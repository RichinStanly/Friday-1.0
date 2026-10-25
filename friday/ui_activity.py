from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton
from PySide6.QtCore import Qt
from friday.icons import get_icon
import time

class ActivityWidget(QFrame):
    def __init__(self, theme, model_display="", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.model_display = model_display
        self.setObjectName("activityWidget")
        self.setStyleSheet(f"""
            #activityWidget {{
                background-color: {theme.PANEL};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
            }}
        """)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.header_btn = QPushButton()
        self.header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_btn.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                background: transparent;
                border: none;
                padding: 8px 12px;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: {theme.HOVER};
            }}
        """)
        self.header_layout = QHBoxLayout(self.header_btn)
        self.header_layout.setContentsMargins(0,0,0,0)

        self.toggle_icon = QLabel()
        self.toggle_icon.setPixmap(get_icon("chevron-down", theme.MUTED, 16).pixmap(16, 16))
        self.header_layout.addWidget(self.toggle_icon)

        self.title_lbl = QLabel("Activity")
        self.title_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; font-weight: 500;")
        self.header_layout.addWidget(self.title_lbl)
        self.header_layout.addStretch(1)

        self.header_btn.clicked.connect(self.toggle_expanded)
        self.main_layout.addWidget(self.header_btn)

        self.details_container = QWidget()
        self.details_layout = QVBoxLayout(self.details_container)
        self.details_layout.setContentsMargins(32, 0, 12, 12)
        self.details_layout.setSpacing(6)

        self.steps = []
        self.main_layout.addWidget(self.details_container)

        self.expanded = False
        self.details_container.hide()
        self.toggle_icon.setPixmap(get_icon("chevron-right", theme.MUTED, 16).pixmap(16, 16))

        self.start_time = time.time()

    def set_status(self, text: str):
        self.title_lbl.setText(f"Activity · {text}")
        lbl = QLabel(f"✓ {text}")
        lbl.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 12px;")
        self.details_layout.addWidget(lbl)
        self.steps.append(text)

    def complete(self, cancelled=False, error=False):
        duration = time.time() - self.start_time
        summary = "Activity"

        has_web = any("search" in s.lower() or "retrieved" in s.lower() for s in self.steps)
        has_img_search = any("image search" in s.lower() for s in self.steps)
        has_vision = any("vision" in s.lower() or "image" in s.lower() for s in self.steps) and not has_img_search

        if has_web:
            summary = f"Web · {self.model_display}"
        elif has_img_search:
            summary = f"Image Search · {self.model_display}"
        elif has_vision:
            summary = f"Vision · {self.model_display}"
        else:
            summary = f"Local · {self.model_display}"

        if cancelled:
            self.title_lbl.setText(f"Stopped · {summary} ({duration:.1f}s)")
            final_lbl = QLabel("× Generation stopped")
            final_lbl.setStyleSheet(f"color: {self.theme.DANGER}; font-size: 12px;")
        elif error:
            self.title_lbl.setText(f"Error · {summary} ({duration:.1f}s)")
            final_lbl = QLabel("× Request failed")
            final_lbl.setStyleSheet(f"color: {self.theme.DANGER}; font-size: 12px;")
        else:
            self.title_lbl.setText(f"{summary} ({duration:.1f}s)")
            final_lbl = QLabel("✓ Response generated")
            final_lbl.setStyleSheet(f"color: {self.theme.TEXT}; font-size: 12px;")

        self.details_layout.addWidget(final_lbl)

    def toggle_expanded(self):
        self.expanded = not self.expanded
        self.details_container.setVisible(self.expanded)
        icon_name = "chevron-down" if self.expanded else "chevron-right"
        self.toggle_icon.setPixmap(get_icon(icon_name, self.theme.MUTED, 16).pixmap(16, 16))
