import os
from PySide6.QtWidgets import (
    QPushButton, QLabel, QWidget, QHBoxLayout, QVBoxLayout,
    QFrame, QSizePolicy
)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPainterPath, QColor, QCursor
from PySide6.QtCore import Qt, Signal, Property, QPropertyAnimation, QEasingCurve, QSize
from friday.icons import get_icon

class IconButton(QPushButton):
    def __init__(self, icon_name: str, theme, parent=None, size=32, icon_size=20):
        super().__init__(parent)
        self.theme = theme
        self.icon_name = icon_name
        self.setFixedSize(size, size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_icon(self.theme.TEXT)

    def update_icon(self, color):
        self.setIcon(get_icon(self.icon_name, color, self.iconSize().width()))

class Avatar(QLabel):
    def __init__(self, text: str, theme, size=36, pic_path=None, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if pic_path:
            import os
            from PySide6.QtGui import QPixmap, QPainter, QPainterPath
            if os.path.exists(pic_path):
                from PySide6.QtGui import QImage, QImageReader
                reader = QImageReader(pic_path)
                reader.setAutoTransform(True)
                img = reader.read()
                if not img.isNull():
                    render_size = size * 3
                    scaled_img = img.scaled(render_size, render_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    target = QImage(render_size, render_size, QImage.Format.Format_ARGB32_Premultiplied)
                    target.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(target)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    path = QPainterPath()
                    path.addEllipse(0, 0, render_size, render_size)
                    painter.setClipPath(path)
                    x_offset = (render_size - scaled_img.width()) // 2
                    y_offset = (render_size - scaled_img.height()) // 2
                    painter.drawImage(x_offset, y_offset, scaled_img)
                    painter.end()
                    final_pixmap = QPixmap.fromImage(target)
                    final_pixmap.setDevicePixelRatio(3.0)
                    self.setPixmap(final_pixmap)
                return

        self.setText(text[0].upper() if text else "B")
        self.setStyleSheet(f"""
            background-color: {theme.AVATAR_BG};
            color: {theme.AVATAR_FG};
            border-radius: {size // 2}px;
            font-weight: bold;
            font-size: {size // 2}px;
        """)

class SuggestionCard(QFrame):
    clicked = Signal(str)
    def __init__(self, title: str, desc: str, icon_name: str, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.text = title
        self.setObjectName("suggestionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(240, 100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setStyleSheet("background: transparent; border: none;"); icon_lbl.setPixmap(get_icon(icon_name, theme.MUTED, 18).pixmap(18, 18))
        header.addWidget(icon_lbl)
        header.addStretch(1)
        layout.addLayout(header)

        layout.addStretch(1)

        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {theme.TEXT}; font-weight: bold; font-size: 13px; background: transparent; border: none;")
        layout.addWidget(lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(f"color: {theme.MUTED}; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(desc_lbl)

        self.setStyleSheet(f"""
            #suggestionCard {{
                background-color: {theme.PANEL};
                border: 1px solid {theme.BORDER};
                border-radius: 12px;
            }}
            #suggestionCard:hover {{
                border-color: {theme.ACCENT};
                background-color: {theme.HOVER};
            }}
        """)

    def mouseReleaseEvent(self, event):
        from PySide6.QtCore import Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.text)
        super().mouseReleaseEvent(event)

class AttachmentChip(QFrame):
    removed = Signal(str)
    def __init__(self, filename: str, filepath: str, theme, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.theme = theme
        self.setObjectName("attachmentChip")
        self.setStyleSheet(f"""
            #attachmentChip {{
                background-color: {theme.PANEL};
                border: 1px solid {theme.BORDER};
                border-radius: 6px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        icon_name = "image" if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')) else "file-text"
        icon_lbl = QLabel()
        icon_lbl.setStyleSheet("background: transparent; border: none;"); icon_lbl.setPixmap(get_icon(icon_name, theme.TEXT, 16).pixmap(16, 16))
        layout.addWidget(icon_lbl)

        name_lbl = QLabel(filename)
        name_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
        if len(filename) > 20:
            name_lbl.setText(filename[:17] + "...")
        layout.addWidget(name_lbl)

        close_btn = IconButton("x", theme, size=20, icon_size=14)
        close_btn.clicked.connect(lambda: self.removed.emit(self.filepath))
        layout.addWidget(close_btn)

class IconTextButton(QPushButton):
    def __init__(self, text: str, icon_name: str, theme, primary=False, parent=None):
        super().__init__(text, parent)
        self.theme = theme
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        bg_color = theme.ACCENT if primary else theme.BORDER
        text_color = theme.BG if primary else theme.TEXT

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: {text_color};
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme.HOVER if not primary else "#0e8c6d"};
            }}
        """)

        if icon_name:
            self.setIcon(get_icon(icon_name, text_color, 16))
