from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal, QPoint
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QAbstractScrollArea, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QInputDialog,
    QPushButton, QScrollArea, QSizePolicy, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
    QMenu
)

from friday.chat import ChatEngine
from friday.config import AppPaths
from friday.providers import OllamaLauncher, OllamaProvider
from friday.storage import LocalStore
from friday.tool_manager import ToolManager

logger = logging.getLogger(__name__)

from friday.theme import Theme

class _Bridge(QObject):
    event = Signal(str, str)
    conv_event = Signal(str, str, str)
    voice_event = Signal(str, str)
    voice_typing_done = Signal(int, str)
    voice_typing_placeholder = Signal(str)
    permission_request = Signal(object)


class ChatInput(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.send_callback = None
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if self.send_callback: self.send_callback()
            return
        super().keyPressEvent(event)

class TitleBar(QWidget):
    def __init__(self, parent, theme, app_instance):
        super().__init__(parent)
        self.parent = parent
        self.theme = theme
        self.app = app_instance
        self.setObjectName("mainTitleBar")
        self.setStyleSheet(f"#mainTitleBar {{ background-color: {self.theme.PANEL}; border-bottom: 1px solid {self.theme.BORDER}; }}")

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(12, 0, 0, 0)
        self.layout.setSpacing(4)

        from friday.ui_components import IconButton
        self.logo = IconButton("brain", self.theme, size=24, icon_size=16)
        self.layout.addWidget(self.logo)

        from PySide6.QtWidgets import QMenuBar, QMenu
        self.menu_bar = QMenuBar()
        self.menu_bar.setStyleSheet(f"""
            QMenuBar {{ background: transparent; color: {self.theme.TEXT}; font-size: 13px; }}
            QMenuBar::item {{ padding: 6px 12px; background: transparent; border-radius: 4px; }}
            QMenuBar::item:selected {{ background: {self.theme.HOVER}; }}
            QMenu {{ background: {self.theme.BG}; border: 1px solid {self.theme.BORDER}; }}
            QMenu::item {{ padding: 6px 24px; color: {self.theme.TEXT}; }}
            QMenu::item:selected {{ background: {self.theme.HOVER}; }}
        """)

        file_menu = self.menu_bar.addMenu("File")
        file_menu.addAction("New Chat").triggered.connect(self.app.new_chat)
        file_menu.addAction("Open Attachment").triggered.connect(self.app.add_attachment)
        file_menu.addSeparator()
        file_menu.addAction("Exit").triggered.connect(self.parent.close)

        edit_menu = self.menu_bar.addMenu("Edit")
        edit_menu.addAction("Undo")
        edit_menu.addAction("Redo")
        edit_menu.addSeparator()
        edit_menu.addAction("Cut")
        edit_menu.addAction("Copy")
        edit_menu.addAction("Paste")

        view_menu = self.menu_bar.addMenu("View")
        view_menu.addAction("Toggle Sidebar").triggered.connect(self.app._toggle_sidebar)
        view_menu.addAction("Toggle Web Tools").triggered.connect(self.app._set_web)

        chat_menu = self.menu_bar.addMenu("Chat")
        chat_menu.addAction("Clear Current Chat").triggered.connect(self.app.clear_chat)
        chat_menu.addAction("Regenerate Last Response").triggered.connect(self.app.regenerate)

        tools_menu = self.menu_bar.addMenu("Tools")
        tools_menu.addAction("Control Center").triggered.connect(self.app.open_settings)
        tools_menu.addAction("Voice Mode").triggered.connect(self.app._toggle_voice)

        window_menu = self.menu_bar.addMenu("Window")
        window_menu.addAction("Minimize").triggered.connect(self.parent.showMinimized)
        window_menu.addAction("Maximize").triggered.connect(self.toggle_maximize)

        self.layout.addWidget(self.menu_bar)

        self.layout.addStretch(1)

        from PySide6.QtGui import QCursor
        btn_style = f"QPushButton {{ background: transparent; border: none; padding: 4px; }} QPushButton:hover {{ background: {self.theme.HOVER}; }}"
        close_style = f"QPushButton {{ background: transparent; border: none; padding: 4px; }} QPushButton:hover {{ background: {self.theme.DANGER}; color: white; }}"

        self.min_btn = IconButton("minus", self.theme, size=32, icon_size=16)
        self.min_btn.setStyleSheet(btn_style)
        self.min_btn.clicked.connect(self.parent.showMinimized)
        self.layout.addWidget(self.min_btn)

        self.max_btn = IconButton("maximize", self.theme, size=32, icon_size=16)
        self.max_btn.setStyleSheet(btn_style)
        self.max_btn.clicked.connect(self.toggle_maximize)
        self.layout.addWidget(self.max_btn)

        self.close_btn = IconButton("x", self.theme, size=32, icon_size=16)
        self.close_btn.setStyleSheet(close_style)
        self.close_btn.clicked.connect(self.parent.close)
        self.layout.addWidget(self.close_btn)

        self.start = QPoint(0, 0)
        self.pressing = False

    def toggle_maximize(self):
        if self.parent.isMaximized():
            self.parent.showNormal()
        else:
            self.parent.showMaximized()

    def mousePressEvent(self, event):
        from PySide6.QtCore import Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = event.globalPosition().toPoint()
            self.pressing = True

    def mouseDoubleClickEvent(self, event):
        self.toggle_maximize()

    def mouseMoveEvent(self, event):
        if self.pressing:
            if self.parent.isMaximized():
                self.parent.showNormal()
            end = event.globalPosition().toPoint()
            self.parent.move(self.parent.pos() + end - self.start)
            self.start = end

    def mouseReleaseEvent(self, event):
        self.pressing = False

class FridayApp:
    def __init__(self) -> None:
        paths = AppPaths(); paths.ensure()
        self.store = LocalStore(paths.database)
        self.provider = OllamaProvider()
        self.launcher = OllamaLauncher(self.provider)
        self.web_enabled = bool(self.store.setting("web_enabled", False))
        self.is_light_mode = bool(self.store.setting("light_mode", False))
        self.theme = Theme(self.is_light_mode)
        self.tools = ToolManager(self.web_enabled, store=self.store)
        self.chat = ChatEngine(self.store, self.provider, self.tools)
        self._apply_routing_to_chat()
        self.models = []
        self.attachments: list[tuple[str, str]] = []
        self.active_conversation = None
        self.live_view: QTextBrowser | None = None
        self.bridge = _Bridge()
        self.bridge.event.connect(self._handle_event)
        self.bridge.conv_event.connect(self._handle_conv_event)
        self.bridge.voice_event.connect(self._handle_voice_event)
        self.cancel_event = threading.Event()  # legacy compat — keep for voice
        # Per-conversation request isolation
        # _conv_jobs[conv_id] = {"cancel": threading.Event, "live_view": view, "live_activity": widget}
        self._conv_jobs: dict = {}
        self._voice_lock = threading.RLock()


        self.permission_event = threading.Event()
        self.permission_result = False
        from friday.permission_manager import engine as perm_engine
        perm_engine.ui_confirm_callback = self._handle_permission_request_threadsafe
        self.bridge.permission_request.connect(self._show_permission_dialog)
        self._voice_session = 0
        self._voice_processing = False
        self._voice_cancel_event: threading.Event | None = None
        self._voice_typing_session = 0
        self.qt = QApplication.instance() or QApplication([])

        self.window = QMainWindow(); self.window.setWindowTitle("Friday")
        self.window.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.window.resize(1320, 820); self.window.setMinimumSize(960, 640)

        self._build()
        self.bridge.voice_typing_done.connect(self._append_voice_typing)
        self.bridge.voice_typing_placeholder.connect(self.input.setPlaceholderText)
        self.apply_theme()

        self.new_chat(); self._auto_start_and_refresh()

        self.voice_ui_window = None
        original_key_press = self.window.keyPressEvent
        def hooked_key_press(event):
            if event.key() == Qt.Key.Key_V:
                self._toggle_voice()
            elif event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
                self._instant_interrupt()
            original_key_press(event)
        self.window.keyPressEvent = hooked_key_press

    def _handle_voice_event(self, kind: str, value: str) -> None:
        """All voice UI updates come here on the Qt main thread (via Signal)."""
        ui = getattr(self, 'voice_ui_window', None)
        if not ui:
            return
        if kind == "state":
            ui.set_state(value)
        elif kind == "user_query":
            ui.set_user_query(value)
        elif kind == "transcript":
            ui.set_transcript(value)
        elif kind == "tool":
            ui.set_tool_activity(value)
        elif kind == "images":
            try:
                ui.set_images(json.loads(value))
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.exception("Voice image event contained invalid data")
        elif kind == "amplitude":
            try:
                ui.set_amplitude(float(value))
            except (ValueError, TypeError):
                pass

    def _voice_emit_signal(self, kind: str, value: str = ""):
        """Thread-safe way to update voice UI from any thread."""
        self.bridge.voice_event.emit(kind, value)

    def _toggle_voice(self):
        if getattr(self, 'voice_ui_window', None):
            self._close_voice()
            return

        from friday.voice_ui import FridayVoiceExperience
        from friday.voice import ContinuousRecorder, VoiceTranscriber
        from friday.tts import VoiceSpeaker

        with self._voice_lock:
            self._voice_session += 1
            session = self._voice_session
            self._voice_processing = False
        from friday.config import AppPaths
        self.voice_ui_window = FridayVoiceExperience()
        self.voice_transcriber = VoiceTranscriber()
        self.voice_speaker = VoiceSpeaker(AppPaths().data_dir)
        self.cancel_event.clear()

        self.voice_speaker.on_amplitude = lambda amp: self._voice_emit_signal("amplitude", str(amp))

        def _on_speech_start():
            if session != self._voice_session or getattr(self, '_voice_processing', False):
                return
            self.cancel_event.set()
            with self._voice_lock:
                self._voice_response_id = getattr(self, '_voice_response_id', 0) + 1
                self._voice_processing = False
            if getattr(self, 'voice_speaker', None):
                self.voice_speaker.stop()
            if getattr(self, 'voice_recorder', None):
                self.voice_recorder.ignore_mic = False
            self._voice_emit_signal("state", "LISTENING")

        def _on_speech_end(wav_bytes):
            if not wav_bytes:
                self._voice_emit_signal("state", "LISTENING")
                return
            with self._voice_lock:
                if session != self._voice_session or self._voice_processing:
                    return
                self._voice_processing = True
            self._voice_emit_signal("state", "PROCESSING")
            threading.Thread(target=lambda: self._transcribe_and_respond(wav_bytes, session), daemon=True).start()

        from friday.voice import ContinuousRecorder
        self.voice_recorder = ContinuousRecorder(
            on_speech_start=_on_speech_start,
            on_speech_end=_on_speech_end,
            on_amplitude=lambda amp: self._voice_emit_signal("amplitude", str(amp))
        )

        self.voice_ui_window.on_exit = self._close_voice
        self.voice_ui_window.showFullScreen()

        try:
            self.voice_recorder.start()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Microphone failed to start")
            self._voice_emit_signal("transcript", f"Microphone error: {exc}")
            self._voice_emit_signal("state", "ERROR")
            return

        def _after():
            if session != getattr(self, '_voice_session', -1): return
            self._voice_emit_signal("state", "LISTENING")
        if getattr(self, 'voice_speaker', None):
            self.voice_speaker.speak("Online and ready, Boss.", on_stop=_after)

    def _is_hallucination(self, text: str) -> bool:
        """Check if the transcribed text is a Whisper hallucination."""
        text = text.lower().strip().strip('.!?*')
        hallucinations = ["thank you", "you", "thanks", "thank you very much", "subtitles by amara.org community", ""]
        return text in hallucinations

    def _transcribe_and_respond(self, wav_bytes, session: int):
        with self._voice_lock:
            if session != self._voice_session:
                return
            self._voice_response_id = getattr(self, '_voice_response_id', 0) + 1
            current_response_id = self._voice_response_id
        import threading
        tts_handoff = threading.Event()
        if getattr(self, 'voice_recorder', None):
            self.voice_recorder.ignore_mic = True

        try:
            text = self.voice_transcriber.transcribe(wav_bytes)

            if not text or self._is_hallucination(text):
                self._voice_emit_signal("state", "LISTENING")
                return

            self._voice_emit_signal("user_query", text)

            cleaned = text.lower().strip().strip('.!?')
            if cleaned in ("stop", "stop it", "stop friday", "shut up", "cancel"):
                self._instant_interrupt()
                return

            self._voice_emit_signal("state", "PROCESSING")

            self.cancel_event.clear()
            full_response = []

            def _voice_emit(kind, value):
                if kind == "token":
                    full_response.append(value)
                elif kind == "tool_start":
                    self._voice_emit_signal("tool", value)
                elif kind == "images":
                    self._voice_emit_signal("images", value)
                elif kind == "error":
                    self._voice_emit_signal("transcript", "Error: " + value)
                    self._voice_emit_signal("state", "LISTENING")
                elif kind == "done":
                    content = "".join(full_response)
                    self._voice_emit_signal("transcript", content)
                    self._voice_emit_signal("state", "SPEAKING")
                    import re
                    spoken = re.sub(r'http\S+', '', content)
                    spoken = re.sub(r'[\*\#\`\>\_]', '', spoken).strip()

                    if getattr(self, 'voice_speaker', None) and spoken:
                        tts_handoff.set()
                        with self._voice_lock:
                            self._voice_processing = False
                        if getattr(self, 'voice_recorder', None):
                            self.voice_recorder.allow_barge_in = True
                        self.voice_speaker.speak(spoken, on_stop=lambda: self._finish_voice_cycle(session, current_response_id))
                    else:
                        self._finish_voice_cycle(session, current_response_id)

            cid = self.active_conversation.id if self.active_conversation else "voice_session"
            self.chat.respond(cid, self._get_selected_model(), text, [], self.models[:], _voice_emit, self.cancel_event, force_web=self.web_enabled)

        except Exception as e:
            self._voice_emit_signal("transcript", f"Error: {e}")
            import logging
            logging.getLogger(__name__).exception("Exclusive voice response failed")
        finally:
            if not tts_handoff.is_set():
                self._finish_voice_cycle(session, current_response_id)


    def _instant_interrupt(self):
        self.cancel_event.set()
        if getattr(self, 'voice_speaker', None):
            self.voice_speaker.stop()
        with self._voice_lock:
            session = self._voice_session
            self._voice_response_id = getattr(self, '_voice_response_id', 0) + 1
            current_response_id = self._voice_response_id
        self._finish_voice_cycle(session, current_response_id)

    def _finish_voice_cycle(self, session: int, response_id: int = -1) -> None:
        """Restore a live exclusive-voice session to listening exactly once."""
        with self._voice_lock:
            if session != self._voice_session:
                return
            if response_id != -1 and response_id != getattr(self, '_voice_response_id', -1):
                return
            self._voice_processing = False
        if getattr(self, 'voice_recorder', None):
            self.voice_recorder.ignore_mic = False
        self._voice_emit_signal("state", "LISTENING")

    def _close_voice(self):
        with self._voice_lock:
            self._voice_session += 1
            self._voice_processing = False
        if getattr(self, 'voice_recorder', None):
            self.voice_recorder.stop()
            self.voice_recorder = None
        if getattr(self, 'voice_speaker', None):
            self.voice_speaker.stop()
            self.voice_speaker = None
        if getattr(self, 'voice_ui_window', None):
            self.voice_ui_window.hide()
            self.voice_ui_window.close()
            self.voice_ui_window = None

    def _toggle_voice_typing(self):
        if getattr(self, 'voice_typing_recorder', None):
            self.voice_typing_recorder.stop()
            self.voice_typing_recorder = None
            self._voice_typing_session += 1
            self.input.setPlaceholderText("Message Friday...")
            self.voice_btn.setStyleSheet("")
            return

        self.input.setPlaceholderText("🎙 Listening...")
        self._voice_typing_session += 1
        session = self._voice_typing_session
        self.voice_btn.setStyleSheet("background: #ef4444; color: white;")

        def _on_speech_end(wav_bytes):
            if session != self._voice_typing_session:
                return
            if not wav_bytes:
                self.bridge.voice_typing_placeholder.emit("🎙 Listening...")
                return
            self.bridge.voice_typing_placeholder.emit("⚙ Transcribing...")

            def _work():
                if not getattr(self, 'voice_transcriber', None):
                    from friday.voice import VoiceTranscriber
                    self.voice_transcriber = VoiceTranscriber()
                text = self.voice_transcriber.transcribe(wav_bytes)
                if text:
                    self.bridge.voice_typing_done.emit(session, text)
                self.bridge.voice_typing_placeholder.emit("🎙 Listening...")

            threading.Thread(target=_work, daemon=True).start()

        from friday.voice import ContinuousRecorder
        self.voice_typing_recorder = ContinuousRecorder(
            on_speech_start=lambda: None,
            on_speech_end=_on_speech_end,
            on_amplitude=lambda a: None
        )
        try:
            self.voice_typing_recorder.start()
        except Exception as exc:
            logger.exception("Normal chat microphone failed to start")
            self.voice_typing_recorder = None
            self.voice_btn.setStyleSheet("")
            self.input.setPlaceholderText("Microphone unavailable")
            QMessageBox.warning(self.window, "Friday microphone", f"Could not start voice typing: {exc}")

    def _append_voice_typing(self, session: int, text: str) -> None:
        """Append an STT result on the Qt thread without replacing user edits."""
        if session != self._voice_typing_session:
            return
        cursor = self.input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.input.toPlainText().strip():
            cursor.insertText(" ")
        cursor.insertText(text)
        self.input.setTextCursor(cursor)

    def apply_theme(self):
        self.theme = Theme(self.is_light_mode)
        self.qt.setStyleSheet(self._stylesheet())
        self.render_messages()

    def _stylesheet(self) -> str:
                t = self.theme
                return f"""
        QWidget {{ background: {t.BG}; color: {t.TEXT}; font-family: 'Segoe UI', -apple-system, sans-serif; font-size: 14.5px; }}
        QMainWindow {{ background: {t.BG}; }}
        QLineEdit, QComboBox {{ background: {t.PANEL}; border: 1px solid {t.BORDER}; border-radius: 8px; padding: 8px 12px; color: {t.TEXT}; }}
        QLineEdit:focus, QComboBox:focus {{ border: 1px solid {t.MUTED}; }}
        QPushButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; color: {t.TEXT}; padding: 6px 10px; }}
        QPushButton:hover {{ background: {t.HOVER}; }}
        QPushButton:disabled {{ color: {t.MUTED}; }}
        QComboBox::drop-down {{ border: 0; width: 28px; }}
        QComboBox QAbstractItemView {{ background: {t.PANEL}; color: {t.TEXT}; border: 1px solid {t.BORDER}; selection-background-color: {t.HOVER}; padding: 5px; }}
        QListWidget {{ border: 0; background: {t.SIDEBAR}; color: {t.MUTED}; outline: 0; padding: 6px 0; }}
        QListWidget::item {{ padding: 10px 12px; margin: 2px 8px; border-radius: 8px; }}
        QListWidget::item:hover {{ background: {t.HOVER}; color: {t.TEXT}; }}
        QListWidget::item:selected {{ background: {t.SELECTED}; color: {t.TEXT}; }}

        QScrollArea {{ background: {t.BG}; border: 0; }}
        QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {t.BORDER}; border-radius: 3px; min-height: 20px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; background: transparent; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

        QCheckBox {{ spacing: 8px; color: {t.TEXT}; }}
        QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {t.BORDER}; border-radius: 4px; background: {t.PANEL}; }}
        QCheckBox::indicator:checked {{ background: {t.TEXT}; border-color: {t.TEXT}; }}
        QDialog {{ background: {t.BG}; }}

        #settingsTitle {{ font-size: 20px; font-weight: 600; color: {t.TEXT}; margin-bottom: 12px; }}
        #settingsFrame {{ background: {t.PANEL}; border: 1px solid {t.BORDER}; border-radius: 12px; padding: 12px; }}
        #settingsCloseBtn {{ font-size: 16px; font-weight: bold; color: {t.MUTED}; border-radius: 15px; }}
        #settingsCloseBtn:hover {{ background: #ef4444; color: white; }}

        #titleBar {{ background: {t.SIDEBAR}; }}
        #closeBtn {{ font-size: 14px; color: {t.MUTED}; border-radius: 15px; }}
        #closeBtn:hover {{ background: #ef4444; color: white; }}
        #sidebar {{ background: {t.SIDEBAR}; }}
        #brand {{ font-size: 16px; font-weight: 600; color: {t.TEXT}; padding: 10px 14px 4px 14px; }}
        #newChatBtn {{ background: transparent; border: 0; color: {t.TEXT}; text-align: left; padding: 10px 14px; font-weight: 500; font-size: 14px; }}
        #newChatBtn:hover {{ background: {t.HOVER}; border-radius: 8px; }}
        #sectionLbl {{ color: {t.MUTED}; font-size: 11px; font-weight: 600; padding: 16px 14px 4px 14px; }}
        #settingsBtn {{ background: transparent; text-align: left; padding: 10px 14px; font-weight: 500; border-radius: 8px; }}
        #settingsBtn:hover {{ background: {t.HOVER}; }}
        #messageHost {{ background: {t.BG}; }}

        #composer {{ background: {t.PANEL}; border-radius: 24px; padding: 4px; }}
        #attachBtn {{ font-size: 20px; font-weight: 400; color: {t.TEXT}; border-radius: 16px; padding: 0; }}
        #attachBtn:hover {{ background: {t.BORDER}; }}
        #composerInput {{ background: transparent; border: 0; color: {t.TEXT}; padding: 6px 8px; font-size: 15px; }}
        #stopBtn {{ color: {t.MUTED}; border: 1px solid {t.BORDER}; border-radius: 16px; padding: 0; }}
        #stopBtn:hover {{ background: {t.BORDER}; }}
        #sendBtn {{ background: {t.TEXT}; color: {t.BG}; font-size: 16px; font-weight: bold; border-radius: 16px; padding: 0; }}
        #sendBtn:hover {{ opacity: 0.8; }}
        #voiceBtn {{ background: transparent; color: {t.TEXT}; font-size: 20px; border-radius: 16px; padding: 0; }}
        #voiceBtn:hover {{ background: {t.BORDER}; }}
        #globeBtn {{ background: transparent; color: {t.MUTED}; font-size: 20px; border-radius: 16px; padding: 0; }}
        #globeBtn:hover {{ background: {t.BORDER}; }}
        #globeBtn:checked {{ color: #3b82f6; background: {t.BORDER}; }}

        #userCard {{ background: {t.USER}; border-radius: 20px; padding: 10px 16px; }}
        #botCard {{ background: transparent; }}
        #botLabel {{ color: {t.TEXT}; font-weight: 700; font-size: 15px; margin-bottom: 4px; }}
        #msgView {{ background: transparent; color: {t.TEXT}; border: 0; font-size: 15.5px; padding: 0; line-height: 1.6; }}
        #msgCopy {{ color: {t.MUTED}; padding: 4px 8px; font-size: 12px; }}
        #msgCopy:hover {{ color: {t.TEXT}; background: {t.PANEL}; }}
        #footerLbl {{ color: {t.MUTED}; font-size: 11px; padding: 8px; }}
        """

    def _confirm(self, text: str) -> bool:
        msg = QMessageBox(self.window)
        msg.setText(text)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def button(self, text: str, callback, accent: bool = False) -> QPushButton:
        button = QPushButton(text); button.clicked.connect(callback)
        if accent:
            button.setStyleSheet(f"QPushButton {{ background: {self.theme.TEXT}; color: {self.theme.BG}; font-weight: 600; border: 0; }}")
        return button

    def _build(self) -> None:
        from friday.ui_components import IconButton, Avatar, SuggestionCard, AttachmentChip
        shell = QWidget(); self.window.setCentralWidget(shell)
        layout = QVBoxLayout(shell); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        self.title_bar = TitleBar(self.window, self.theme, self)
        self.title_bar.setObjectName("titleBar")
        layout.addWidget(self.title_bar)

        main_layout = QHBoxLayout(); main_layout.setContentsMargins(0,0,0,0); main_layout.setSpacing(0)
        layout.addLayout(main_layout, 1)

        self.sidebar = QFrame(); self.sidebar.setObjectName("sidebar"); self.sidebar.setFixedWidth(260)
        side = QVBoxLayout(self.sidebar); side.setContentsMargins(12, 12, 12, 12); side.setSpacing(8)

        top_side = QHBoxLayout(); top_side.setContentsMargins(4, 0, 4, 8)
        brand = QLabel("FRIDAY"); brand.setStyleSheet(f"font-size: 16px; font-weight: bold; background: transparent; border: none; color: {self.theme.TEXT}; letter-spacing: 1px;")
        top_side.addWidget(brand)
        top_side.addStretch(1)

        self.new_chat_btn = IconButton("plus", self.theme, size=32, icon_size=16)
        self.new_chat_btn.setToolTip("New Chat")
        self.new_chat_btn.clicked.connect(self.new_chat)
        top_side.addWidget(self.new_chat_btn)
        side.addLayout(top_side)

        section = QLabel("Recents"); section.setObjectName("sectionLbl"); section.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 12px; font-weight: bold; padding-left: 4px;")
        side.addWidget(section)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search conversations")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.textChanged.connect(self.load_history)
        side.addWidget(self.history_search)

        self.history = QListWidget(); self.history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history.customContextMenuRequested.connect(self._show_history_context_menu)
        self.history.itemActivated.connect(self._open_history_item); side.addWidget(self.history, 1)
        self.show_archived_btn = QPushButton("Show archived")
        self.show_archived_btn.setCheckable(True)
        self.show_archived_btn.toggled.connect(self._toggle_archived_history)
        side.addWidget(self.show_archived_btn)

        footer = QVBoxLayout(); footer.setContentsMargins(0, 8, 0, 12); footer.setSpacing(4)

        voice_row = QHBoxLayout(); voice_row.setContentsMargins(8, 8, 8, 8); voice_row.setSpacing(12)
        voice_icon = IconButton("mic", self.theme, size=24, icon_size=16); voice_icon.setEnabled(False)
        voice_lbl = QLabel("Voice Mode"); voice_lbl.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: 500; background: transparent;")
        voice_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        voice_btn_wrap = QPushButton(); voice_btn_wrap.setLayout(voice_row); voice_btn_wrap.clicked.connect(self._toggle_voice)
        voice_btn_wrap.setCursor(Qt.CursorShape.PointingHandCursor)
        voice_btn_wrap.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-radius: 8px; text-align: left; }} QPushButton:hover {{ background: {self.theme.HOVER}; }}")
        voice_row.addWidget(voice_icon); voice_row.addWidget(voice_lbl); voice_row.addStretch(1)
        footer.addWidget(voice_btn_wrap)

        cc_row = QHBoxLayout(); cc_row.setContentsMargins(8, 8, 8, 8); cc_row.setSpacing(12)
        cc_icon = IconButton("settings", self.theme, size=24, icon_size=16); cc_icon.setEnabled(False)
        cc_lbl = QLabel("Control Center"); cc_lbl.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: 500; background: transparent;")
        cc_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        cc_btn_wrap = QPushButton(); cc_btn_wrap.setLayout(cc_row); cc_btn_wrap.clicked.connect(self.open_settings)
        cc_btn_wrap.setCursor(Qt.CursorShape.PointingHandCursor)
        cc_btn_wrap.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-radius: 8px; text-align: left; }} QPushButton:hover {{ background: {self.theme.HOVER}; }}")
        cc_row.addWidget(cc_icon); cc_row.addWidget(cc_lbl); cc_row.addStretch(1)
        footer.addWidget(cc_btn_wrap)

        profile_row = QHBoxLayout(); profile_row.setContentsMargins(8, 8, 12, 8); profile_row.setSpacing(12)
        self.profile_btn = QPushButton()
        self.profile_btn.setFixedHeight(52)
        self.profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_btn.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-radius: 8px; }} QPushButton:hover {{ background: {self.theme.HOVER}; }}")
        self.profile_btn.setLayout(profile_row)
        self.profile_btn.clicked.connect(self._show_profile_menu)

        name = self.store.setting("profile_name", "Boss")
        pic = self.store.setting("profile_pic", "")
        self.user_avatar = Avatar(name, self.theme, size=36, pic_path=pic)
        self.user_avatar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.user_name_lbl = QLabel(name)
        self.user_name_lbl.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: 600; font-size: 14px; background: transparent;")
        self.user_name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        chevron_lbl = QLabel("⋯")
        chevron_lbl.setStyleSheet(f"color: {self.theme.MUTED}; font-weight: bold; font-size: 16px; background: transparent;")
        chevron_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        profile_row.addWidget(self.user_avatar)
        profile_row.addWidget(self.user_name_lbl)
        profile_row.addStretch(1)
        profile_row.addWidget(chevron_lbl)

        footer.addWidget(self.profile_btn)

        side.addLayout(footer)
        main_layout.addWidget(self.sidebar)

        main = QWidget(); content = QVBoxLayout(main); content.setContentsMargins(0, 0, 0, 0); content.setSpacing(0)

        top_bar_container = QWidget(); top_bar_container.setObjectName("topBar")
        top_bar_container.setStyleSheet(f"#topBar {{ background-color: {self.theme.BG}; border-bottom: 1px solid {self.theme.BORDER}; }}")
        top_bar = QHBoxLayout(top_bar_container); top_bar.setContentsMargins(16, 10, 16, 10); top_bar.setSpacing(12)

        self.sidebar_toggle = IconButton("menu", self.theme, size=32, icon_size=18)
        self.sidebar_toggle.clicked.connect(self._toggle_sidebar)
        top_bar.addWidget(self.sidebar_toggle)

        self.context_title = QLabel("FRIDAY"); self.context_title.setStyleSheet(f"font-weight: bold; color: {self.theme.TEXT}; font-size: 14px;")
        top_bar.addWidget(self.context_title)
        top_bar.addStretch(1)

        self.model_picker = QComboBox(); self.model_picker.addItem("FRIDAY Auto")
        self.model_picker.setFixedWidth(160)
        self.model_picker.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_picker.currentIndexChanged.connect(self._set_active_conversation_model)
        top_bar.addWidget(self.model_picker)

        top_bar.addStretch(1)

        from friday.ui_components import IconTextButton
        self.web_status_btn = IconTextButton("Web ON" if self.web_enabled else "Web OFF", "globe", self.theme, primary=self.web_enabled)
        self.web_status_btn.setToolTip("Web tools enabled" if self.web_enabled else "Web tools disabled")
        self.web_status_btn.clicked.connect(self._toggle_web_header)
        top_bar.addWidget(self.web_status_btn)

        self.incognito_btn = QPushButton("Incognito"); self.incognito_btn.setObjectName("incognitoBtn")
        self.incognito_btn.setCheckable(True); self.incognito_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.incognito_btn.setStyleSheet(f"QPushButton {{ background: transparent; color: {self.theme.MUTED}; border: 1px solid {self.theme.BORDER}; border-radius: 6px; padding: 6px 12px; font-weight: bold; }} QPushButton:checked {{ background: {self.theme.DANGER}; color: white; border-color: {self.theme.DANGER}; }}")
        self.incognito_btn.setToolTip("Temporary search context. Results are not saved to long-term memory.")
        self.incognito_btn.toggled.connect(self._set_active_conversation_incognito)
        top_bar.addWidget(self.incognito_btn)

        self.clear_btn = IconButton("trash", self.theme, size=32, icon_size=16)
        self.clear_btn.setToolTip("Clear Chat")
        self.clear_btn.clicked.connect(self.clear_chat)
        top_bar.addWidget(self.clear_btn)

        content.addWidget(top_bar_container)

        # Keep this row deliberately small: Model/Web/Incognito are the header
        # controls for the active conversation. Memory remains visible in Details.
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(16, 3, 16, 3)
        controls_layout.setSpacing(10)
        conversation_label = QLabel("Conversation")
        conversation_label.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 12px;")
        controls_layout.addWidget(conversation_label)
        controls_layout.addStretch(1)
        self.context_details_btn = QPushButton("Details")
        self.context_details_btn.setToolTip("Show safe context details for this conversation")
        self.context_details_btn.clicked.connect(self._open_context_inspector)
        controls_layout.addWidget(self.context_details_btn)
        content.addWidget(controls)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.message_host = QWidget(); self.message_host.setObjectName("messageHost")
        self.message_layout = QVBoxLayout(self.message_host); self.message_layout.setContentsMargins(40, 20, 40, 40); self.message_layout.setAlignment(Qt.AlignmentFlag.AlignTop); self.message_layout.setSpacing(32)
        self.scroll.setWidget(self.message_host); content.addWidget(self.scroll, 1)

        composer_wrapper = QHBoxLayout(); composer_wrapper.setContentsMargins(20, 10, 20, 10)
        composer_wrapper.addStretch(1)

        composer_container = QVBoxLayout(); composer_container.setSpacing(4)

        self.attachment_container = QWidget()
        self.attachment_layout = QHBoxLayout(self.attachment_container)
        self.attachment_layout.setContentsMargins(12, 0, 12, 0)
        self.attachment_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.attachment_container.hide()
        composer_container.addWidget(self.attachment_container)

        composer = QFrame(); composer.setObjectName("composer"); composer.setFixedWidth(750)
        compose = QHBoxLayout(composer); compose.setContentsMargins(12, 12, 12, 12); compose.setSpacing(8)

        self.attach_button = IconButton("paperclip", self.theme, size=32, icon_size=18)
        self.attach_button.clicked.connect(self.add_attachment)
        compose.addWidget(self.attach_button)

        self.web_btn = IconButton("globe", self.theme, size=32, icon_size=18)
        self.web_btn.setCheckable(True); self.web_btn.setChecked(self.web_enabled)
        self.web_btn.clicked.connect(self._set_web)
        if self.web_enabled: self.web_btn.update_icon(self.theme.ACCENT)
        compose.addWidget(self.web_btn)

        self.input = ChatInput(); self.input.send_callback = self.send; self.input.setObjectName("composerInput")
        self.input.setPlaceholderText("Message FRIDAY...")
        self.input.setFixedHeight(38)
        compose.addWidget(self.input, 1)

        self.voice_btn = IconButton("mic", self.theme, size=32, icon_size=18)
        self.voice_btn.clicked.connect(self._toggle_voice_typing)
        compose.addWidget(self.voice_btn)

        self.stop_button = IconButton("stop", self.theme, size=32, icon_size=18)
        self.stop_button.clicked.connect(self.stop); self.stop_button.hide(); self.stop_button.setEnabled(False); self.stop_button.setEnabled(False)
        compose.addWidget(self.stop_button)

        self.send_btn = IconButton("send", self.theme, size=32, icon_size=18)
        self.send_btn.clicked.connect(self.send); self.send_btn.setObjectName("primaryBtn")
        self.send_btn.setStyleSheet(f"#primaryBtn {{ background: {self.theme.TEXT}; border-radius: 16px; }}")
        self.send_btn.update_icon(self.theme.BG)
        compose.addWidget(self.send_btn)

        composer_container.addWidget(composer)

        composer_wrapper.addLayout(composer_container)
        composer_wrapper.addStretch(1)
        content.addLayout(composer_wrapper)

        footer_msg = QLabel("FRIDAY can make mistakes. Verify important information."); footer_msg.setObjectName("footerLbl")
        footer_msg.setAlignment(Qt.AlignmentFlag.AlignCenter); footer_msg.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 11px; margin-bottom: 8px;")
        content.addWidget(footer_msg)
        main_layout.addWidget(main, 1)

        self.attachment_label = QLabel()

    def _toggle_sidebar(self) -> None:
        self.sidebar.setVisible(not self.sidebar.isVisible())
    def _show_history_context_menu(self, position: QPoint) -> None:
        item = self.history.itemAt(position)
        if not item: return
        menu = QMenu()
        menu.setStyleSheet(f"QMenu {{ background: {self.theme.PANEL}; color: {self.theme.TEXT}; border: 1px solid {self.theme.BORDER}; border-radius: 8px; padding: 4px; }} QMenu::item {{ padding: 6px 20px; border-radius: 4px; }} QMenu::item:selected {{ background: {self.theme.HOVER}; }}")
        rename_action = menu.addAction("Rename")
        conversation = self.store.get_conversation(item.data(Qt.ItemDataRole.UserRole))
        pin_action = menu.addAction("Unpin" if conversation and conversation.pinned else "Pin")
        archive_action = menu.addAction("Restore" if conversation and conversation.archived else "Archive")
        menu.addSeparator()
        delete_action = menu.addAction("Delete chat")
        action = menu.exec(self.history.viewport().mapToGlobal(position))
        if action == rename_action:
            self.rename_conversation(item)
        elif action == pin_action:
            self._toggle_pin_conversation(item)
        elif action == archive_action:
            self._toggle_archive_conversation(item)
        elif action == delete_action:
            self.delete_selected_conversation(item)

    def rename_conversation(self, item: QListWidgetItem | None = None) -> None:
        item = item or self.history.currentItem()
        conversation_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        conversation = self.store.get_conversation(conversation_id) if conversation_id else None
        if not conversation:
            return
        title, accepted = QInputDialog.getText(self.window, "Rename conversation", "Title:", text=conversation.title)
        if accepted and title.strip():
            self.store.rename_conversation(conversation.id, title.strip())
            if self.active_conversation and self.active_conversation.id == conversation.id:
                self.active_conversation = self.store.get_conversation(conversation.id)
            self.load_history()

    def _toggle_pin_conversation(self, item: QListWidgetItem) -> None:
        conversation = self.store.get_conversation(item.data(Qt.ItemDataRole.UserRole))
        if conversation:
            self.store.set_pinned(conversation.id, not conversation.pinned)
            self.load_history()

    def _toggle_archive_conversation(self, item: QListWidgetItem) -> None:
        conversation = self.store.get_conversation(item.data(Qt.ItemDataRole.UserRole))
        if not conversation:
            return
        self.store.set_archived(conversation.id, not conversation.archived)
        if self.active_conversation and self.active_conversation.id == conversation.id and not conversation.archived:
            self.new_chat()
        else:
            self.load_history()

    def _toggle_archived_history(self, checked: bool) -> None:
        self.show_archived_btn.setText("Hide archived" if checked else "Show archived")
        self.load_history()

    def delete_selected_conversation(self, item: QListWidgetItem) -> None:
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if not conversation_id: return
        if self._confirm("Delete this chat?"):
            was_active = self.active_conversation and self.active_conversation.id == conversation_id
            self.store.delete_conversation(conversation_id)
            remaining = self.store.conversations()
            if was_active:
                if remaining:
                    # Load the most recent remaining chat instead of creating a new one
                    self.active_conversation = remaining[0]
                    self.load_history()
                    self.render_messages()
                else:
                    self.new_chat()
            else:
                self.load_history()

    def clear_chat(self) -> None:
        if not self.active_conversation: return
        if self._confirm("Clear all messages?"):
            self.store.clear_messages(self.active_conversation.id)
            self.render_messages()

    def run(self) -> None:
        self.window.showFullScreen(); self.qt.exec()

    def _get_model_aliases(self) -> dict:
        import json
        raw = self.store.setting("model_aliases", "{}")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _get_model_display_name(self, internal_id: str) -> str:
        if internal_id == "FRIDAY Auto": return "FRIDAY Auto"
        for m in getattr(self, "models", []):
            if m.name == internal_id:
                return m.display_name

        # Fallback if models not loaded yet
        aliases = self._get_model_aliases()
        if internal_id in aliases and aliases[internal_id]:
            return aliases[internal_id]

        mapping = {
            "qwen2.5:7b": "FRIDAY Pro",
            "qwen3-vl:8b": "FRIDAY Pro Vision",
            "huihui_ai/dolphin3-abliterated:8b": "FRIDAY Thunder Pro"
        }
        return mapping.get(internal_id, internal_id)

    def _get_selected_model(self) -> str:
        return self.model_picker.currentData() or self.model_picker.currentText()

    def _show_profile_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.window)
        menu.setStyleSheet(f"""
            QMenu {{ background: {self.theme.BG}; border: 1px solid {self.theme.BORDER}; border-radius: 6px; padding: 4px; }}
            QMenu::item {{ padding: 8px 24px; color: {self.theme.TEXT}; font-size: 13px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {self.theme.HOVER}; }}
            QMenu::separator {{ height: 1px; background: {self.theme.BORDER}; margin: 4px 0px; }}
        """)

        name = self.store.setting("profile_name", "Boss")
        title_action = menu.addAction(name)
        title_action.setEnabled(False)
        menu.addSeparator()

        menu.addAction("Profile").triggered.connect(self._open_profile_dialog)
        menu.addAction("About FRIDAY").triggered.connect(self._open_about_dialog)
        menu.addAction("Control Center").triggered.connect(self.open_settings)
        menu.addSeparator()
        menu.addAction("Close").triggered.connect(menu.close)

        pos = self.profile_btn.mapToGlobal(self.profile_btn.rect().topRight())
        menu.exec(pos)


    def _open_about_dialog(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
        from PySide6.QtCore import Qt
        dialog = QDialog(self.window)
        dialog.setWindowTitle("About FRIDAY")
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setStyleSheet(f"QDialog {{ background-color: {self.theme.BG}; border: 1px solid {self.theme.BORDER}; }} QLabel {{ color: {self.theme.TEXT}; }} QPushButton {{ background: {self.theme.PANEL}; color: {self.theme.TEXT}; border: 1px solid {self.theme.BORDER}; padding: 6px 12px; border-radius: 4px; }} QPushButton:hover {{ background: {self.theme.HOVER}; }}")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(12, 8, 12, 8)
        title_lbl = QLabel("About FRIDAY")
        title_lbl.setStyleSheet("font-weight: bold;")
        title_bar.addWidget(title_lbl)
        title_bar.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setStyleSheet(f"background: transparent; border: none; font-size: 14px; padding: 0px 4px; color: {self.theme.TEXT};")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(dialog.reject)
        title_bar.addWidget(close_btn)

        layout.addLayout(title_bar)

        content = QVBoxLayout()
        content.setContentsMargins(20, 12, 20, 20)
        import sys, platform
        text = f"""<h3>FRIDAY</h3>
        <p><b>Local AI Assistant</b></p>
        <p><b>Version:</b> 1.0.0</p>
        <p><b>Runtime:</b> Python {sys.version.split()[0]} / PySide6<br/>
        <b>OS:</b> {platform.system()} {platform.release()}</p>
        <p><b>Capabilities:</b><br/>
        • Local AI<br/>
        • Vision<br/>
        • Web<br/>
        • Media<br/>
        • Voice<br/>
        • Tools</p>
        """
        lbl = QLabel(text)
        content.addWidget(lbl)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(ok_btn)
        content.addLayout(btn_layout)

        layout.addLayout(content)
        dialog.exec()

    def _sync_conversation_controls(self) -> None:
        conversation = self.active_conversation
        if not conversation:
            return
        self.model_picker.blockSignals(True)
        index = self.model_picker.findData(conversation.model)
        self.model_picker.setCurrentIndex(index if index >= 0 else 0)
        self.model_picker.blockSignals(False)
        self.incognito_btn.blockSignals(True)
        self.incognito_btn.setChecked(bool(conversation.incognito))
        self.incognito_btn.blockSignals(False)
        self._apply_web_ui(bool(conversation.web_enabled))

    def _refresh_active_conversation(self) -> None:
        if self.active_conversation:
            self.active_conversation = self.store.get_conversation(self.active_conversation.id)

    def _set_active_conversation_model(self, _index: int) -> None:
        if not self.active_conversation:
            return
        model = self._get_selected_model()
        self.store.set_model(self.active_conversation.id, model)
        self._refresh_active_conversation()

    def _set_active_conversation_web(self, enabled: bool) -> None:
        if self.active_conversation:
            self.store.set_conversation_options(self.active_conversation.id, web_enabled=enabled)
            self._refresh_active_conversation()

    def _set_active_conversation_incognito(self, enabled: bool) -> None:
        if self.active_conversation:
            self.store.set_conversation_options(self.active_conversation.id, incognito=enabled)
            self._refresh_active_conversation()

    def _open_context_inspector(self) -> None:
        conversation = self.active_conversation
        if not conversation:
            return
        messages = self.store.messages(conversation.id)
        last_user = next((message.content for message in reversed(messages) if message.role == "user"), "")
        relevant_memory_count = len(self.store.relevant_memories(last_user)) if conversation.memory_enabled and last_user else 0
        attachment_count = 0
        for message in messages:
            try:
                attachment_count += len(json.loads(message.metadata).get("attachments", []))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        details = (
            ("Model", self._get_model_display_name(conversation.model)),
            ("Mode", "Local"),
            ("Instructions", self._get_model_display_name(conversation.model)),
            ("Memory", f"{relevant_memory_count} relevant memories" if conversation.memory_enabled else "Off"),
            ("Conversation", f"{len(messages)} messages"),
            ("Attachments", str(attachment_count)),
            ("Web", "ON" if conversation.web_enabled else "OFF"),
            ("Incognito", "ON" if conversation.incognito else "OFF"),
            ("Tools", "Available on demand"),
        )
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Conversation context")
        dialog.setMinimumWidth(360)
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setObjectName("conversationContextDialog")
        dialog.setAutoFillBackground(True)
        dialog.setStyleSheet(f"#conversationContextDialog {{ background: {self.theme.BG}; color: {self.theme.TEXT}; border: 1px solid {self.theme.BORDER}; }}")
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        header = QWidget()
        header.setStyleSheet(f"background: {self.theme.PANEL}; border-bottom: 1px solid {self.theme.BORDER};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 8, 8, 8)
        header_title = QLabel("Conversation context")
        header_title.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: bold; font-size: 13px;")
        close_title = QPushButton("×")
        close_title.setFixedSize(26, 26)
        close_title.setToolTip("Close")
        close_title.setStyleSheet(f"QPushButton {{ background: transparent; color: {self.theme.MUTED}; border: none; font-size: 18px; }} QPushButton:hover {{ color: {self.theme.DANGER}; background: {self.theme.HOVER}; border-radius: 4px; }}")
        close_title.clicked.connect(dialog.accept)
        header_layout.addWidget(header_title)
        header_layout.addStretch(1)
        header_layout.addWidget(close_title)
        main_layout.addWidget(header)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 16, 18, 18)
        main_layout.addWidget(body)
        title = QLabel("CONTEXT")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {self.theme.TEXT};")
        layout.addWidget(title)
        for label, value in details:
            row = QHBoxLayout()
            key = QLabel(label)
            key.setStyleSheet(f"color: {self.theme.MUTED};")
            val = QLabel(value)
            val.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: 600;")
            row.addWidget(key)
            row.addStretch(1)
            row.addWidget(val)
            layout.addLayout(row)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _open_profile_dialog(self):
        from friday.profile_ui import ProfileDialog
        dialog = ProfileDialog(self.store, self.theme, self.window)
        dialog.profile_updated.connect(self._on_profile_updated)
        dialog.exec()

    def _on_profile_updated(self, name, pic_path):
        from friday.ui_components import Avatar
        self.user_name_lbl.setText(name)
        new_avatar = Avatar(name, self.theme, size=28, pic_path=pic_path)
        self.profile_btn.layout().replaceWidget(self.user_avatar, new_avatar)
        self.user_avatar.deleteLater()
        self.user_avatar = new_avatar
        self.render_messages()

    def new_chat(self) -> None:
        self.active_conversation = self.store.new_conversation(self._get_selected_model(), web_enabled=self.web_enabled)
        self.attachments = []; self._render_attachments(); self.render_messages(); self.load_history(); self.input.setFocus()
        self._sync_conversation_controls()
        self._update_sidebar_indicators()

    def load_history(self, _query: str = "") -> None:
        self.history.blockSignals(True); self.history.clear()
        query = self.history_search.text().strip() if hasattr(self, "history_search") else ""
        include_archived = self.show_archived_btn.isChecked() if hasattr(self, "show_archived_btn") else False
        for conversation in self.store.conversations(query, include_archived=include_archived):
            title = ("★ " if conversation.pinned else "") + conversation.title
            if conversation.archived:
                title = "[Archived] " + title
            item = QListWidgetItem(title); item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            if query:
                item.setToolTip("Matches conversation title or message content")
            self.history.addItem(item)
        if self.active_conversation:
            for i in range(self.history.count()):
                if self.history.item(i).data(Qt.ItemDataRole.UserRole) == self.active_conversation.id:
                    self.history.blockSignals(True)
                    self.history.setCurrentRow(i)
                    self.history.blockSignals(False)
                    break
        self.history.blockSignals(False)
        self._update_sidebar_indicators()

    def _open_history_item(self, item: QListWidgetItem) -> None:
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if not conversation_id: return
        if self.active_conversation and conversation_id == self.active_conversation.id: return
        self.active_conversation = self.store.get_conversation(conversation_id)
        index = self.model_picker.findData(self.active_conversation.model); self.model_picker.setCurrentIndex(index if index >= 0 else 0); self.render_messages()
        self._sync_conversation_controls()
        self._update_sidebar_indicators()

    def _open_selected_history(self) -> None:
        item = self.history.currentItem(); conversation_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not conversation_id: return
        if self.active_conversation and conversation_id == self.active_conversation.id: return
        self.active_conversation = self.store.get_conversation(conversation_id)
        index = self.model_picker.findData(self.active_conversation.model); self.model_picker.setCurrentIndex(index if index >= 0 else 0); self.render_messages()
        self._sync_conversation_controls()
        self._update_sidebar_indicators()

    def clear_messages(self) -> None:
        while self.message_layout.count():
            item = self.message_layout.takeAt(0); widget = item.widget()
            if widget: widget.deleteLater()


    def _get_greeting(self) -> str:
        import datetime
        import random
        hour = datetime.datetime.now().hour
        name = "Boss"
        if hour < 12:
            return random.choice([f"Good morning, {name}.", f"Morning, {name}. What are we building today?", f"Good morning, {name}. Ready when you are."])
        elif hour < 18:
            return random.choice([f"Good afternoon, {name}.", f"Good afternoon, {name}. What shall we tackle?", f"Afternoon, {name}. FRIDAY is standing by."])
        else:
            return random.choice([f"Good evening, {name}.", f"Still working, {name}?", f"FRIDAY is still online, {name}."])

    def render_messages(self) -> None:
        self.clear_messages()
        if not self.active_conversation: return
        messages = [item for item in self.store.messages(self.active_conversation.id) if item.role != "tool"]
        if not messages:
            self.message_layout.addStretch(1)

            center_wrap = QVBoxLayout()
            center_wrap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            center_wrap.setSpacing(16)

            from friday.ui_components import Avatar, SuggestionCard

            avatar = Avatar("F", self.theme, size=56)
            avatar_layout = QHBoxLayout(); avatar_layout.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignCenter)
            center_wrap.addLayout(avatar_layout)

            greeting = QLabel(self._get_greeting())
            greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
            greeting.setStyleSheet(f"font-size: 26px; font-weight: 600; color: {self.theme.TEXT};")
            center_wrap.addWidget(greeting)

            subtext = QLabel("What shall we work on today?")
            subtext.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtext.setStyleSheet(f"font-size: 16px; color: {self.theme.MUTED}; margin-bottom: 16px;")
            center_wrap.addWidget(subtext)

            sugg_layout = QHBoxLayout()
            sugg_layout.setSpacing(16)
            sugg_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            s1 = SuggestionCard("Analyze an image", "Understand and inspect images", "image", self.theme)
            s1.clicked.connect(lambda t: self.input.setPlainText(t))
            sugg_layout.addWidget(s1)

            s2 = SuggestionCard("Search the web", "Find current information", "globe", self.theme)
            s2.clicked.connect(lambda t: self.input.setPlainText(t))
            sugg_layout.addWidget(s2)

            s3 = SuggestionCard("Control Center", "Manage FRIDAY", "settings", self.theme)
            s3.clicked.connect(lambda _: self.open_settings())
            sugg_layout.addWidget(s3)

            center_wrap.addLayout(sugg_layout)

            cw = QWidget(); cw.setLayout(center_wrap)
            self.message_layout.addWidget(cw)

            self.message_layout.addStretch(2)
        else:
            import json
            for item in messages:
                meta = {}
                try:
                    if item.metadata:
                        meta = json.loads(item.metadata)
                except:
                    pass
                self.add_message(item.role, item.content, meta)

        # Restore live background job if one is running for this conversation
        job = self._conv_jobs.get(self.active_conversation.id)
        if job:
            initial_text = job["buffer"] if job["buffer"] else f"*{job.get('status', 'Thinking...')}*"
            view, activity = self.add_message("assistant", initial_text, return_activity=True)
            job["live_view"] = view
            job["live_activity"] = activity

            if activity and "status" in job:
                activity.set_status(job["status"])

            if job.get("media"):
                import json
                try:
                    from friday.components import MediaCard
                    if self.message_layout.count() > 0:
                        last_row = self.message_layout.itemAt(self.message_layout.count() - 1).widget()
                        if last_row:
                            row_layout = last_row.layout()
                            if row_layout and row_layout.count() > 0:
                                content_wrapper = row_layout.itemAt(0).widget()
                                if content_wrapper and content_wrapper.layout():
                                    for m_data in job["media"]:
                                        card = MediaCard(m_data, self.theme)
                                        content_wrapper.layout().addWidget(card)
                except Exception as e:
                    print(f"Error restoring media: {e}")

            if job.get("image_search"):
                try:
                    from friday.components import ImageSearchWidget
                    data = job["image_search"]
                    query = data.get("query", "Search")
                    results = data.get("results", [])
                    if self.message_layout.count() > 0:
                        last_row = self.message_layout.itemAt(self.message_layout.count() - 1).widget()
                        if last_row:
                            row_layout = last_row.layout()
                            if row_layout and row_layout.count() > 0:
                                content_wrapper = row_layout.itemAt(0).widget()
                                if content_wrapper and content_wrapper.layout():
                                    widget = ImageSearchWidget(query, results, self.theme, on_download=self._download_image_result)
                                    content_wrapper.layout().addWidget(widget)
                except Exception as e:
                    print(f"Error restoring image search: {e}")

            self.stop_button.setEnabled(True)
            self.stop_button.setVisible(True)
            self.send_btn.setVisible(False)
        else:
            self.stop_button.setEnabled(False)
            self.stop_button.setVisible(False)
            self.send_btn.setVisible(True)

        self.scroll_to_bottom()

    def add_message(self, role: str, content: str = "", metadata: dict = None, return_activity: bool = False):
        from friday.ui_components import Avatar, IconButton
        row = QWidget(); row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0, 0, 0, 0)
        is_user = role == "user"

        content_wrapper = QWidget();
        content_wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        wrapper_layout = QVBoxLayout(content_wrapper); wrapper_layout.setContentsMargins(0,0,0,0); wrapper_layout.setSpacing(6);

        if is_user:
            row_layout.addStretch(1); row_layout.addWidget(content_wrapper)
            header = QHBoxLayout(); header.setContentsMargins(0,0,0,0); header.setSpacing(12)
            header.addStretch(1)
            u_name = self.store.setting("profile_name", "Boss")
            u_pic = self.store.setting("profile_pic", "")
            name_lbl = QLabel(u_name); name_lbl.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: bold;")
            avatar = Avatar(u_name, self.theme, size=28, pic_path=u_pic)
            header.addWidget(name_lbl); header.addWidget(avatar)
            wrapper_layout.addLayout(header)

            label = QLabel(content); label.setObjectName("msgView"); label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setStyleSheet(f"background: {self.theme.USER}; padding: 12px 16px; border-radius: 16px; color: {self.theme.TEXT};")

            c_lay = QHBoxLayout(); c_lay.setContentsMargins(0,0,0,0); c_lay.addStretch(1); c_lay.addWidget(label)
            wrapper_layout.addLayout(c_lay)

            self.message_layout.addWidget(row)
            return (label, None) if return_activity else label
        else:
            row_layout.addWidget(content_wrapper, stretch=1)
            header = QHBoxLayout(); header.setContentsMargins(0,0,0,0); header.setSpacing(12)
            avatar = Avatar("F", self.theme, size=28)
            name_lbl = QLabel("FRIDAY"); name_lbl.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: bold;")
            header.addWidget(avatar); header.addWidget(name_lbl)

            used_model = self.active_conversation.model if hasattr(self, 'active_conversation') and self.active_conversation else self._get_selected_model()
            if used_model:
                disp = self._get_model_display_name(used_model)
                tech_lbl = QLabel(f"· {disp} · Local"); tech_lbl.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 11px;")
                header.addWidget(tech_lbl)

            header.addStretch(1)
            wrapper_layout.addLayout(header)

            act_widget = None
            if return_activity:
                from friday.ui_activity import ActivityWidget
                act_widget = ActivityWidget(self.theme, disp if "disp" in locals() else "")
                wrapper_layout.addWidget(act_widget)

            view = QTextBrowser(); view.setObjectName("msgView"); view.setOpenExternalLinks(True); view.setFrameShape(QFrame.Shape.NoFrame); view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); view.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents); view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            view.setStyleSheet(f"background: transparent; color: {self.theme.TEXT};")
            view.document().contentsChanged.connect(lambda view=view: self._fit_message_view(view))
            wrapper_layout.addWidget(view)

            actions = QHBoxLayout(); actions.setContentsMargins(0,0,0,0); actions.setSpacing(4)
            copy = IconButton("message", self.theme, size=28, icon_size=14); copy.setToolTip("Copy")
            copy.clicked.connect(lambda: self.qt.clipboard().setText(view.toPlainText()))
            actions.addWidget(copy)

            regen = IconButton("refresh", self.theme, size=28, icon_size=14); regen.setToolTip("Regenerate")
            regen.clicked.connect(self.regenerate)
            actions.addWidget(regen)
            actions.addStretch(1)
            wrapper_layout.addLayout(actions)

            if metadata and metadata.get("media"):
                try:
                    from friday.components import MediaCard
                    for m_data in metadata["media"]:
                        card = MediaCard(m_data, self.theme)
                        wrapper_layout.addWidget(card)
                except Exception as e:
                    print(f"Error rendering media: {e}")

            if metadata and metadata.get("image_search"):
                try:
                    from friday.components import ImageSearchWidget
                    import json
                    m_data = json.loads(metadata["image_search"]) if isinstance(metadata["image_search"], str) else metadata["image_search"]
                    widget = ImageSearchWidget(m_data.get("query", "Search"), m_data.get("results", []), self.theme, on_download=self._download_image_result)
                    wrapper_layout.addWidget(widget)
                except Exception as e:
                    print(f"Error rendering image_search: {e}")

            if content: view.setMarkdown(content)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda view=view: self._fit_message_view(view))

            self.message_layout.addWidget(row)
            return (view, act_widget) if return_activity else view

    def _fit_message_view(self, view: QTextBrowser) -> None:
        width = view.viewport().width()
        if width > 0:
            view.document().setTextWidth(width)
        height = int(view.document().size().height()) + 8
        view.setFixedHeight(max(24, height))

    def send(self) -> None:
        prompt = self.input.toPlainText().strip()
        if not prompt or not self.active_conversation or self.stop_button.isEnabled():
            return
        attachment_names = [name for name, _ in self.attachments]
        self.input.setPlainText(""); self.add_message("user", prompt + (("\n\nAttached: " + ", ".join(attachment_names)) if attachment_names else ""));

        initial_status = "Loading Qwen3-VL..." if attachment_names else "Thinking..."
        view, activity = self.add_message("assistant", f"*{initial_status}*", return_activity=True)
        self.live_view = view
        self.live_activity = activity
        if self.live_activity:
            self.live_activity.set_status(initial_status)
        self._first_token = True

        conv_id = self.active_conversation.id
        selected_model = self.active_conversation.model
        is_incognito = bool(self.active_conversation.incognito)
        force_web = bool(self.active_conversation.web_enabled)

        existing = self._conv_jobs.get(conv_id)
        if existing:
            existing["cancel"].set()

        cancel_ev = threading.Event()
        self._conv_jobs[conv_id] = {
            "cancel": cancel_ev,
            "live_view": view,
            "live_activity": activity,
            "buffer": "",
            "status": initial_status,
            "media": [],
            "image_search": None,
            "_first_token": True
        }

        self.cancel_event = cancel_ev

        self.stop_button.setEnabled(True); self.stop_button.setVisible(True); self.send_btn.setVisible(False)
        self.store.set_model(conv_id, selected_model)

        # Capture conv_id at call time — emit always routes to the right conversation
        emit = lambda kind, value, _cid=conv_id: self.bridge.conv_event.emit(_cid, kind, value)

        thread = threading.Thread(
            target=self.chat.respond,
            args=(conv_id, selected_model, prompt, self.attachments[:], self.models[:], emit, cancel_ev, force_web, is_incognito),
            daemon=True
        )
        self._conv_jobs[conv_id]["thread"] = thread
        self.attachments = []; self._render_attachments(); thread.start(); self.scroll_to_bottom()

    def _is_conv_active(self, conv_id: str) -> bool:
        """Returns True if conv_id is the currently displayed conversation."""
        return bool(self.active_conversation and self.active_conversation.id == conv_id)

    def regenerate(self) -> None:
        if not self.active_conversation: return
        conv_id = self.active_conversation.id
        if conv_id in self._conv_jobs and not self._conv_jobs[conv_id]["cancel"].is_set():
            return  # still generating for this conversation
        last_user = next((item for item in reversed(self.store.messages(conv_id)) if item.role == "user"), None)
        if not last_user: return
        self.store.delete_last_assistant_message(conv_id)
        self.render_messages()
        view, activity = self.add_message("assistant", "*Thinking...*", return_activity=True)
        self.live_view = view
        self.live_activity = activity
        if self.live_activity:
            self.live_activity.set_status("Thinking...")

        cancel_ev = threading.Event()
        self._conv_jobs[conv_id] = {
            "cancel": cancel_ev,
            "live_view": view,
            "live_activity": activity,
            "buffer": "",
            "status": "Thinking...",
            "media": [],
            "image_search": None,
            "_first_token": True
        }
        self.cancel_event = cancel_ev
        self.stop_button.setEnabled(True); self.stop_button.setVisible(True); self.send_btn.setVisible(False)
        emit = lambda kind, value, _cid=conv_id: self.bridge.conv_event.emit(_cid, kind, value)
        thread = threading.Thread(target=self.chat.regenerate, args=(conv_id, self.active_conversation.model, last_user.content, self.models[:], emit, cancel_ev), daemon=True)
        self._conv_jobs[conv_id]["thread"] = thread
        thread.start()

    def stop(self) -> None:
        """Cancel ONLY the active conversation's request. Other conversations continue."""
        if not self.active_conversation:
            return
        conv_id = self.active_conversation.id
        job = self._conv_jobs.get(conv_id)
        if job:
            job["cancel"].set()
        self.stop_button.setEnabled(False)
        job_activity = job.get("live_activity") if job else None
        if job_activity:
            job_activity.set_status("Stopping...")
        elif hasattr(self, 'live_activity') and self.live_activity:
            self.live_activity.set_status("Stopping...")



    def _handle_permission_request_threadsafe(self, req) -> bool:
        self.permission_event.clear()
        self.bridge.permission_request.emit(req)
        self.permission_event.wait()
        return self.permission_result

    def _show_permission_dialog(self, req):
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Permission Required")
        msg.setText(f"FRIDAY wants to perform: {req.action_name}")
        msg.setInformativeText(f"Target: {req.target}\n\nConsequence: {req.consequence}\n\nDo you allow this action?")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.setStyleSheet(f"background-color: {self.BG}; color: {self.TEXT};")

        result = msg.exec()
        self.permission_result = (result == QMessageBox.StandardButton.Yes)
        self.permission_event.set()


    def _download_image_result(self, result_dict):
        from friday.image_search import ImageSearchHub, ImageSearchResult
        hub = ImageSearchHub(self.store)
        if isinstance(result_dict, dict):
            # filter keys to avoid TypeError
            import inspect
            sig = inspect.signature(ImageSearchResult.__init__)
            valid_keys = [k for k in sig.parameters if k != 'self']
            filtered = {k: v for k, v in result_dict.items() if k in valid_keys}
            res = ImageSearchResult(**filtered)
        else:
            res = result_dict
        return hub.download_image(res)

    def _handle_conv_event(self, conv_id: str, kind: str, value: str) -> None:
        """Routes per-conversation events. Only updates UI widgets if conv_id is currently active."""
        is_active = self._is_conv_active(conv_id)
        job = self._conv_jobs.get(conv_id)
        if not job:
            return  # Job was already cleaned up or never existed

        live_view = job.get("live_view") if is_active else None
        live_activity = job.get("live_activity") if is_active else None

        if kind == "status":
            job["status"] = value
            if live_activity:
                live_activity.set_status(value)

        elif kind == "done":
            cancel_ev = job.get("cancel")
            was_cancelled = cancel_ev.is_set() if cancel_ev else False
            if live_activity:
                live_activity.complete(cancelled=was_cancelled)
            if is_active:
                self.stop_button.setEnabled(False)
                self.stop_button.setVisible(False)
                self.send_btn.setVisible(True)
                self.load_history()
                self.render_messages()
            else:
                # Background conv finished — just refresh sidebar so title updates
                self.load_history()
            self._conv_jobs.pop(conv_id, None)
            self._update_sidebar_indicators()

        elif kind == "token":
            job["buffer"] += value
            if live_view:
                if job.get("_first_token", True):
                    live_view.setMarkdown("")
                    job["_first_token"] = False
                cursor = live_view.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(value)
                live_view.setTextCursor(cursor)
                if is_active:
                    self.scroll_to_bottom()

        elif kind == "media":
            import json
            try:
                media_list = json.loads(value)
                job["media"].extend(media_list)
                if is_active:
                    from friday.components import MediaCard
                    if self.message_layout.count() > 0:
                        last_row = self.message_layout.itemAt(self.message_layout.count() - 1).widget()
                        if last_row:
                            row_layout = last_row.layout()
                            if row_layout and row_layout.count() > 0:
                                content_wrapper = row_layout.itemAt(0).widget()
                                if content_wrapper and content_wrapper.layout():
                                    for m_data in media_list:
                                        card = MediaCard(m_data, self.theme)
                                        content_wrapper.layout().addWidget(card)
                                    self.scroll_to_bottom()
            except Exception as e:
                print(f"Media event error: {e}")

        elif kind == "image_search":
            import json
            try:
                data = json.loads(value)
                job["image_search"] = data
                if is_active:
                    from friday.components import ImageSearchWidget
                    query = data.get("query", "Search")
                    results = data.get("results", [])
                    if self.message_layout.count() > 0:
                        last_row = self.message_layout.itemAt(self.message_layout.count() - 1).widget()
                        if last_row:
                            row_layout = last_row.layout()
                            if row_layout and row_layout.count() > 0:
                                content_wrapper = row_layout.itemAt(0).widget()
                                if content_wrapper and content_wrapper.layout():
                                    widget = ImageSearchWidget(query, results, self.theme, on_download=self._download_image_result)
                                    content_wrapper.layout().addWidget(widget)
                                    self.scroll_to_bottom()
            except Exception as e:
                print(f"Image search event error: {e}")

        elif kind == "error":
            if is_active:
                self.stop_button.setEnabled(False)
                self.stop_button.setVisible(False)
                self.send_btn.setVisible(True)
                if live_view:
                    from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
                    from friday.icons import get_icon
                    err_widget = QWidget()
                    err_widget.setStyleSheet(f"QWidget {{ background-color: {self.theme.PANEL}; border: 1px solid {self.theme.DANGER}; border-radius: 8px; }}")
                    err_layout = QVBoxLayout(err_widget)
                    err_layout.setContentsMargins(16, 16, 16, 16)
                    header = QHBoxLayout()
                    icon_lbl = QLabel()
                    icon_lbl.setPixmap(get_icon("alert-circle", self.theme.DANGER, 20).pixmap(20, 20))
                    header.addWidget(icon_lbl)
                    title = QLabel("Connection issue" if "Ollama" in value else "Error")
                    title.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: bold; font-size: 14px; border: none;")
                    header.addWidget(title)
                    header.addStretch(1)
                    err_layout.addLayout(header)
                    msg = QLabel(value)
                    msg.setWordWrap(True)
                    msg.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 13px; border: none;")
                    err_layout.addWidget(msg)
                    btn_layout = QHBoxLayout()
                    retry_btn = QPushButton("Retry Connection")
                    retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    retry_btn.setStyleSheet(f"QPushButton {{ background: {self.theme.BG}; color: {self.theme.TEXT}; border: 1px solid {self.theme.BORDER}; border-radius: 6px; padding: 6px 12px; font-weight: 500; }} QPushButton:hover {{ background: {self.theme.HOVER}; }}")
                    retry_btn.clicked.connect(self.regenerate)
                    btn_layout.addWidget(retry_btn)
                    btn_layout.addStretch(1)
                    err_layout.addLayout(btn_layout)
                    parent_layout = live_view.parentWidget().layout()
                    parent_layout.addWidget(err_widget)
                if live_activity:
                    live_activity.complete(error=True)
            self._conv_jobs.pop(conv_id, None)
            self._update_sidebar_indicators()

        elif kind in ("source", "tool_start"):
            if is_active:
                # pass these through to existing _handle_event for backward compat
                self._handle_event(kind, value)

        elif kind == "models":
            self._apply_models()


    def _update_sidebar_indicators(self) -> None:
        """Add/remove a subtle '●' indicator on sidebar items that have an active background job."""
        active_conv_ids = set(self._conv_jobs.keys())
        for i in range(self.history.count()):
            item = self.history.item(i)
            conv_id = item.data(Qt.ItemDataRole.UserRole)
            title = item.text()
            clean = title.rstrip(" ●⟳")
            if conv_id in active_conv_ids and conv_id != (self.active_conversation.id if self.active_conversation else ""):
                item.setText(clean + " ●")
            else:
                item.setText(clean)

    def _handle_conv_event(self, conv_id: str, kind: str, value: str) -> None:
        """Routes per-conversation events. Only updates UI widgets if conv_id is currently active."""
        is_active = self._is_conv_active(conv_id)
        job = self._conv_jobs.get(conv_id, {})
        live_view = job.get("live_view") if is_active else None
        live_activity = job.get("live_activity") if is_active else None

        if kind == "status":
            if live_activity:
                live_activity.set_status(value)

        elif kind == "done":
            cancel_ev = job.get("cancel")
            was_cancelled = cancel_ev.is_set() if cancel_ev else False
            if live_activity:
                live_activity.complete(cancelled=was_cancelled)
            if is_active:
                self.stop_button.setEnabled(False)
                self.stop_button.setVisible(False)
                self.send_btn.setVisible(True)
                self.load_history()
                self.render_messages()
            else:
                # Background conv finished — just refresh sidebar so title updates
                self.load_history()
            self._conv_jobs.pop(conv_id, None)
            self._update_sidebar_indicators()

        elif kind == "token":
            if live_view:
                if job.get("_first_token", True):
                    live_view.setMarkdown("")
                    job["_first_token"] = False
                cursor = live_view.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(value)
                live_view.setTextCursor(cursor)
                if is_active:
                    self.scroll_to_bottom()

        elif kind == "media":
            if is_active:
                import json
                try:
                    from friday.components import MediaCard
                    media_list = json.loads(value)
                    if self.message_layout.count() > 0:
                        last_row = self.message_layout.itemAt(self.message_layout.count() - 1).widget()
                        if last_row:
                            row_layout = last_row.layout()
                            if row_layout and row_layout.count() > 0:
                                content_wrapper = row_layout.itemAt(0).widget()
                                if content_wrapper and content_wrapper.layout():
                                    for m_data in media_list:
                                        card = MediaCard(m_data, self.theme)
                                        content_wrapper.layout().addWidget(card)
                                    self.scroll_to_bottom()
                except Exception as e:
                    print(f"Media event error: {e}")

        elif kind == "image_search":
            if is_active:
                import json
                try:
                    from friday.components import ImageSearchWidget
                    data = json.loads(value)
                    query = data.get("query", "Search")
                    results = data.get("results", [])
                    if self.message_layout.count() > 0:
                        last_row = self.message_layout.itemAt(self.message_layout.count() - 1).widget()
                        if last_row:
                            row_layout = last_row.layout()
                            if row_layout and row_layout.count() > 0:
                                content_wrapper = row_layout.itemAt(0).widget()
                                if content_wrapper and content_wrapper.layout():
                                    widget = ImageSearchWidget(query, results, self.theme, on_download=self._download_image_result)
                                    content_wrapper.layout().addWidget(widget)
                                    self.scroll_to_bottom()
                except Exception as e:
                    print(f"Image search event error: {e}")

        elif kind == "error":
            if is_active:
                self.stop_button.setEnabled(False)
                self.stop_button.setVisible(False)
                self.send_btn.setVisible(True)
                if live_view:
                    from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
                    from friday.icons import get_icon
                    err_widget = QWidget()
                    err_widget.setStyleSheet(f"QWidget {{ background-color: {self.theme.PANEL}; border: 1px solid {self.theme.DANGER}; border-radius: 8px; }}")
                    err_layout = QVBoxLayout(err_widget)
                    err_layout.setContentsMargins(16, 16, 16, 16)
                    header = QHBoxLayout()
                    icon_lbl = QLabel()
                    icon_lbl.setPixmap(get_icon("alert-circle", self.theme.DANGER, 20).pixmap(20, 20))
                    header.addWidget(icon_lbl)
                    title = QLabel("Connection issue" if "Ollama" in value else "Error")
                    title.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: bold; font-size: 14px; border: none;")
                    header.addWidget(title)
                    header.addStretch(1)
                    err_layout.addLayout(header)
                    msg = QLabel(value)
                    msg.setWordWrap(True)
                    msg.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 13px; border: none;")
                    err_layout.addWidget(msg)
                    btn_layout = QHBoxLayout()
                    retry_btn = QPushButton("Retry Connection")
                    retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    retry_btn.setStyleSheet(f"QPushButton {{ background: {self.theme.BG}; color: {self.theme.TEXT}; border: 1px solid {self.theme.BORDER}; border-radius: 6px; padding: 6px 12px; font-weight: 500; }} QPushButton:hover {{ background: {self.theme.HOVER}; }}")
                    retry_btn.clicked.connect(self.regenerate)
                    btn_layout.addWidget(retry_btn)
                    btn_layout.addStretch(1)
                    err_layout.addLayout(btn_layout)
                    parent_layout = live_view.parentWidget().layout()
                    parent_layout.addWidget(err_widget)
                if live_activity:
                    live_activity.complete(error=True)
            self._conv_jobs.pop(conv_id, None)
            self._update_sidebar_indicators()

        elif kind in ("source", "tool_start"):
            if is_active:
                # pass these through to existing _handle_event for backward compat
                self._handle_event(kind, value)

        elif kind == "models":
            self._apply_models()

    def _update_sidebar_indicators(self) -> None:
        """Add/remove a subtle '●' indicator on sidebar items that have an active background job."""
        active_conv_ids = set(self._conv_jobs.keys())
        for i in range(self.history.count()):
            item = self.history.item(i)
            conv_id = item.data(Qt.ItemDataRole.UserRole)
            title = item.text()
            clean = title.rstrip(" ●⟳")
            if conv_id in active_conv_ids and conv_id != (self.active_conversation.id if self.active_conversation else ""):
                item.setText(clean + " ●")
            else:
                item.setText(clean)

    def _handle_event(self, kind: str, value: str) -> None:
        if kind == "status":
            if hasattr(self, 'live_activity') and self.live_activity:
                self.live_activity.set_status(value)
        elif kind == "done":
            if hasattr(self, 'live_activity') and self.live_activity:
                if self.cancel_event.is_set():
                    self.live_activity.complete(cancelled=True)
                else:
                    self.live_activity.complete()
            self.stop_button.setEnabled(False)
            self.cancel_event.clear()
            self.load_history()
            self.render_messages()

        if kind == "media":
            import json
            try:
                from friday.components import MediaCard
                media_list = json.loads(value)
                if self.message_layout.count() > 0:
                    last_row = self.message_layout.itemAt(self.message_layout.count() - 1).widget()
                    if last_row:
                        row_layout = last_row.layout()
                        if row_layout and row_layout.count() > 0:
                            content_wrapper = row_layout.itemAt(0).widget()
                            if content_wrapper and content_wrapper.layout():
                                for m_data in media_list:
                                    card = MediaCard(m_data, self.theme)
                                    content_wrapper.layout().addWidget(card)
                                self.scroll_to_bottom()
            except Exception as e:
                print(f"Media event error: {e}")
        elif kind == "token" and self.live_view:
            if getattr(self, '_first_token', False):
                self.live_view.setMarkdown("")
                self._first_token = False
            cursor = self.live_view.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End); cursor.insertText(value); self.live_view.setTextCursor(cursor); self.scroll_to_bottom()
        elif kind == "models": self._apply_models()
        elif kind == "image_search":
            import json
            try:
                from friday.components import ImageSearchWidget
                data = json.loads(value)
                query = data.get("query", "Search")
                results = data.get("results", [])

                if self.message_layout.count() > 0:
                    last_row = self.message_layout.itemAt(self.message_layout.count() - 1).widget()
                    if last_row:
                        row_layout = last_row.layout()
                        if row_layout and row_layout.count() > 0:
                            content_wrapper = row_layout.itemAt(0).widget()
                            if content_wrapper and content_wrapper.layout():
                                widget = ImageSearchWidget(query, results, self.theme, on_download=self._download_image_result)
                                content_wrapper.layout().addWidget(widget)
                                self.scroll_to_bottom()
            except Exception as e:
                print(f"Image search event error: {e}")
        elif kind == "error":
            self.stop_button.setEnabled(False)
            if self.live_view:
                from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
                from friday.icons import get_icon

                err_widget = QWidget()
                err_widget.setStyleSheet(f"""
                    QWidget {{ background-color: {self.theme.PANEL}; border: 1px solid {self.theme.DANGER}; border-radius: 8px; }}
                """)
                err_layout = QVBoxLayout(err_widget)
                err_layout.setContentsMargins(16, 16, 16, 16)

                header = QHBoxLayout()
                icon_lbl = QLabel()
                icon_lbl.setPixmap(get_icon("alert-circle", self.theme.DANGER, 20).pixmap(20, 20))
                header.addWidget(icon_lbl)
                title = QLabel("Connection issue" if "Ollama" in value else "Error")
                title.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: bold; font-size: 14px; border: none;")
                header.addWidget(title)
                header.addStretch(1)
                err_layout.addLayout(header)

                msg = QLabel(value)
                msg.setWordWrap(True)
                msg.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 13px; border: none;")
                err_layout.addWidget(msg)

                btn_layout = QHBoxLayout()
                retry_btn = QPushButton("Retry Connection")
                retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                retry_btn.setStyleSheet(f"""
                    QPushButton {{ background: {self.theme.BG}; color: {self.theme.TEXT}; border: 1px solid {self.theme.BORDER}; border-radius: 6px; padding: 6px 12px; font-weight: 500; }}
                    QPushButton:hover {{ background: {self.theme.HOVER}; }}
                """)
                retry_btn.clicked.connect(self.regenerate)
                btn_layout.addWidget(retry_btn)
                btn_layout.addStretch(1)
                err_layout.addLayout(btn_layout)

                parent_layout = self.live_view.parentWidget().layout()
                parent_layout.addWidget(err_widget)

                if hasattr(self, 'live_activity') and self.live_activity:
                    self.live_activity.complete(error=True)

    def scroll_to_bottom(self) -> None:
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def add_attachment(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self.window, "Attach local files", "", "Text, code & images (*.txt *.md *.py *.json *.csv *.html *.js *.ts *.log *.png *.jpg *.jpeg *.webp *.gif);;All files (*.*)")
        for raw_path in paths:
            path = Path(raw_path)
            try:
                if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                    if path.stat().st_size > 5_000_000: raise ValueError("images above 5 MB are not supported")
                    import base64
                    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
                    self.attachments.append((path.name, f"B64IMG:{b64}"))
                else:
                    if path.stat().st_size > 1_000_000: raise ValueError("files above 1 MB are not included in chat context")
                    self.attachments.append((path.name, path.read_text(encoding="utf-8", errors="replace")))
            except Exception as error: QMessageBox.warning(self.window, "Friday", f"Could not read {path.name}: {error}")
        self._render_attachments()

    def _remove_attachment(self, filepath: str) -> None:
        self.attachments = [(n, p) for n, p in self.attachments if p != filepath]
        self._render_attachments()

    def _render_attachments(self) -> None:
        while self.attachment_layout.count():
            item = self.attachment_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.attachments:
            self.attachment_container.hide()
            return

        self.attachment_container.show()
        from friday.ui_components import AttachmentChip
        for name, path in self.attachments:
            chip = AttachmentChip(name, path, self.theme)
            chip.removed.connect(self._remove_attachment)
            self.attachment_layout.addWidget(chip)
        self.attachment_layout.addStretch(1)

    def refresh_models(self, silent: bool = False) -> None:
        def work() -> None:
            aliases = self._get_model_aliases()
            self.models = self.provider.available_models(aliases=aliases)
            self.bridge.event.emit("models", "")
        threading.Thread(target=work, daemon=True).start()

    def _auto_start_and_refresh(self) -> None:
        selected_model = self._get_selected_model()
        def work() -> None:
            if not self.provider.is_running():
                self.launcher.ensure_running()
            aliases = self._get_model_aliases()
            self.models = self.provider.available_models(aliases=aliases)
            self.bridge.event.emit("models", "")
            installed = {model.name for model in self.models}
            model_to_load = selected_model if selected_model in installed else self.chat._default_chat_model()
            if not model_to_load or model_to_load not in installed:
                model_to_load = self.chat.router.choose("", self.models)
            if model_to_load:
                try:
                    self.provider.load_model(model_to_load, keep_alive="5m")
                except Exception:
                    logger.info("Could not preload the selected local model at startup", exc_info=True)
        threading.Thread(target=work, daemon=True).start()

    def _apply_models(self) -> None:
        current_data = self._get_selected_model()
        self.model_picker.blockSignals(True)
        self.model_picker.clear(); self.model_picker.addItem("FRIDAY Auto", userData="FRIDAY Auto")

        for model in self.models:
            self.model_picker.addItem(model.display_name, userData=model.name)

        idx = 0
        for i in range(self.model_picker.count()):
            if (self.model_picker.itemData(i) or self.model_picker.itemText(i)) == current_data:
                idx = i
                break
        self.model_picker.setCurrentIndex(idx)
        self.model_picker.blockSignals(False)
        self._sync_conversation_controls()
        control_center = getattr(self, "_control_center_dialog", None)
        if control_center is not None and hasattr(control_center, "refresh_routing_models"):
            control_center.refresh_routing_models()


    def open_settings(self) -> None:
        try:
            from friday.control_center import ControlCenterDialog
            dialog = ControlCenterDialog(self, self.window)
            self._control_center_dialog = dialog
            try:
                dialog.exec()
            finally:
                self._control_center_dialog = None
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to open Control Center")

    def _apply_routing_to_chat(self) -> None:
        routing = {
            "default_chat": self.store.setting("routing_default_chat", "") or "",
            "vision": self.store.setting("routing_vision", "") or "",
            "image_prompt": self.store.setting("routing_image_prompt", "") or "",
            "tool_routing": self.store.setting("routing_tool_routing", "") or "",
        }
        self.chat.update_routing(routing)
    def _delete_all_chats(self) -> None:
        if self._confirm("Are you sure you want to delete ALL chats? This cannot be undone."):
            for c in self.store.conversations(): self.store.delete_conversation(c.id)
            self.new_chat()

    def _toggle_web_header(self) -> None:
        current = bool(self.active_conversation.web_enabled) if self.active_conversation else self.web_enabled
        self._set_web(not current)

    def _set_web(self, enabled: bool) -> None:
        if self.active_conversation:
            self._set_active_conversation_web(enabled)
        else:
            self.web_enabled = enabled
            self.store.set_setting("web_enabled", enabled)
        self._apply_web_ui(enabled)

    def _apply_web_ui(self, enabled: bool) -> None:
        """Synchronize the two existing Web affordances without writing globals."""
        self.tools.web_enabled = enabled
        if hasattr(self, 'web_btn') and self.web_btn:
            self.web_btn.blockSignals(True)
            self.web_btn.setChecked(enabled)
            self.web_btn.blockSignals(False)
        if hasattr(self, 'web_status_btn') and self.web_status_btn:
            self.web_status_btn.setText("Web ON" if enabled else "Web OFF")
            self.web_status_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.theme.ACCENT if enabled else self.theme.BORDER};
                    color: {self.theme.BG if enabled else self.theme.TEXT};
                    border: none;
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-weight: 600;
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: {self.theme.HOVER if not enabled else "#0e8c6d"};
                }}
            """)
            from friday.icons import get_icon
            self.web_status_btn.setIcon(get_icon("globe", self.theme.BG if enabled else self.theme.TEXT, 16))
            self.web_status_btn.setToolTip("Web tools enabled for this conversation" if enabled else "Web tools disabled for this conversation")

    def _set_theme(self, light: bool) -> None:
        self.is_light_mode = light; self.store.set_setting("light_mode", light); self.apply_theme()

    def install_model(self, model_name: str, dialog: QDialog) -> None:
        model_name = model_name.strip()
        if not model_name: return
        def work() -> None:
            try: self.provider.pull(model_name, lambda status: None); self.bridge.event.emit("models", "")
            except Exception as error: self.bridge.event.emit("error", f"Could not install {model_name}: {error}")
        threading.Thread(target=work, daemon=True).start(); dialog.accept()

    def remove_selected_model(self, listbox: QListWidget, dialog: QDialog) -> None:
        index = listbox.currentRow()
        if index < 0: return
        model = self.models[index]
        if not self._confirm(f"Remove {model.name}?"): return
        def work() -> None:
            try: self.provider.delete(model.name); self.bridge.event.emit("models", "")
            except Exception as error: self.bridge.event.emit("error", f"Could not remove {model.name}: {error}")
        threading.Thread(target=work, daemon=True).start(); dialog.accept()
