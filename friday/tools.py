from __future__ import annotations

import ast
import datetime as dt
import html
import operator
import os
import platform
import re
import shlex
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from friday.file_manager import FileManager


@dataclass(slots=True)
class ToolResult:
    source: str
    content: str
    external: bool = False
    artifacts: tuple[str, ...] = ()


_TEXT_EXTS = {
    ".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".env", ".sh", ".bat", ".ps1",
    ".csv", ".xml", ".log", ".rst", ".java", ".c", ".cpp", ".h", ".rs",
    ".go", ".rb", ".php", ".swift", ".kt", ".sql",
}

# Shell commands that are always safe (read-only, no side effects)
_SAFE_COMMANDS = {
    "dir", "ls", "pwd", "echo", "whoami", "hostname", "ipconfig",
    "git log", "git status", "git branch", "git diff",
    "pip list", "pip show", "python --version", "node --version",
    "systeminfo", "tasklist", "netstat", "ping",
    "cat", "type", "head", "tail", "wc", "find", "where",
}


class ToolEngine:
    """Safe, modular tools. New tools are added here, never into the UI."""
    _operators = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg,
    }

    def __init__(self, web_enabled: bool = False, store=None) -> None:
        self.web_enabled = web_enabled
        self.store = store
        self.file_manager = FileManager()


    def calculator(self, expression: str) -> ToolResult:
        def evaluate(node: ast.AST) -> float:
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if abs(node.value) > 1_000_000_000:
                    raise ValueError("numbers must be smaller than one billion")
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in self._operators:
                left, right = evaluate(node.left), evaluate(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 12:
                    raise ValueError("exponents must be 12 or smaller")
                result = self._operators[type(node.op)](left, right)
                if abs(result) > 1_000_000_000_000:
                    raise ValueError("result is too large")
                return result
            if isinstance(node, ast.UnaryOp) and type(node.op) in self._operators:
                return self._operators[type(node.op)](evaluate(node.operand))
            raise ValueError("Only basic arithmetic is supported")
        try:
            answer = evaluate(ast.parse(expression, mode="eval").body)
            return ToolResult("Local calculator", f"{expression} = {answer}")
        except Exception as error:
            return ToolResult("Local calculator", f"Could not calculate that safely: {error}")

    def time_and_date(self) -> ToolResult:
        return ToolResult("Local clock", dt.datetime.now().astimezone().strftime("%A, %d %B %Y — %I:%M %p %Z"))

    def system_info(self) -> ToolResult:
        return ToolResult("Local system", f"{platform.system()} {platform.release()} on {platform.machine()}; Python {platform.python_version()}")

    def fetch_webpage(self, url: str) -> ToolResult:
        if not self.web_enabled:
            return ToolResult("Web", "Web tools are disabled. Enable them in Settings.", False)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return ToolResult("Web", "Only http and https URLs can be opened.", True)
        request = urllib.request.Request(url, headers={"User-Agent": "Friday-Local-Assistant/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = response.read(120_000).decode(errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            return ToolResult("Web", f"Could not retrieve that page: {error}", True)
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", " ", raw, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip()[:12_000]
        return ToolResult(f"External webpage: {url}", text, True)

    def search_web(self, query: str) -> ToolResult:
        """Retrieve current search results; the local model remains responsible for the answer."""
        if not self.web_enabled:
            return ToolResult("Web", "Web tools are disabled. Enable them in Settings.", False)
        query = query.strip()[:240]
        if not query:
            return ToolResult("Web", "I need a topic to search for.", False)
        search_url = "https://lite.duckduckgo.com/lite/"
        data = urllib.parse.urlencode({'q': query}).encode('utf-8')
        request = urllib.request.Request(search_url, data=data, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = response.read(180_000).decode(errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            raw = ""
        if not raw or "challenge" in raw.lower() or "select all squares" in raw.lower():
            fallback_url = "https://www.bing.com/search?q=" + urllib.parse.quote_plus(query)
            fallback_request = urllib.request.Request(fallback_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            try:
                with urllib.request.urlopen(fallback_request, timeout=12) as response:
                    raw = response.read(180_000).decode(errors="replace")
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
                if not raw:
                    return ToolResult("Web", f"Could not search the web: {error}", True)

        results = []
        for tr in re.finditer(r'<tr[^>]*>(.*?)</tr>', raw, re.I | re.S):
            tr_html = tr.group(1)
            if 'result-link' in tr_html:
                href = re.search(r'href=["\']([^"\']+)["\']', tr_html, re.I)
                text = re.search(r'>([^<]+)</a>', tr_html, re.I)
                if href and text:
                    url = html.unescape(href.group(1))
                    if 'uddg=' in url:
                        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                        if 'uddg' in q: url = q['uddg'][0]
                    title = html.unescape(text.group(1).strip())
                    results.append({'title': title, 'url': url, 'snippet': ''})
            elif 'result-snippet' in tr_html and results:
                snippet = re.search(r'<td[^>]*class=["\']result-snippet["\'][^>]*>(.*?)</td>', tr_html, re.I | re.S)
                if snippet:
                    s = re.sub(r'<[^>]+>', '', snippet.group(1)).strip()
                    results[-1]['snippet'] = html.unescape(s)

        if results:
            formatted = "\n\n".join(f"[{r['title']}]({r['url']})\n{r['snippet']}" for r in results[:8])
            return ToolResult(f"External web search: {query}", formatted, True)

        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", " ", raw, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip()
        if "Any Time Past Day" in text:
            text = text.split("Any Time Past Day", 1)[1]
        text = html.unescape(text).strip()[:8000]
        return ToolResult(f"External web search: {query}", text, True)


    def clipboard_read(self) -> ToolResult:
        """Read the current contents of the system clipboard."""
        try:
            import pyperclip
            text = pyperclip.paste()
            if not text or not text.strip():
                return ToolResult("Clipboard", "The clipboard is currently empty.")
            return ToolResult("Clipboard", text.strip()[:12_000])
        except Exception as e:
            return ToolResult("Clipboard", f"Could not read clipboard: {e}")

    def clipboard_write(self, text: str) -> ToolResult:
        """Write text to the system clipboard."""
        try:
            import pyperclip
            pyperclip.copy(text)
            preview = text[:80] + ("…" if len(text) > 80 else "")
            return ToolResult("Clipboard", f"✅ Copied to clipboard: {preview}")
        except Exception as e:
            return ToolResult("Clipboard", f"Could not write to clipboard: {e}")


    def search_files(self, query: str) -> ToolResult:
        """Search for files within the allowed workspace."""
        try:
            results = self.file_manager.search_files(query)
            if not results:
                return ToolResult("File Search", f"No files found matching: {query}")
            return ToolResult("File Search", "Found matching files:\n" + "\n".join(f"{i+1}. {str(p)}" for i, p in enumerate(results)))
        except Exception as e:
            return ToolResult("File Search", f"Error searching files: {e}")

    def list_directory(self, path: str = None) -> ToolResult:
        """List directory contents within the allowed workspace."""
        try:
            results = self.file_manager.list_directory(path)
            title = f"Directory listing for {path}" if path else "Workspace listing"
            if not results:
                return ToolResult("Directory List", f"{title} is empty.")
            return ToolResult("Directory List", f"{title}:\n" + "\n".join(results))
        except PermissionError as e:
            return ToolResult("Directory List", str(e))
        except Exception as e:
            return ToolResult("Directory List", f"Error: {e}")

    def file_info(self, path: str) -> ToolResult:
        """Get metadata for a file in the allowed workspace."""
        try:
            info = self.file_manager.file_info(path)
            s = "\n".join(f"{k}: {v}" for k, v in info.items())
            return ToolResult("File Info", s)
        except PermissionError as e:
            return ToolResult("File Info", str(e))
        except Exception as e:
            return ToolResult("File Info", f"Error: {e}")

    def open_file(self, path: str) -> ToolResult:
        """Open a file with the default OS application."""
        try:
            success = self.file_manager.open_file(path)
            if success:
                return ToolResult("Open File", f"Opened successfully: {path}")
            return ToolResult("Open File", f"Failed to open (unsupported OS): {path}")
        except PermissionError as e:
            return ToolResult("Open File", str(e))
        except Exception as e:
            return ToolResult("Open File", f"Error: {e}")

    def delete_file(self, path: str) -> ToolResult:
        """Delete a file within the allowed workspace."""
        try:
            success = self.file_manager.delete_file(path)
            if success:
                return ToolResult("Delete File", f"File deleted successfully: {path}")
            return ToolResult("Delete File", f"Failed to delete file: {path}")
        except PermissionError as e:
            return ToolResult("Delete File", str(e))
        except Exception as e:
            return ToolResult("Delete File", f"Error deleting file: {e}")

    def read_file(self, path: str) -> ToolResult:
        """Read a local file and return its contents."""
        p = self.file_manager.get_safe_path(path)
        if not p:
            return ToolResult("Local file", f"Access Denied or Path Traversing Outside Allowed Workspace: {path}")
        if not p.exists():
            return ToolResult("Local file", f"File not found: {p}")
        if not p.is_file():
            return ToolResult("Local file", f"Not a file: {p}")
        if p.stat().st_size > 2_000_000:
            return ToolResult("Local file", f"File is too large to read (>{2_000_000 // 1024}KB): {p.name}")

        suffix = p.suffix.lower()

        if suffix == ".pdf":
            try:
                import fitz
                doc = fitz.open(str(p))
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
                return ToolResult(f"Local file: {p.name}", text.strip()[:12_000])
            except ImportError:
                return ToolResult("Local file", "PDF reading requires PyMuPDF. Run: pip install pymupdf")
            except Exception as e:
                return ToolResult("Local file", f"Could not read PDF: {e}")

        if suffix not in _TEXT_EXTS:
            return ToolResult("Local file", f"Unsupported file type: {suffix}. Supported: {', '.join(sorted(_TEXT_EXTS))}")

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            return ToolResult(f"Local file: {p.name}", content[:12_000])
        except Exception as e:
            return ToolResult("Local file", f"Could not read file: {e}")



    def search_videos(self, query: str, count: int = 4) -> ToolResult:
        if not self.web_enabled:
            return ToolResult('Video Search', 'Web tools are disabled. Enable them in Settings.', False)
        try:
            from ddgs import DDGS
            # We use text search because DDGS video endpoint frequently 403s.
            # Appending 'site:youtube.com' or just 'video' works reliably.
            # If not explicitly requesting a platform, we prefer youtube for embeds.
            if "youtube" not in query.lower():
                query = f"{query} site:youtube.com"

            results = DDGS().text(query, max_results=count)
            if not results:
                return ToolResult("Video Search", f"No videos found for: {query}")

            media_list = []
            html_chunks = []
            for r in results:
                title = r.get("title", "")
                url = r.get("href", "")
                snippet = r.get("body", "")

                embed_url = ""
                thumbnail = ""
                if "youtube.com/watch?v=" in url:
                    vid = url.split("v=")[1].split("&")[0]
                    embed_url = f"https://www.youtube.com/embed/{vid}"
                    thumbnail = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
                elif "youtu.be/" in url:
                    vid = url.split("youtu.be/")[1].split("?")[0]
                    embed_url = f"https://www.youtube.com/embed/{vid}"
                    thumbnail = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"

                media = {
                    "type": "video",
                    "title": title,
                    "url": url,
                    "thumbnail": thumbnail,
                    "source": "YouTube" if embed_url else "Web",
                    "snippet": snippet,
                    "embed_url": embed_url
                }
                media_list.append(media)
                html_chunks.append(f"**{title}**\n{url}\n")

            return ToolResult("Video Search", "\n".join(html_chunks), artifacts=media_list)
        except Exception as e:
            return ToolResult("Video Search", f"Search failed: {e}")

    def search_images(self, query: str, count: int = 20) -> ToolResult:
        if not self.web_enabled:
            return ToolResult('Image Search', 'Web tools are disabled. Enable them in Settings.', False)
        try:
            from friday.image_search import ImageSearchHub
            hub = ImageSearchHub(self.store)
            enhanced_query, results = hub.search_images(query, page=1)

            if not results:
                return ToolResult("Image Search", f"No images found for: {query}")

            # Keep image metadata for the UI; don't download every result here.
            import json
            payload = {
                "query": enhanced_query,
                "results": [r.to_dict() for r in results]
            }
            return ToolResult(
                "Image Search",
                "",
                external=True,
                artifacts=[json.dumps(payload)]
            )
        except Exception as e:
            return ToolResult("Image Search", f"Failed to search images: {str(e)}")


    def run_shell(self, command: str) -> ToolResult:
        """Execute a safe, read-only shell command and return the output."""
        cmd = command.strip()
        cmd_lower = cmd.lower()
        allowed = any(
            cmd_lower == safe or cmd_lower.startswith(safe + " ")
            for safe in _SAFE_COMMANDS
        )
        if not allowed:
            safe_list = ", ".join(sorted(_SAFE_COMMANDS))
            return ToolResult(
                "Shell",
                f"Command not in the safe allowlist. Allowed commands: {safe_list}\n"
                f"To run '{cmd}', the user must explicitly approve it in Settings."
            )
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=15, encoding="utf-8", errors="replace"
            )
            output = (result.stdout or "") + (result.stderr or "")
            output = output.strip()[:8_000]
            return ToolResult(f"Shell: {cmd}", output or "(no output)")
        except subprocess.TimeoutExpired:
            return ToolResult("Shell", f"Command timed out: {cmd}")
        except Exception as e:
            return ToolResult("Shell", f"Command failed: {e}")


    def send_notification(self, title: str, message: str, delay_seconds: int = 0) -> ToolResult:
        """Send a Windows system tray notification, optionally after a delay."""
        def _notify():
            if delay_seconds > 0:
                threading.Event().wait(delay_seconds)
            try:
                from plyer import notification
                notification.notify(
                    title=title,
                    message=message,
                    app_name="Friday",
                    timeout=8,
                )
            except Exception as e:
                # Fallback: PowerShell balloon tip
                ps = (
                    f'Add-Type -AssemblyName System.Windows.Forms; '
                    f'$n = New-Object System.Windows.Forms.NotifyIcon; '
                    f'$n.Icon = [System.Drawing.SystemIcons]::Information; '
                    f'$n.Visible = $true; '
                    f'$n.ShowBalloonTip(5000, "{title}", "{message}", [System.Windows.Forms.ToolTipIcon]::Info)'
                )
                subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=10)

        threading.Thread(target=_notify, daemon=True).start()

        if delay_seconds > 0:
            mins = delay_seconds // 60
            secs = delay_seconds % 60
            when = f"{mins}m {secs}s" if mins else f"{secs}s"
            return ToolResult("Notification", "✅ Reminder set in " + when + ": " + message)
        return ToolResult("Notification", "✅ Notification sent: " + message)


    def screenshot(self) -> ToolResult:
        """Capture the screen and save to a temp file; return description + path."""
        try:
            from PIL import ImageGrab, Image
            img = ImageGrab.grab()
            width, height = img.size

            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", prefix="friday_screenshot_", delete=False
            )
            img.save(tmp.name, "PNG")
            tmp.close()

            img_small = img.resize((100, 100))
            pixels = list(img_small.getdata())
            avg_r = sum(p[0] for p in pixels) // len(pixels)
            avg_g = sum(p[1] for p in pixels) // len(pixels)
            avg_b = sum(p[2] for p in pixels) // len(pixels)

            return ToolResult(
                "Screenshot",
                f"Screenshot captured: {width}×{height} pixels\n"
                f"Saved to: {tmp.name}\n"
                f"Average color (R:{avg_r} G:{avg_g} B:{avg_b})\n\n"
                f"Note: Vision analysis requires a multimodal model (e.g. llava). "
                f"The screenshot has been saved and is ready for manual inspection."
            )
        except Exception as e:
            return ToolResult("Screenshot", f"Could not capture screen: {e}")


    def memory_list(self) -> ToolResult:
        """Return all stored memories."""
        if not self.store:
            return ToolResult("Memory", "Memory store not available.")
        try:
            memories = self.store.all_memories()
            if not memories:
                return ToolResult("Memory", "No memories stored yet. Tell me something to remember!")
            lines = "\n".join(f"- {m}" for m in memories)
            return ToolResult("Memory", f"I have {len(memories)} memories:\n{lines}")
        except Exception as e:
            return ToolResult("Memory", f"Could not read memories: {e}")

    def memory_add(self, content: str, category: str = "USER") -> ToolResult:
        """Save a new memory."""
        if not self.store:
            return ToolResult("Memory", "Memory store not available.")
        try:
            self.store.save_memory(content.strip(), category)
            return ToolResult("Memory", f"Got it! Remembered [{category.upper()}]: " + content.strip())
        except Exception as e:
            return ToolResult("Memory", f"Could not save memory: {e}")

    def memory_forget(self, keyword: str) -> ToolResult:
        """Delete memories matching a keyword."""
        if not self.store:
            return ToolResult("Memory", "Memory store not available.")
        try:
            count = self.store.delete_memories_matching(keyword.strip())
            if count == 0:
                return ToolResult("Memory", f"No memories found containing '{keyword}'.")
            return ToolResult("Memory", f"✅ Deleted {count} memory/memories containing '{keyword}'.")
        except Exception as e:
            return ToolResult("Memory", f"Could not delete memories: {e}")

    def clipboard_read(self) -> ToolResult:
        try:
            import pyperclip
            text = pyperclip.paste()
            if not text or not text.strip():
                return ToolResult("Clipboard", "Clipboard is empty or not text.")
            return ToolResult("Clipboard", f"Clipboard contents:\n{text[:2000]}")
        except Exception as e:
            return ToolResult("Clipboard", f"Failed to read clipboard: {e}")

    def clipboard_write(self, text: str) -> ToolResult:
        try:
            import pyperclip
            pyperclip.copy(text)
            return ToolResult("Clipboard", "Text copied to clipboard.")
        except Exception as e:
            return ToolResult("Clipboard", f"Failed to write clipboard: {e}")

    def clipboard_clear(self) -> ToolResult:
        try:
            import pyperclip
            pyperclip.copy("")
            return ToolResult("Clipboard", "Clipboard cleared.")
        except Exception as e:
            return ToolResult("Clipboard", f"Failed to clear clipboard: {e}")

    def launch_app(self, app_name: str) -> ToolResult:
        from friday.permission_manager import engine
        target = engine.is_app_allowed(app_name)
        if not target:
            return ToolResult("Application Launcher", f"{app_name} is not currently allowed. Add it in Control Center -> Permissions & Access.")
        try:
            import os
            os.startfile(target)
            return ToolResult("Application Launcher", f"Launched {app_name}.")
        except Exception as e:
            return ToolResult("Application Launcher", f"Failed to launch {app_name}: {e}")

    def process_info(self) -> ToolResult:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            lines = [f"CPU Usage: {cpu}%", f"RAM Usage: {mem.percent}% ({mem.used // (1024**2)} MB / {mem.total // (1024**2)} MB)"]
            common = {"ollama", "chrome", "code", "python", "figma"}
            running = set()
            for p in psutil.process_iter(['name']):
                name = p.info['name']
                if name:
                    name_lower = name.lower()
                    for c in common:
                        if c in name_lower:
                            running.add(c)
            if running:
                lines.append("Common apps running: " + ", ".join(running))
            return ToolResult("Process Info", "\n".join(lines))
        except Exception as e:
            return ToolResult("Process Info", f"Failed to read process info: {e}")

    def audio_control(self, action: str) -> ToolResult:
        try:
            import ctypes
            VK_VOLUME_MUTE = 0xAD
            VK_VOLUME_DOWN = 0xAE
            VK_VOLUME_UP = 0xAF
            vk = None
            if action == "mute": vk = VK_VOLUME_MUTE
            elif action == "down": vk = VK_VOLUME_DOWN
            elif action == "up": vk = VK_VOLUME_UP
            else: return ToolResult("Audio Control", f"Unknown action: {action}")

            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            return ToolResult("Audio Control", f"Volume {action} sent.")
        except Exception as e:
            return ToolResult("Audio Control", f"Failed to change volume: {e}")

    def take_screenshot(self) -> ToolResult:
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if not app:
                return ToolResult("Screenshot", "Cannot take screenshot: No Qt application.")
            screen = app.primaryScreen()
            pixmap = screen.grabWindow(0)
            path = "screenshot.png"
            pixmap.save(path)
            return ToolResult("Screenshot", f"Screenshot saved to {path}.")
        except Exception as e:
            return ToolResult("Screenshot", f"Failed to take screenshot: {e}")

    def archive_inspect(self, path: str) -> ToolResult:
        try:
            p = self.file_manager.get_safe_path(path)
            if not p or not p.exists():
                return ToolResult("Archive Inspect", f"File not found: {path}")
            import zipfile
            with zipfile.ZipFile(p, 'r') as zf:
                names = zf.namelist()
            res = "\n".join(names[:100])
            if len(names) > 100: res += f"\n... and {len(names)-100} more files."
            return ToolResult("Archive Inspect", f"Contents of {path}:\n{res}")
        except Exception as e:
            return ToolResult("Archive Inspect", f"Failed to read archive: {e}")

    def archive_extract(self, path: str) -> ToolResult:
        try:
            p = self.file_manager.get_safe_path(path)
            if not p or not p.exists():
                return ToolResult("Archive Extract", f"File not found: {path}")
            # Target is the root of the workspace to prevent traversal
            target_dir = self.file_manager.allowed_roots[0] / p.stem

            import zipfile
            with zipfile.ZipFile(p, 'r') as zf:
                for member in zf.infolist():
                    if '..' in member.filename or member.filename.startswith('/'):
                        return ToolResult("Archive Extract", f"Blocked: Archive contains unsafe paths.")

                zf.extractall(target_dir)
            return ToolResult("Archive Extract", f"Extracted {path} into {target_dir}")
        except Exception as e:
            return ToolResult("Archive Extract", f"Failed to extract archive: {e}")
