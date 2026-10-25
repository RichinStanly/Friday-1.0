from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from friday.config import APP_DIR, OLLAMA_URL
from friday.models import LocalModel


class _VisibleResponseFilter:
    """Strip private <think> blocks from streamed model output."""

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, chunk: str, final: bool = False) -> str:
        self._buffer += chunk
        output = []
        while self._buffer:
            marker = self._CLOSE if self._inside else self._OPEN
            index = self._buffer.find(marker)
            if index >= 0:
                if not self._inside:
                    output.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(marker):]
                self._inside = not self._inside
                continue
            if final:
                if not self._inside:
                    output.append(self._buffer)
                self._buffer = ""
                break
            safe_length = max(0, len(self._buffer) - len(marker) + 1)
            if safe_length:
                if not self._inside:
                    output.append(self._buffer[:safe_length])
                self._buffer = self._buffer[safe_length:]
            break
        return "".join(output)


class LocalModelProvider(ABC):
    """Contract for local runtimes. Add LM Studio etc. without touching the UI."""

    @abstractmethod
    def available_models(self, aliases: dict[str, str] = None) -> list[LocalModel]: ...

    @abstractmethod
    def stream_chat(self, model: str, messages: list[dict], on_token: Callable[[str], None], cancelled: Callable[[], bool]) -> None: ...


class OllamaProvider(LocalModelProvider):
    def __init__(self, base_url: str = OLLAMA_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, payload: dict | None = None, timeout: float = 8) -> urllib.request.addinfourl:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(request, timeout=timeout)

    def is_running(self) -> bool:
        try:
            self._request("/api/tags", timeout=1.5).close()
            return True
        except (urllib.error.URLError, socket.timeout, OSError):
            return False

    def available_models(self, aliases: dict[str, str] = None) -> list[LocalModel]:
        try:
            with self._request("/api/tags") as response:
                payload = json.load(response)
        except (urllib.error.URLError, socket.timeout, OSError):
            return []

        models = []
        aliases = aliases or {}
        for item in payload.get("models", []):
            name = item.get("name", "unknown")
            disp = name
            cap = ""
            if name == "qwen2.5:7b":
                disp = "FRIDAY Pro"
                cap = "General Intelligence"
            elif name == "qwen3-vl:8b":
                disp = "FRIDAY Pro Vision"
                cap = "Vision + Image Intelligence"
            elif name == "huihui_ai/dolphin3-abliterated:8b":
                disp = "FRIDAY Thunder Pro"
                cap = "Creative Image Prompt Generation"

            if name in aliases and aliases[name]:
                disp = aliases[name]

            models.append(LocalModel(
                name=name,
                size_bytes=item.get("size", 0),
                modified_at=item.get("modified_at", ""),
                details=item.get("details", {}).get("family", ""),
                display_name=disp,
                capability=cap
            ))
        return models

    def load_model(self, model_name: str, keep_alive: str = "5m") -> None:
        """Load a local model into Ollama's runtime without generating a reply."""
        payload = {"model": model_name, "prompt": "", "stream": False, "keep_alive": keep_alive}
        with self._request("/api/generate", payload, timeout=600) as response:
            result = json.load(response)
        if result.get("error"):
            raise RuntimeError(result["error"])

    def stream_chat(self, model: str, messages: list[dict], on_token: Callable[[str], None], cancelled: Callable[[], bool]) -> None:
        payload = {"model": model, "messages": messages, "stream": True, "options": {"temperature": 0.7}}
        import http.client
        import urllib.parse
        import threading
        import time
        import socket

        url = urllib.parse.urlparse(self.base_url)
        host = url.hostname or "127.0.0.1"
        port = url.port or 11434

        conn = http.client.HTTPConnection(host, port, timeout=600)
        data = json.dumps(payload).encode()

        done = False
        def monitor():
            while not done:
                if cancelled():
                    if conn.sock:
                        try:
                            conn.sock.shutdown(socket.SHUT_RDWR)
                            conn.sock.close()
                        except: pass
                    break
                time.sleep(0.2)

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

        try:
            conn.request("POST", url.path + "/api/chat", body=data, headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            if response.status >= 400:
                if response.status == 400:
                    raise RuntimeError(f"Ollama returned 400 Bad Request. The model '{model}' may not exist or the request is malformed.")
                elif response.status == 404:
                    raise RuntimeError(f"Model '{model}' not found in Ollama. Please download it first.")
                raise RuntimeError(f"Ollama HTTP Error {response.status}: {response.reason}")

            visible_filter = _VisibleResponseFilter()
            for raw_line in response:
                if cancelled():
                    break
                if not raw_line.strip():
                    continue
                event = json.loads(raw_line)
                if event.get("error"):
                    raise RuntimeError(event["error"])
                token = event.get("message", {}).get("content", "")
                if token:
                    visible = visible_filter.feed(token)
                    if visible:
                        on_token(visible)
            tail = visible_filter.feed("", final=True)
            if tail:
                on_token(tail)
        except Exception as error:
            if cancelled():
                pass
            else:
                if isinstance(error, (ConnectionError, socket.timeout, TimeoutError, OSError)):
                    raise RuntimeError("Ollama is not available. Start Ollama, then select an installed local model.") from error
                raise
        finally:
            done = True
            conn.close()

    def pull(self, model_name: str, progress: Callable[[str], None]) -> None:
        with self._request("/api/pull", {"name": model_name, "stream": True}, timeout=30) as response:
            for line in response:
                if line.strip():
                    event = json.loads(line)
                    progress(event.get("status", "Preparing local model"))

    def delete(self, model_name: str) -> None:
        self._request("/api/delete", {"name": model_name}).close()


class FridayAutoRouter:
    """A deliberately local-only routing heuristic for installed models."""

    def choose(self, prompt: str, models: list[LocalModel]) -> str | None:
        if not models:
            return None

        # Dolphin is dedicated to image prompt expansion, avoid selecting it for general chat
        general_models = [m for m in models if "dolphin" not in m.name.lower()]
        if not general_models:
            general_models = models

        lowered = prompt.lower()
        coding = any(word in lowered for word in ("code", "python", "javascript", "debug", "function", "api", "sql"))
        reasoning = any(word in lowered for word in ("analyze", "reason", "compare", "plan", "strategy", "explain"))
        preferred = ("coder", "code", "deepseek") if coding else (("70b", "32b", "27b", "14b", "reason") if reasoning else ("3b", "4b", "7b", "8b", "qwen", "llama"))
        for hint in preferred:
            match = next((model.name for model in general_models if hint in model.name.lower()), None)
            if match:
                return match
        return general_models[0].name

class OllamaLauncher:
    """Start a local Ollama server if one is not already reachable.

    Design constraints:
    - Never opens a visible window.
    - Derives the models directory from the project root (APP_DIR/models) so
      it works for any user without hardcoding a username.
    - Checks %LOCALAPPDATA% for the standard Windows install location first,
      then falls back to `ollama` on PATH (Linux/macOS / custom installs).
    - Polls for readiness instead of sleeping a fixed duration.
    - All failures return False; the caller decides how to respond.
    """

    _MODELS_DIR: Path = APP_DIR / "models"
    _POLL_INTERVAL: float = 0.5   # seconds between readiness probes
    _TIMEOUT: float = 30.0        # seconds before giving up

    def __init__(self, provider: OllamaProvider) -> None:
        self._provider = provider

    @classmethod
    def _configured_models_dir(cls) -> Path | None:
        explicit = os.environ.get("OLLAMA_MODELS", "").strip()
        if explicit and Path(explicit).is_dir():
            return Path(explicit)
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            log_path = Path(local_app_data) / "Ollama" / "server.log"
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            for line in reversed(lines):
                match = re.search(r"OLLAMA_MODELS:(.*?)\s+OLLAMA_NOHISTORY:", line)
                if match:
                    candidate = Path(match.group(1).strip().strip('"'))
                    if candidate.is_dir():
                        return candidate
        return cls._MODELS_DIR if cls._model_store_has_manifests(cls._MODELS_DIR) else None

    @staticmethod
    def _model_store_has_manifests(models_dir: Path | None) -> bool:
        manifests = models_dir / "manifests" if models_dir else None
        if not manifests or not manifests.is_dir():
            return False
        try:
            return any(path.is_file() for path in manifests.rglob("*"))
        except OSError:
            return False

    @staticmethod
    def _stop_empty_misconfigured_server() -> bool:
        """Stop only an Ollama process listening on the local API port."""
        if sys.platform != "win32":
            return False
        try:
            result = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=5, check=False)
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) < 5 or fields[0].upper() != "TCP" or not fields[1].lower().endswith(":11434") or fields[3].upper() != "LISTENING":
                    continue
                pid = fields[4]
                task = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=5, check=False)
                if not task.stdout.strip().lower().startswith('"ollama.exe"'):
                    continue
                stopped = subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, text=True, timeout=10, check=False)
                return stopped.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
        return False


    def _find_executable(self) -> Path | None:
        import shutil
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            candidate = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
            if candidate.is_file():
                return candidate
        system_candidate = Path(r"C:\Program Files\Ollama\ollama.exe")
        if system_candidate.is_file():
            return system_candidate
        which = shutil.which("ollama")
        if which:
            return Path(which)
        return None


    def ensure_running(self) -> bool:
        """Return True once Ollama is ready; start it if needed.

        Returns False if Ollama is not installed or does not become ready
        within the timeout. Friday must still launch normally in that case.
        """
        models_dir = self._configured_models_dir()
        if self._provider.is_running():
            if self._provider.available_models():
                return True
            if not self._model_store_has_manifests(models_dir):
                return True
            if not self._stop_empty_misconfigured_server():
                return False

        exe = self._find_executable()
        if exe is None:
            return False

        env = os.environ.copy()
        if models_dir:
            env["OLLAMA_MODELS"] = str(models_dir)
        env["OLLAMA_HOST"] = "127.0.0.1:11434"

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            subprocess.Popen(
                [str(exe), "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError:
            return False

        # Poll until the server responds or the timeout expires.
        deadline = time.monotonic() + self._TIMEOUT
        while time.monotonic() < deadline:
            if self._provider.is_running():
                if not self._model_store_has_manifests(models_dir) or self._provider.available_models():
                    return True
            time.sleep(self._POLL_INTERVAL)
        return False
