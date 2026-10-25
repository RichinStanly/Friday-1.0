"""FRIDAY Text-to-Speech Engine with Kokoro (ONNX) and SAPI5 fallback."""
from __future__ import annotations

import logging
import os
import queue
import tempfile
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

KOKORO_AVAILABLE = False
try:
    import kokoro_onnx
    import soundfile as sf
    KOKORO_AVAILABLE = True
except ImportError:
    pass

class TTSManager:
    """Manages TTS engines, defaulting to Kokoro if available, with SAPI5 fallback."""
    def __init__(self, data_dir: Path, on_amplitude: Callable[[float], None] | None = None) -> None:
        self.on_amplitude = on_amplitude
        self._queue: queue.Queue[tuple[str, Callable[[], None] | None, threading.Event]] = queue.Queue()
        self._current_cancel: threading.Event | None = None
        self._lock = threading.Lock()
        self.is_speaking = False

        self.engine_name = "SAPI5"
        self.kokoro = None

        self.voice_pack = "Cinematic"
        self.speed = 1.0

        if KOKORO_AVAILABLE:
            model_path = data_dir / "tts" / "kokoro-v1.0.onnx"
            voices_path = data_dir / "tts" / "voices-v1.0.bin"
            if model_path.exists() and voices_path.exists():
                try:
                    self.kokoro = kokoro_onnx.Kokoro(str(model_path), str(voices_path))
                    self.engine_name = "Kokoro"
                except Exception:
                    logger.exception("Failed to initialize Kokoro")

        self._thread = threading.Thread(target=self._loop, daemon=True, name="friday-tts")
        self._thread.start()

    def set_config(self, engine: str, pack: str, speed: float) -> None:
        with self._lock:
            if engine == "Kokoro" and self.kokoro is not None:
                self.engine_name = "Kokoro"
            else:
                self.engine_name = "SAPI5"
            self.voice_pack = pack
            self.speed = speed

    def speak(self, text: str, on_stop: Callable[[], None] | None = None) -> None:
        text = text.strip()
        if text:
            self._queue.put((text, on_stop, threading.Event()))

    def stop(self) -> None:
        with self._lock:
            if self._current_cancel is not None:
                self._current_cancel.set()
        while True:
            try:
                _text, callback, _cancel = self._queue.get_nowait()
            except queue.Empty:
                break
            if callback:
                self._safe_callback(callback)

    @staticmethod
    def _safe_callback(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            logger.exception("TTS completion callback failed")

    def _set_speaking(self, value: bool, cancel: threading.Event | None = None) -> None:
        with self._lock:
            self.is_speaking = value
            self._current_cancel = cancel if value else None

    def _loop(self) -> None:
        import sounddevice as sd
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            sapi = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception:
            sapi = None

        while True:
            text, callback, cancel = self._queue.get()
            self._set_speaking(True, cancel)
            try:
                if self.engine_name == "Kokoro" and self.kokoro:
                    self._speak_kokoro(sd, text, cancel)
                elif sapi:
                    self._speak_sapi5(sapi, win32com.client, sd, text, cancel)
                else:
                    logger.error("No TTS engine available to speak.")
            except Exception:
                logger.exception("TTS failed")
            finally:
                self._set_speaking(False)
                if callback:
                    self._safe_callback(callback)

    def _get_kokoro_voice(self) -> str:
        # Mapping cinematic presets to Kokoro internal voice IDs if available
        # Kokoro voices usually have names like 'af_heart', 'af_bella', 'am_michael'
        if self.voice_pack == "Cinematic":
            return "af_bella"
        elif self.voice_pack == "Velvet":
            return "af_heart"
        elif self.voice_pack == "Tactical":
            return "af_nicole"
        elif self.voice_pack == "Classic":
            return "af_alloy"
        return "af_bella"

    def _speak_kokoro(self, sd, text: str, cancel: threading.Event) -> None:
        voice = self._get_kokoro_voice()
        try:
            stream = self.kokoro.create_stream(text, voice=voice, speed=self.speed, lang="en-us")
            for samples, sample_rate in stream:
                if cancel.is_set():
                    break
                self._play_audio_array(sd, samples, sample_rate, cancel)
        except Exception as e:
            logger.error(f"Kokoro failed, falling back to SAPI5. Error: {e}")
            with self._lock:
                self.engine_name = "SAPI5"
            # Use SAPI5 for later requests after Kokoro fails.

    def _speak_sapi5(self, sapi, com_client, sd, text: str, cancel: threading.Event) -> None:
        for voice in sapi.GetVoices():
            desc = voice.GetDescription()
            if self.voice_pack in ("Velvet", "Cinematic"):
                if "Zira" in desc or "Female" in desc:
                    sapi.Voice = voice
                    break
            else:
                if "David" in desc or "Male" in desc:
                    sapi.Voice = voice
                    break

        sapi.Rate = int((self.speed - 1.0) * 10)

        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(prefix="friday_tts_", suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            file_stream = com_client.Dispatch("SAPI.SpFileStream")
            file_stream.Open(tmp_path, 3)
            sapi.AudioOutputStream = file_stream
            sapi.Speak(text)
            file_stream.Close()
            if cancel.is_set():
                return
            with wave.open(tmp_path, "rb") as wav:
                sample_rate = wav.getframerate()
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                raw = wav.readframes(wav.getnframes())
            if not raw:
                raise RuntimeError("SAPI produced an empty audio stream")
            audio = np.frombuffer(raw, dtype=np.int16 if sample_width == 2 else np.uint8)
            if sample_width == 1:
                audio = ((audio.astype(np.float32) - 128) * 256).astype(np.int16)
            if channels > 1:
                audio = audio.reshape(-1, channels)[:, 0]

            self._play_audio_array(sd, audio, sample_rate, cancel)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _play_audio_array(self, sd, audio: np.ndarray, sample_rate: int, cancel: threading.Event) -> None:
        position = 0
        def callback(outdata, frames, _time_info, _status) -> None:
            nonlocal position
            if cancel.is_set() or position >= len(audio):
                outdata.fill(0)
                raise sd.CallbackStop()
            length = min(frames, len(audio) - position)
            samples = audio[position:position + length]
            outdata[:length, 0] = samples
            if outdata.shape[1] > 1:
                outdata[:length, 1] = samples
            if length < frames:
                outdata[length:].fill(0)
            position += length
            if self.on_amplitude:
                self.on_amplitude(float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))))

        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16", callback=callback, blocksize=1024):
            while position < len(audio) and not cancel.is_set():
                time.sleep(0.01)

# Backwards compatibility alias for app.py
VoiceSpeaker = TTSManager
