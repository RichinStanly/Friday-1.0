from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QTextEdit

from friday.app import FridayApp
from friday.chat import ChatEngine
from friday.tools import ToolResult
from friday.voice_ui import FridayVoiceExperience


APP = QApplication.instance() or QApplication([])


class _Tools:
    def search_web(self, query):
        return ToolResult("Web", query, True)

    def search_images(self, query):
        return ToolResult("Image Search", query, True, ("C:/example.png",))


class ToolRoutingTests(unittest.TestCase):
    def setUp(self):
        self.chat = ChatEngine(store=None, provider=None, tools=_Tools())

    def test_image_search_beats_force_web(self):
        result = self.chat._maybe_local_context("find pictures of Saturn", force_web=True)
        self.assertEqual(result.source, "Image Search")
        self.assertEqual(result.artifacts, ("C:/example.png",))

    def test_normal_chat_streams_tokens_and_completes(self):
        class Store:
            def __init__(self):
                self.saved = []

            def save_message(self, *args):
                self.saved.append(args)

            def get_conversation(self, _cid):
                return type("Conversation", (), {"summary": "", "title": "Existing", "memory_enabled": True})()

            def setting(self, _key, default=""):
                return default

            def relevant_memories(self, _prompt):
                return []

            def messages(self, _cid, limit=None):
                return []

            def rename_conversation(self, *_args):
                raise AssertionError("existing conversation should not be renamed")

        class Provider:
            def stream_chat(self, _model, _context, on_token, _cancelled):
                on_token("Hello")
                on_token(" Boss")

        store = Store()
        chat = ChatEngine(store, Provider(), _Tools())
        events = []
        chat.respond("c1", "model", "hello", [], [], lambda kind, value: events.append((kind, value)), threading.Event())
        self.assertEqual(events[-1], ("done", ""))
        self.assertEqual("".join(value for kind, value in events if kind == "token"), "Hello Boss")


class VoiceStateTests(unittest.TestCase):
    def test_finish_cycle_restores_microphone_and_listening(self):
        class Recorder:
            ignore_mic = True

        app = FridayApp.__new__(FridayApp)
        app._voice_lock = threading.RLock()
        app._voice_session = 4
        app._voice_processing = True
        app.voice_ui_window = object()
        app.voice_recorder = Recorder()
        app.cancel_event = threading.Event()
        app.cancel_event.set()
        events = []
        app._voice_emit_signal = lambda kind, value="": events.append((kind, value))
        app._finish_voice_cycle(4)
        self.assertFalse(app._voice_processing)
        self.assertFalse(app.voice_recorder.ignore_mic)
        self.assertEqual(events, [("state", "LISTENING")])

    def test_voice_typing_appends_without_destroying_existing_text(self):
        app = FridayApp.__new__(FridayApp)
        app._voice_typing_session = 3
        app.input = QTextEdit()
        app.input.setPlainText("Keep this")
        FridayApp._append_voice_typing(app, 3, "and add this")
        self.assertEqual(app.input.toPlainText(), "Keep this and add this")

    def test_five_voice_cycles_keep_microphone_muted_until_tts_completes(self):
        class Recorder:
            ignore_mic = False

        class Transcriber:
            def transcribe(self, _wav):
                return "status report"

        class Speaker:
            def __init__(self):
                self.callbacks = []

            def speak(self, _text, on_stop):
                self.callbacks.append(on_stop)

        class Chat:
            def respond(self, _cid, _model, _text, _attachments, _models, emit, _cancel, force_web=False):
                emit("token", "All systems nominal.")
                emit("done", "")

        class Picker:
            def currentText(self):
                return "test-model"
            def currentData(self):
                return "test-model"

        app = FridayApp.__new__(FridayApp)
        app._voice_lock = threading.RLock()
        app._voice_session = 1
        app._voice_processing = True
        app.voice_ui_window = object()
        app.voice_recorder = Recorder()
        app.voice_transcriber = Transcriber()
        app.voice_speaker = Speaker()
        app.chat = Chat()
        app.active_conversation = type("Conversation", (), {"id": "voice"})()
        app.model_picker = Picker()
        app.models = []
        app.web_enabled = False
        app.cancel_event = threading.Event()
        app._voice_emit_signal = lambda *_args: None

        for _ in range(5):
            app._voice_processing = True
            app._transcribe_and_respond(b"audio", 1)
            self.assertTrue(app.voice_recorder.ignore_mic)
            callback = app.voice_speaker.callbacks.pop(0)
            callback()
            self.assertFalse(app._voice_processing)
            self.assertFalse(app.voice_recorder.ignore_mic)


class VoiceImageTests(unittest.TestCase):
    def test_voice_hud_loads_a_local_image_asynchronously(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "result.png"
            image = QImage(20, 20, QImage.Format.Format_RGB32)
            image.fill(0x00E5FF)
            self.assertTrue(image.save(str(image_path)))
            ui = FridayVoiceExperience()
            ui.set_images([str(image_path), str(Path(directory) / "missing.png")])
            ui._image_worker.wait(3000)
            APP.processEvents()
            self.assertGreaterEqual(ui.image_layout.count(), 1)
            ui.deleteLater()


if __name__ == "__main__":
    unittest.main()
