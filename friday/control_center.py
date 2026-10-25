import os
import sys
import json
import shutil
import platform
import urllib.request
import threading
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QListWidget, QStackedWidget,
    QLabel, QPushButton, QFrame, QCheckBox, QLineEdit, QListWidgetItem, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QCursor

class UpdateChecker(QObject):
    finished = Signal(dict)

    def check_updates(self):
        def work():
            results = {}
            results["python"] = {"installed": sys.version.split()[0], "latest": "Unknown", "status": "Check unavailable"}

            try:
                import PySide6
                results["pyside6"] = {"installed": PySide6.__version__}
                req = urllib.request.Request("https://pypi.org/pypi/PySide6/json")
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = json.loads(r.read())
                    latest = data["info"]["version"]
                    results["pyside6"]["latest"] = latest
                    results["pyside6"]["status"] = "Update available" if latest != PySide6.__version__ else "Up to date"
            except Exception as e:
                results["pyside6"] = {"installed": getattr(PySide6, "__version__", "Unknown"), "latest": "Unknown", "status": f"Error: {e}"}

            try:
                req = urllib.request.Request("http://127.0.0.1:11434/api/version")
                with urllib.request.urlopen(req, timeout=2) as r:
                    installed = json.loads(r.read())["version"].lstrip("v")
                    results["ollama"] = {"installed": installed}
            except Exception:
                results["ollama"] = {"installed": "Not Running", "latest": "Unknown", "status": "Check unavailable"}

            if "ollama" in results and results["ollama"]["installed"] != "Not Running":
                try:
                    req = urllib.request.Request("https://api.github.com/repos/ollama/ollama/releases/latest", headers={"User-Agent": "FRIDAY-Agent"})
                    with urllib.request.urlopen(req, timeout=5) as r:
                        latest = json.loads(r.read())["tag_name"].lstrip("v")
                        results["ollama"]["latest"] = latest
                        results["ollama"]["status"] = "Update available" if latest != results["ollama"]["installed"] else "Up to date"
                except Exception:
                    results["ollama"]["latest"] = "Unknown"
                    results["ollama"]["status"] = "Error checking"

            self.finished.emit(results)
        threading.Thread(target=work, daemon=True).start()

class ControlCenterDialog(QDialog):
    def __init__(self, app_instance, parent=None):
        super().__init__(parent)
        self.app = app_instance
        self.theme = app_instance.theme
        self.setWindowTitle("FRIDAY CONTROL CENTER")
        self.resize(800, 550)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setObjectName("controlCenter"); self.setStyleSheet(f"#controlCenter {{ background-color: {self.theme.BG}; border: 1px solid {self.theme.BORDER}; }}"); self.setAutoFillBackground(True)

        self.checker = UpdateChecker()
        self.checker.finished.connect(self._on_updates_checked)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        header = QWidget()
        header.setStyleSheet(f"background-color: {self.theme.PANEL}; border-bottom: 1px solid {self.theme.BORDER};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel("⚙ FRIDAY CONTROL CENTER")
        title.setStyleSheet(f"color: {self.theme.TEXT}; font-weight: bold; font-size: 14px; letter-spacing: 1px;")
        h_layout.addWidget(title)
        h_layout.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {self.theme.MUTED}; font-weight: bold; }} QPushButton:hover {{ color: #ef4444; }}")
        close_btn.clicked.connect(self.accept)
        h_layout.addWidget(close_btn)
        main_layout.addWidget(header)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.setStyleSheet(f"""
            QListWidget {{ background-color: {self.theme.SIDEBAR}; border: none; border-right: 1px solid {self.theme.BORDER}; outline: none; padding: 10px 0; }}
            QListWidget::item {{ color: {self.theme.MUTED}; padding: 12px 20px; font-weight: bold; font-size: 13px; }}
            QListWidget::item:hover {{ color: {self.theme.TEXT}; background-color: {self.theme.HOVER}; }}
            QListWidget::item:selected {{ color: {self.theme.TEXT}; background-color: {self.theme.SELECTED}; border-left: 3px solid {self.theme.TEXT}; padding-left: 17px; }}
        """)

        sections = [
            "🤖 AI & Models",
            "⚙ Model Instructions",
            "🌐 Internet & Media",
            "🖼️ Image Intelligence",
            "🎙️ Voice",
            "🧠 Memory",
            "📁 Files & Workspace",
            "🛠 Tools",
            "🛠️ Tools & Updates",
            "⚙️ System"
        ]
        self.sidebar.addItems(sections)
        self.sidebar.currentRowChanged.connect(self._change_page)
        body_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        body_layout.addWidget(self.stack, 1)

        self.stack.addWidget(self._build_ai_models())
        self.stack.addWidget(self._build_model_instructions())
        self.stack.addWidget(self._build_internet())
        self.stack.addWidget(self._build_image_ai())
        self.stack.addWidget(self._build_voice())
        self.stack.addWidget(self._build_memory())
        self.stack.addWidget(self._build_files())
        self.stack.addWidget(self._build_permissions())
        self.stack.addWidget(self._build_tool_registry())
        self.stack.addWidget(self._build_tools())
        self.stack.addWidget(self._build_system())

        main_layout.addLayout(body_layout, 1)
        self.sidebar.setCurrentRow(0)

    def _change_page(self, index):
        self.stack.setCurrentIndex(index)

    def _create_panel(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        header = QLabel(title)
        header.setStyleSheet(f"color: {self.theme.TEXT}; font-size: 18px; font-weight: bold;")
        layout.addWidget(header)
        return page, layout

    def _create_card(self, layout):
        card = QFrame()
        card.setStyleSheet(f"background-color: {self.theme.PANEL}; border: 1px solid {self.theme.BORDER}; border-radius: 8px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(15)
        layout.addWidget(card)
        return card, card_layout

    def _label(self, text, color=None, bold=False):
        lbl = QLabel(text)
        c = color or self.theme.TEXT
        w = "bold" if bold else "normal"
        lbl.setStyleSheet(f"color: {c}; font-weight: {w};")
        lbl.setWordWrap(True)
        return lbl

    def _button(self, text, callback, accent=False, danger=False):
        btn = QPushButton(text)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if danger:
            btn.setStyleSheet(f"QPushButton {{ background-color: transparent; border: 1px solid #ef4444; border-radius: 6px; color: #ef4444; padding: 6px 12px; font-weight: bold; }} QPushButton:hover {{ background-color: #ef4444; color: white; }}")
        elif accent:
            btn.setStyleSheet(f"QPushButton {{ background-color: {self.theme.TEXT}; border: none; border-radius: 6px; color: {self.theme.BG}; padding: 6px 12px; font-weight: bold; }}")
        else:
            btn.setStyleSheet(f"QPushButton {{ background-color: {self.theme.BORDER}; border: none; border-radius: 6px; color: {self.theme.TEXT}; padding: 6px 12px; font-weight: bold; }} QPushButton:hover {{ background-color: {self.theme.HOVER}; }}")
        btn.clicked.connect(callback)
        return btn

    def _build_ai_models(self):
        page, layout = self._create_panel("AI & Models")
        card, c_layout = self._create_card(layout)

        active_model = self.app.model_picker.currentText()
        c_layout.addWidget(self._label(f"Active Selected Model: {active_model}", bold=True))
        c_layout.addWidget(self._label("You can quickly switch active models from the dropdown in the main chat bar.", color=self.theme.MUTED))

        c_layout.addWidget(self._label("\nInstalled Local Models", bold=True))
        self.model_list = QListWidget()
        self.model_list.setStyleSheet(f"background-color: {self.theme.BG}; border: 1px solid {self.theme.BORDER}; border-radius: 4px; color: {self.theme.TEXT}; padding: 4px;")
        self._populate_models()
        c_layout.addWidget(self.model_list, 1)

        actions = QHBoxLayout()
        self.install_input = QLineEdit()
        self.install_input.setPlaceholderText("Model to pull (e.g. qwen2.5:7b)")
        self.install_input.setStyleSheet(f"background-color: {self.theme.BG}; border: 1px solid {self.theme.BORDER}; border-radius: 4px; color: {self.theme.TEXT}; padding: 6px;")
        actions.addWidget(self.install_input, 1)
        actions.addWidget(self._button("Pull / Install", self._do_install, accent=True))
        actions.addWidget(self._button("Rename Selected", self._do_rename, accent=False))
        actions.addWidget(self._button("Remove Selected", self._do_remove, danger=True))
        c_layout.addLayout(actions)
        layout.addStretch(1)
        return page

    def _populate_models(self):
        self.model_list.clear()
        for m in self.app.models:
            from PySide6.QtWidgets import QListWidgetItem
            from PySide6.QtCore import Qt
            disp = f"{m.display_name} (Internal: {m.name})  —  {m.size_label}"
            item = QListWidgetItem(disp)
            item.setData(Qt.ItemDataRole.UserRole, m.name)
            self.model_list.addItem(item)

    def _do_install(self):
        self.app.install_model(self.install_input.text(), self)

    def _do_remove(self):
        self.app.remove_selected_model(self.model_list, self)

    def _do_rename(self):
        item = self.model_list.currentItem()
        if not item: return
        from PySide6.QtCore import Qt
        internal_id = item.data(Qt.ItemDataRole.UserRole)
        if not internal_id: return

        current_display = self.app._get_model_display_name(internal_id)
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Model",
            f"Enter new display name for:\n{internal_id}",
            text=current_display
        )
        if ok and new_name.strip():
            aliases = self.app._get_model_aliases()
            aliases[internal_id] = new_name.strip()
            import json
            self.app.store.set_setting("model_aliases", json.dumps(aliases))

            self.app.refresh_models()

            self.app.models = self.app.provider.available_models(aliases=aliases)
            self._populate_models()

            for i in range(self.model_list.count()):
                if self.model_list.item(i).data(Qt.ItemDataRole.UserRole) == internal_id:
                    self.model_list.setCurrentRow(i)
                    break

    def _build_internet(self):
        page, layout = self._create_panel("Internet & Media")
        card, c_layout = self._create_card(layout)

        web_check = QCheckBox("Enable Web Tools (Search, Media Fetching)")
        web_check.setStyleSheet(f"color: {self.theme.TEXT};")
        web_check.setChecked(self.app.web_enabled)
        web_check.toggled.connect(self.app._set_web)
        c_layout.addWidget(web_check)

        c_layout.addWidget(self._label("Incognito Mode and Media embedding are actively configured in the chat UI.", color=self.theme.MUTED))

        c_layout.addWidget(self._label("\nWeb Agent (Phase 6C):", bold=True))
        c_layout.addWidget(self._label("● Enabled", color="#10b981", bold=True))
        c_layout.addWidget(self._label("Search: Enabled\nPage Reading: Enabled\nResearch Mode: Enabled\nMaximum sources: 2", color=self.theme.MUTED))

        c_layout.addWidget(self._label("\nCapabilities:", bold=True))
        c_layout.addWidget(self._label("Image Search: Available (via DDGS)\nVideo Search: Available (via DDGS)\nEmbedded Media: Supported", color=self.theme.MUTED))
        layout.addStretch(1)
        return page

    def _build_image_ai(self):
        from PySide6.QtWidgets import QComboBox, QScrollArea
        page, layout = self._create_panel("Image Intelligence")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        sc_layout = QVBoxLayout(content)
        sc_layout.setContentsMargins(0, 0, 8, 0)
        sc_layout.setSpacing(16)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self._routing_combos = {}

        def add_route(title, description, key, automatic=False):
            _, card_layout = self._create_card(sc_layout)
            card_layout.addWidget(self._label(title, bold=True))
            card_layout.addWidget(self._label(description, color=self.theme.MUTED))
            combo = QComboBox()
            combo.setStyleSheet(
                f"QComboBox {{ background: {self.theme.BG}; color: {self.theme.TEXT}; padding: 6px 10px; "
                f"border: 1px solid {self.theme.BORDER}; border-radius: 4px; min-width: 200px; }}"
            )
            combo.addItem("— Automatic (FRIDAY Auto) —" if automatic else "— Select Model —", "")
            for model in self.app.models:
                combo.addItem(f"{model.display_name}  ({model.name})", model.name)
            saved = self.app.store.setting(key, "") or ""
            if saved:
                idx = combo.findData(saved)
                if idx < 0:
                    combo.addItem(f"{saved} (not installed)", saved)
                    idx = combo.count() - 1
                combo.setCurrentIndex(idx)
            card_layout.addWidget(combo)
            status = self._label("", color=self.theme.MUTED)
            card_layout.addWidget(status)
            self._routing_combos[key] = (combo, automatic, status)

            def changed():
                value = combo.currentData() or ""
                self.app.store.set_setting(key, value)
                self._apply_routing_to_engine()
                status.setText(f"Saved: {value}" if value else f"Using {'FRIDAY Auto' if automatic else 'automatic fallback'}")

            combo.currentIndexChanged.connect(changed)
            status.setText(f"Saved: {saved}" if saved else f"Using {'FRIDAY Auto' if automatic else 'automatic fallback'}")

        add_route("Default Chat Model", "Used for ordinary chat when FRIDAY Auto is selected.", "routing_default_chat", True)
        add_route("Vision / Image Analysis Model", "Model used to inspect attached images. Choose an installed vision-capable model.", "routing_vision")
        add_route("Image Prompt Generation Model", "Model used for /prompt and image-to-prompt requests.", "routing_image_prompt")
        add_route("Capability / Tool Routing Model", "Optional model selection for capability and tool routing.", "routing_tool_routing")
        sc_layout.addStretch(1)
        return page

    def refresh_routing_models(self):
        for key, (combo, automatic, status) in getattr(self, "_routing_combos", {}).items():
            saved = self.app.store.setting(key, "") or ""
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— Automatic (FRIDAY Auto) —" if automatic else "— Select Model —", "")
            for model in self.app.models:
                combo.addItem(f"{model.display_name}  ({model.name})", model.name)
            selected = combo.findData(saved)
            if selected < 0 and saved:
                combo.addItem(f"{saved} (not installed)", saved)
                selected = combo.count() - 1
            combo.setCurrentIndex(max(0, selected))
            combo.blockSignals(False)
            status.setText(f"Saved: {saved}" if saved else f"Using {'FRIDAY Auto' if automatic else 'automatic fallback'}")

    def _apply_routing_to_engine(self):
        routing = {
            "default_chat": self.app.store.setting("routing_default_chat", "") or "",
            "vision": self.app.store.setting("routing_vision", "") or "",
            "image_prompt": self.app.store.setting("routing_image_prompt", "") or "",
            "tool_routing": self.app.store.setting("routing_tool_routing", "") or "",
        }
        if hasattr(self.app, "chat") and hasattr(self.app.chat, "update_routing"):
            self.app.chat.update_routing(routing)

    def _build_voice(self):
        from PySide6.QtWidgets import QComboBox, QSlider
        page, layout = self._create_panel("Voice Configuration")
        card, c_layout = self._create_card(layout)

        c_layout.addWidget(self._label("Speech-to-Text (STT)", bold=True))
        c_layout.addWidget(self._label("Engine: faster-whisper | Model: base", color=self.theme.MUTED))

        c_layout.addWidget(self._label("\nText-to-Speech (TTS)", bold=True))

        h1 = QHBoxLayout()
        h1.addWidget(self._label("Engine:"))
        self.tts_engine = QComboBox()
        self.tts_engine.addItems(["Kokoro", "SAPI5"])
        h1.addWidget(self.tts_engine)
        c_layout.addLayout(h1)

        h2 = QHBoxLayout()
        h2.addWidget(self._label("Voice Pack:"))
        self.tts_pack = QComboBox()
        self.tts_pack.addItems(["Cinematic", "Velvet", "Tactical", "Classic"])
        h2.addWidget(self.tts_pack)
        c_layout.addLayout(h2)

        h3 = QHBoxLayout()
        h3.addWidget(self._label("Speed:"))
        self.tts_speed = QSlider(Qt.Orientation.Horizontal)
        self.tts_speed.setRange(5, 20)
        self.tts_speed.setValue(10)
        h3.addWidget(self.tts_speed)
        c_layout.addLayout(h3)

        c_layout.addWidget(self._label("Pitch / Expression: Not supported by current engine natively.", color=self.theme.MUTED))

        test_btn = self._button("TEST VOICE", self._test_voice, accent=True)
        c_layout.addWidget(test_btn)

        self.tts_preview_status = self._label("", color=self.theme.MUTED)
        c_layout.addWidget(self.tts_preview_status)

        self.tts_engine.currentTextChanged.connect(self._save_voice_config)
        self.tts_pack.currentTextChanged.connect(self._save_voice_config)
        self.tts_speed.valueChanged.connect(self._save_voice_config)

        eng = self.app.store.setting("tts_engine", "SAPI5")
        if eng == "Kokoro": self.tts_engine.setCurrentIndex(0)
        else: self.tts_engine.setCurrentIndex(1)

        pack = self.app.store.setting("tts_pack", "Cinematic")
        idx = self.tts_pack.findText(pack)
        if idx >= 0: self.tts_pack.setCurrentIndex(idx)

        speed = self.app.store.setting("tts_speed", 1.0)
        self.tts_speed.setValue(int(speed * 10))

        layout.addStretch(1)
        return page

    def _save_voice_config(self):
        engine = self.tts_engine.currentText()
        pack = self.tts_pack.currentText()
        speed = self.tts_speed.value() / 10.0
        self.app.store.set_setting("tts_engine", engine)
        self.app.store.set_setting("tts_pack", pack)
        self.app.store.set_setting("tts_speed", speed)

    def _test_voice(self):
        self.tts_preview_status.setText("Initializing TTS Engine...")
        engine = self.tts_engine.currentText()
        pack = self.tts_pack.currentText()
        speed = self.tts_speed.value() / 10.0

        def work():
            from friday.tts import TTSManager
            from friday.config import AppPaths
            mgr = TTSManager(AppPaths().data_dir)
            mgr.set_config(engine, pack, speed)
            if engine == "Kokoro" and mgr.engine_name != "Kokoro":
                self.tts_preview_status.setText("Kokoro unavailable. Missing kokoro-onnx, soundfile, or model files.")
            else:
                self.tts_preview_status.setText(f"Speaking with {mgr.engine_name}...")
                mgr.speak("Systems online. I'm ready.", on_stop=lambda: self.tts_preview_status.setText("Preview finished."))
                import time
                time.sleep(3)
                mgr.stop()
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _build_memory(self):
        page, layout = self._create_panel("Memory")
        card, c_layout = self._create_card(layout)

        db_path = getattr(self.app.store, "db_path", "friday.db")
        size_mb = os.path.getsize(db_path) / (1024*1024) if os.path.exists(db_path) else 0

        stats = self.app.store.get_memory_stats() if hasattr(self.app.store, 'get_memory_stats') else {"total": 0, "categories": {}}
        c_layout.addWidget(self._label(f"Database: {db_path}\nSize: {size_mb:.2f} MB", color=self.theme.MUTED))
        c_layout.addWidget(self._label(f"Total Memories: {stats['total']}", bold=True))
        if stats['categories']:
            cats = "\n".join(f"• {k}: {v}" for k, v in stats['categories'].items())
            c_layout.addWidget(self._label(cats, color=self.theme.MUTED))

        c_layout.addWidget(self._label("\nManagement", bold=True))
        c_layout.addWidget(self._button("Delete All Chats", self.app._delete_all_chats, danger=True))
        c_layout.addWidget(self._label("Destructive action. Wipes all conversations permanently.", color=self.theme.MUTED))

        layout.addStretch(1)
        return page




    def _build_permissions(self):
        page, layout = self._create_panel("Permissions & Access")
        from PySide6.QtWidgets import QHBoxLayout, QFileDialog
        from friday.permission_manager import engine

        card_f, cf_layout = self._create_card(layout)
        cf_layout.addWidget(self._label("FILES & FOLDER ACCESS", bold=True))
        from friday.permission_manager import DEFAULT_ALLOWED_FOLDER
        cf_layout.addWidget(self._label(f"{DEFAULT_ALLOWED_FOLDER} is allowed by default and cannot be removed.", color=self.theme.MUTED))

        self.folder_list_layout = QVBoxLayout()
        cf_layout.addLayout(self.folder_list_layout)

        add_f_btn = self._button("+ Add Folder", self._ui_add_folder, accent=True)
        cf_layout.addWidget(add_f_btn)

        card_a, ca_layout = self._create_card(layout)
        ca_layout.addWidget(self._label("APPLICATION ACCESS", bold=True))
        ca_layout.addWidget(self._label("Allow FRIDAY to launch specific applications.", color=self.theme.MUTED))

        self.app_list_layout = QVBoxLayout()
        ca_layout.addLayout(self.app_list_layout)

        add_a_btn = self._button("+ Add Application", self._ui_add_app, accent=True)
        ca_layout.addWidget(add_a_btn)

        layout.addStretch(1)
        self._refresh_permissions_ui()
        return page

    def _refresh_permissions_ui(self):
        from friday.permission_manager import engine
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
        from PySide6.QtCore import Qt

        while self.folder_list_layout.count():
            item = self.folder_list_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        folders = engine.get_custom_folders()
        for f in folders:
            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(0, 0, 0, 0)
            l.addWidget(self._label(f"✓ {f}"))
            rem = QPushButton("Remove")
            rem.setStyleSheet(f"background-color: transparent; color: {self.theme.TEXT}; border: 1px solid {self.theme.BORDER}; border-radius: 4px; padding: 4px 8px;")
            rem.clicked.connect(lambda checked, path=f: self._ui_remove_folder(path))
            l.addWidget(rem, 0, Qt.AlignmentFlag.AlignRight)
            self.folder_list_layout.addWidget(w)

        while self.app_list_layout.count():
            item = self.app_list_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        apps = engine.get_custom_apps()
        for app_name, app_path in apps.items():
            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(0, 0, 0, 0)
            l.addWidget(self._label(f"✓ {app_name.capitalize()}"))
            rem = QPushButton("Remove")
            rem.setStyleSheet(f"background-color: transparent; color: {self.theme.TEXT}; border: 1px solid {self.theme.BORDER}; border-radius: 4px; padding: 4px 8px;")
            rem.clicked.connect(lambda checked, name=app_name: self._ui_remove_app(name))
            l.addWidget(rem, 0, Qt.AlignmentFlag.AlignRight)
            self.app_list_layout.addWidget(w)

    def _ui_add_folder(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from friday.permission_manager import engine
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Allow Access")
        if folder:
            if not engine.add_folder(folder):
                QMessageBox.warning(self, "Invalid Folder", "Cannot add this folder. System drives (C:\\) and unsafe paths are blocked.")
            self._refresh_permissions_ui()

    def _ui_remove_folder(self, path):
        from friday.permission_manager import engine
        engine.remove_folder(path)
        self._refresh_permissions_ui()

    def _ui_add_app(self):
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        from friday.permission_manager import engine
        path, _ = QFileDialog.getOpenFileName(self, "Select Application Executable", "", "Executables (*.exe *.com *.bat *.cmd)")
        if path:
            name, ok = QInputDialog.getText(self, "Application Name", "Enter a friendly name for this app (e.g. Steam):")
            if ok and name.strip():
                engine.add_app(name.strip(), path)
                self._refresh_permissions_ui()

    def _ui_remove_app(self, name):
        from friday.permission_manager import engine
        engine.remove_app(name)
        self._refresh_permissions_ui()

    def _build_files(self):
        page, layout = self._create_panel("Files & Workspace")
        card, c_layout = self._create_card(layout)

        c_layout.addWidget(self._label("Allowed Workspace Root", bold=True))
        from friday.permission_manager import DEFAULT_ALLOWED_FOLDER
        c_layout.addWidget(self._label(str(DEFAULT_ALLOWED_FOLDER), color=self.theme.PRIMARY if hasattr(self.theme, 'PRIMARY') else self.theme.ACCENT, bold=True))

        c_layout.addWidget(self._label("\nStatus:", bold=True))
        c_layout.addWidget(self._label("● Protected", color="#10b981", bold=True))

        c_layout.addWidget(self._label("\nCapabilities:", bold=True))
        c_layout.addWidget(self._label("• File Search\n• Directory Listing\n• Document & PDF Reading\n• Image Discovery\n• Safe File Opening", color=self.theme.MUTED))

        layout.addStretch(1)
        return page

    def _build_tool_registry(self):
        from PySide6.QtWidgets import QScrollArea, QFrame, QHBoxLayout, QGridLayout
        from PySide6.QtCore import Qt

        page, layout = self._create_panel("Tool Registry")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 10, 0)
        c_layout.setSpacing(15)

        tools_list = list(self.app.tools.registry.values())
        tools_list.sort(key=lambda t: (t.category, t.name))

        current_cat = None
        for t in tools_list:
            if t.category != current_cat:
                current_cat = t.category
                cat_lbl = self._label(f"\n{current_cat.upper()}", bold=True)
                cat_lbl.setStyleSheet(f"color: {self.theme.TEXT}; font-size: 14px; font-weight: bold;")
                c_layout.addWidget(cat_lbl)

            card = QFrame()
            card.setStyleSheet(f"background-color: {self.theme.PANEL}; border: 1px solid {self.theme.BORDER}; border-radius: 8px;")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 15, 15, 15)
            card_layout.setSpacing(8)

            header_layout = QHBoxLayout()
            name_lbl = self._label(t.name, bold=True)
            name_lbl.setStyleSheet(f"color: {self.theme.TEXT}; font-size: 15px; font-weight: bold;")
            header_layout.addWidget(name_lbl)

            header_layout.addStretch(1)
            status_lbl = self._label("● Enabled (Managed by FRIDAY)", color="#10b981", bold=True)
            header_layout.addWidget(status_lbl)
            card_layout.addLayout(header_layout)

            desc_lbl = self._label(t.description, color=self.theme.MUTED)
            desc_lbl.setWordWrap(True)
            card_layout.addWidget(desc_lbl)

            meta_layout = QHBoxLayout()

            inet_color = "#ef4444" if t.requires_internet else "#10b981"
            inet_text = "Required" if t.requires_internet else "No"
            meta_layout.addWidget(self._label("Internet: ", color=self.theme.MUTED))
            meta_layout.addWidget(self._label(inet_text, color=inet_color, bold=True))

            meta_layout.addSpacing(20)

            conf_color = "#f59e0b" if t.requires_confirmation else "#10b981"
            conf_text = "Required" if t.requires_confirmation else "No"
            meta_layout.addWidget(self._label("Confirmation: ", color=self.theme.MUTED))
            meta_layout.addWidget(self._label(conf_text, color=conf_color, bold=True))

            meta_layout.addStretch(1)
            card_layout.addLayout(meta_layout)

            c_layout.addWidget(card)

        c_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)
        return page

    def _build_tools(self):
        page, layout = self._create_panel("Tools & Updates")
        card, self.tools_layout = self._create_card(layout)

        self.tools_layout.addWidget(self._label("FRIDAY Tool Checker", bold=True))
        self.check_btn = self._button("Check for Updates", self._run_update_check, accent=True)
        self.tools_layout.addWidget(self.check_btn)

        self.updates_container = QWidget()
        self.updates_vbox = QVBoxLayout(self.updates_container)
        self.updates_vbox.setContentsMargins(0, 10, 0, 0)
        self.updates_vbox.setSpacing(10)
        self.tools_layout.addWidget(self.updates_container)

        self.updates_vbox.addWidget(self._label("Click to query latest versions.", color=self.theme.MUTED))

        layout.addStretch(1)
        return page

    def _run_update_check(self):
        self.check_btn.setEnabled(False)
        self.check_btn.setText("Checking...")
        while self.updates_vbox.count():
            item = self.updates_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.checker.check_updates()

    def _on_updates_checked(self, results):
        self.check_btn.setEnabled(True)
        self.check_btn.setText("Check for Updates")

        for tool, data in results.items():
            row = QHBoxLayout()
            name_lbl = self._label(tool.upper(), bold=True)
            name_lbl.setFixedWidth(100)
            row.addWidget(name_lbl)

            inst_lbl = self._label(f"Inst: {data.get('installed', 'N/A')}")
            inst_lbl.setFixedWidth(120)
            row.addWidget(inst_lbl)

            latest_lbl = self._label(f"Latest: {data.get('latest', 'N/A')}", color=self.theme.MUTED)
            latest_lbl.setFixedWidth(120)
            row.addWidget(latest_lbl)

            status = data.get('status', '')
            col = "#10b981" if "Up to date" in status else "#f59e0b" if "Update" in status else self.theme.MUTED
            stat_lbl = self._label(status, color=col, bold=True)
            row.addWidget(stat_lbl)

            if tool == "ollama" and "Update available" in status:
                link = self._label("<a href='https://ollama.com/download' style='color:#3b82f6;'>Download Installer</a>")
                link.setOpenExternalLinks(True)
                row.addWidget(link)
            else:
                row.addStretch(1)

            self.updates_vbox.addLayout(row)

        models_lbl = self._label("\nLocal Models (Ollama)", bold=True)
        self.updates_vbox.addWidget(models_lbl)
        for m in self.app.models:
            row = QHBoxLayout()
            row.addWidget(self._label(m.name))
            row.addStretch(1)
            row.addWidget(self._label("Installed", color="#10b981"))
            self.updates_vbox.addLayout(row)

    def _build_system(self):
        page, layout = self._create_panel("System & Diagnostics")
        card, c_layout = self._create_card(layout)

        sys_info = [
            f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
            f"Python: {sys.version.split()[0]}",
            f"Logical CPUs: {os.cpu_count() or 'Unknown'}"
        ]

        path = getattr(self.app.store, "db_path", ".")
        try:
            total, used, free = shutil.disk_usage(os.path.dirname(os.path.abspath(path)))
            sys_info.append(f"Disk Free: {free // (2**30)} GB / {total // (2**30)} GB")
        except Exception:
            pass

        for s in sys_info:
            c_layout.addWidget(self._label(s))

        c_layout.addWidget(self._label("\nOllama Daemon", bold=True))

        daemon_stat = "Not running"
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/version")
            with urllib.request.urlopen(req, timeout=1) as r:
                ver = json.loads(r.read())["version"]
                daemon_stat = f"Running (v{ver})"
        except Exception:
            pass

        c_layout.addWidget(self._label(f"Status: {daemon_stat}", color="#10b981" if "Running" in daemon_stat else "#ef4444"))

        c_layout.addWidget(self._label("\nAppearance", bold=True))
        light_check = QCheckBox("Use Light Mode")
        light_check.setStyleSheet(f"color: {self.theme.TEXT};")
        light_check.setChecked(self.app.is_light_mode)
        light_check.toggled.connect(self._toggle_theme)
        c_layout.addWidget(light_check)

        layout.addStretch(1)
        return page

    def _toggle_theme(self, checked):
        self.app._set_theme(checked)

    def _build_model_instructions(self):
        from PySide6.QtWidgets import QComboBox, QTextEdit, QHBoxLayout
        page, layout = self._create_panel("Model Instructions")
        card, c_layout = self._create_card(layout)

        c_layout.addWidget(self._label("Customize the system instructions for each FRIDAY persona.", color=self.theme.MUTED))
        c_layout.addWidget(self._label("Model:", bold=True))

        self.inst_model_combo = QComboBox()
        self.inst_model_combo.setStyleSheet(f"background: {self.theme.BG}; color: {self.theme.TEXT}; padding: 6px; border: 1px solid {self.theme.BORDER}; border-radius: 4px;")

        self.inst_model_combo.addItem("FRIDAY Auto", "FRIDAY Auto")
        for m in self.app.models:
            self.inst_model_combo.addItem(m.display_name, m.name)

        c_layout.addWidget(self.inst_model_combo)

        c_layout.addWidget(self._label("Instructions:", bold=True))

        self.inst_editor = QTextEdit()
        self.inst_editor.setStyleSheet(f"background: {self.theme.BG}; color: {self.theme.TEXT}; padding: 8px; border: 1px solid {self.theme.BORDER}; border-radius: 4px;")
        c_layout.addWidget(self.inst_editor, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(self._button("Reset to Default", self._reset_instruction))
        btn_layout.addWidget(self._button("Save", self._save_instruction, accent=True))
        c_layout.addLayout(btn_layout)

        self.inst_model_combo.currentIndexChanged.connect(lambda: self._load_instruction())
        self._load_instruction()

        layout.addStretch(1)
        return page

    def _load_instruction(self):
        model_id = self.inst_model_combo.currentData()
        if not model_id: return
        custom = self.app.store.setting(f"inst_{model_id}", "")
        if custom:
            self.inst_editor.setPlainText(custom)
        else:
            try:
                from friday.instruction_defaults import INSTRUCTION_DEFAULTS
                self.inst_editor.setPlainText(INSTRUCTION_DEFAULTS.get(model_id, ""))
            except ImportError:
                pass

    def _save_instruction(self):
        model_id = self.inst_model_combo.currentData()
        if not model_id: return

        text = self.inst_editor.toPlainText().strip()
        try:
            from friday.instruction_defaults import INSTRUCTION_DEFAULTS
            default = INSTRUCTION_DEFAULTS.get(model_id, "").strip()
        except ImportError:
            default = ""

        if text == default or not text:
            self.app.store.set_setting(f"inst_{model_id}", "")
            self.inst_editor.setPlainText(default)
        else:
            self.app.store.set_setting(f"inst_{model_id}", text)

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Saved", f"Instructions saved.")

    def _reset_instruction(self):
        model_id = self.inst_model_combo.currentData()
        if not model_id: return
        self.app.store.set_setting(f"inst_{model_id}", "")
        self._load_instruction()
