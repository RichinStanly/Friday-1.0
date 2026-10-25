"""voice.py – Local speech-to-text using faster-whisper + sounddevice.

Design:
  - VoiceRecorder captures mic audio into a NumPy buffer in a background thread.
  - VoiceTranscriber wraps faster-whisper and runs transcription in a thread pool.
  - The Qt UI (in app.py) owns a single VoiceRecorder and calls start/stop.
  - Results are delivered via a simple callback to keep this module Qt-free.
"""
from __future__ import annotations

import io
import logging
import threading
import wave
from collections.abc import Callable

import numpy as np

logger = logging.getLogger(__name__)


_SAMPLE_RATE = 16_000   # Whisper is trained on 16 kHz mono
_CHANNELS    = 1
_DTYPE       = "int16"


class VoiceRecorder:
    """Push-to-talk microphone recorder.

    Usage::
        rec = VoiceRecorder(on_done=my_callback)
        rec.start()   # begins capturing
        rec.stop()    # stops capturing, fires on_done(wav_bytes)
    """

    def __init__(self, on_done: Callable[[bytes], None]) -> None:
        self._on_done  = on_done
        self._frames: list[np.ndarray] = []
        self._lock     = threading.Lock()
        self._stream   = None
        self.recording = False

    def start(self) -> None:
        import sounddevice as sd  # import lazily so the module is still
                                  # importable when sounddevice is absent

        with self._lock:
            if self.recording:
                logger.warning("VoiceRecorder.start ignored; recorder is already active")
                return
            self._frames.clear()
            self.recording = True

        def _callback(indata: np.ndarray, frames: int, time, status) -> None:
            if status:
                logger.debug("sounddevice status: %s", status)
            with self._lock:
                self._frames.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=_SAMPLE_RATE, channels=_CHANNELS, dtype=_DTYPE, callback=_callback,
            )
            self._stream.start()
            logger.info("VoiceRecorder started")
        except Exception:
            with self._lock:
                self.recording = False
                self._stream = None
            logger.exception("VoiceRecorder failed to start")
            raise

    def stop(self) -> None:
        with self._lock:
            if not self.recording:
                return
            self.recording = False
            stream, self._stream = self._stream, None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:
                logger.exception("VoiceRecorder stream failed to stop cleanly")

        with self._lock:
            frames = list(self._frames)

        if not frames:
            self._on_done(b"")
            return

        audio = np.concatenate(frames, axis=0).flatten()
        wav_bytes = _to_wav_bytes(audio)
        logger.info("VoiceRecorder stopped with %.2fs of audio", len(audio) / _SAMPLE_RATE)
        threading.Thread(target=self._on_done, args=(wav_bytes,), daemon=True).start()


def _to_wav_bytes(audio: np.ndarray) -> bytes:
    """Convert int16 NumPy array → in-memory WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


class ContinuousRecorder:
    """Continuously listens and emits audio chunks when speech is detected based on RMS energy."""

    def __init__(self, on_speech_start: Callable[[], None], on_speech_end: Callable[[bytes], None], on_amplitude: Callable[[float], None] = None):
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self.on_amplitude = on_amplitude

        self._stream = None
        self._is_listening = False
        self._lock = threading.Lock()

        self.energy_threshold = 300
        self.silence_duration = 1.5

        self.ignore_mic = False
        # During an assistant response the recorder stays muted to avoid echo.
        # A close, deliberately spoken command can still break through this
        # conservative threshold and cancel the active turn.
        self.allow_barge_in = False
        self.barge_in_threshold = 1400.0
        self._frames = []
        self._speaking = False
        self._silence_frames = 0
        self._silence_limit = int(self.silence_duration * _SAMPLE_RATE / 1024)

    def start(self):
        import sounddevice as sd
        with self._lock:
            if self._is_listening:
                logger.warning("ContinuousRecorder.start ignored; listener is already active")
                return
            self._frames.clear()
            self._speaking = False
            self._silence_frames = 0
            self._rms_history = []
            self._is_listening = True

        def _callback(indata: np.ndarray, frames: int, time, status) -> None:
            if not self._is_listening:
                return
            if status:
                logger.warning("Audio input status: %s", status)

            # Calculate RMS amplitude properly by preventing int16 overflow
            rms = float(np.sqrt(np.mean(indata.astype(np.float32)**2)))

            if self.ignore_mic:
                if not self.allow_barge_in or rms < self.barge_in_threshold:
                    self._speaking = False
                    self._frames.clear()
                    return
                logger.info("Voice barge-in detected (RMS %.0f)", rms)
                self.ignore_mic = False
                self.allow_barge_in = False

            if self.on_amplitude:
                self.on_amplitude(rms)

            with self._lock:
                # Keep a rolling history of RMS to find the true noise floor
                if not hasattr(self, '_rms_history'):
                    self._rms_history = []

                self._rms_history.append(rms)
                if len(self._rms_history) > 100:
                    self._rms_history.pop(0)

                # The noise floor is the 10th percentile of recent audio
                current_bg = np.percentile(self._rms_history, 10) if len(self._rms_history) >= 10 else rms
                self.energy_threshold = current_bg * 2.5 + 8.0

                if rms > self.energy_threshold:
                    if not self._speaking:
                        self._speaking = True
                        self._frames.clear()
                        logger.info("Voice activity detected")
                        threading.Thread(target=self._safe_speech_start, daemon=True).start()
                    self._silence_frames = 0
                    self._frames.append(indata.copy())
                else:
                    if self._speaking:
                        self._frames.append(indata.copy())
                        self._silence_frames += 1
                        if self._silence_frames > self._silence_limit:
                            self._speaking = False
                            frames_copy = list(self._frames)
                            self._frames.clear()
                            self._process_speech(frames_copy)

        try:
            self._stream = sd.InputStream(
                samplerate=_SAMPLE_RATE, channels=_CHANNELS, dtype=_DTYPE, callback=_callback, blocksize=1024,
            )
            self._stream.start()
            logger.info("ContinuousRecorder started")
        except Exception:
            with self._lock:
                self._is_listening = False
                self._stream = None
            logger.exception("ContinuousRecorder failed to start")
            raise

    def stop(self):
        with self._lock:
            self._is_listening = False
            self._speaking = False
            self._frames.clear()
            stream, self._stream = self._stream, None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:
                logger.exception("ContinuousRecorder stream failed to stop cleanly")
        logger.info("ContinuousRecorder stopped")

    def _safe_speech_start(self) -> None:
        try:
            self.on_speech_start()
        except Exception:
            logger.exception("Voice speech-start callback failed")

    def _process_speech(self, frames):
        if not frames:
            threading.Thread(target=self._safe_speech_end, args=(b"",), daemon=True).start()
            return
        audio = np.concatenate(frames, axis=0).flatten()
        if len(audio) < (_SAMPLE_RATE * 0.5):
            threading.Thread(target=self._safe_speech_end, args=(b"",), daemon=True).start()
            return

        max_val = np.max(np.abs(audio.astype(np.float32)))
        if max_val > 0:
            audio = (audio.astype(np.float32) * (32000.0 / max_val)).astype(np.int16)

        wav_bytes = _to_wav_bytes(audio)
        logger.info("Voice activity ended with %.2fs of audio", len(audio) / _SAMPLE_RATE)
        threading.Thread(target=self._safe_speech_end, args=(wav_bytes,), daemon=True).start()

    def _safe_speech_end(self, wav_bytes: bytes) -> None:
        try:
            self.on_speech_end(wav_bytes)
        except Exception:
            logger.exception("Voice speech-end callback failed")


class VoiceTranscriber:
    """Wraps faster-whisper.  Lazy-loads the model on first use.

    The model is kept alive for the duration of the process so subsequent
    transcriptions are instant (model already in RAM).
    """

    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model      = None
        self._load_lock  = threading.Lock()

    def _load(self):
        from faster_whisper import WhisperModel

        with self._load_lock:
            if self._model is None:
                logger.info("Loading Whisper model '%s'…", self._model_size)
                self._model = WhisperModel(
                    self._model_size,
                    device="cpu",
                    compute_type="int8",
                )
        return self._model

    def transcribe(self, wav_bytes: bytes) -> str:
        """Run transcription on the given wav bytes and return the text."""
        if not wav_bytes:
            return ""
        import tempfile, os
        tmp_path = None
        try:
            model = self._load()
            # faster-whisper works best with a real file path
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_bytes)
                tmp_path = tmp.name

            segments, _info = model.transcribe(
                tmp_path, beam_size=5, language=None, vad_filter=True
            )
            # segments is a lazy generator — must iterate fully here
            text = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info("Transcription result: %r", text)
            return text
        except Exception as exc:
            logger.error("Transcription error: %s", exc, exc_info=True)
            return ""
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
