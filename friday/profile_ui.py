import os, shutil
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QFileDialog, QWidget)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor
from friday.icons import get_icon

def get_profile_data(store):
    name = store.setting("profile_name", "Boss")
    pic = store.setting("profile_pic", "")
    return name, pic

class ProfileDialog(QDialog):
    profile_updated = Signal(str, str)

    def __init__(self, store, theme, parent=None):
        super().__init__(parent)
        self.store = store
        self.theme = theme
        self.setObjectName("profileDialog")
        self.setStyleSheet(f"""
            #profileDialog, QWidget {{ background-color: {theme.BG}; color: {theme.TEXT}; }}
            QLineEdit {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; color: {theme.TEXT}; }}
            QPushButton.primary {{ background: {theme.TEXT}; color: {theme.BG}; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold; }}
            QPushButton.primary:hover {{ background: {theme.HOVER}; }}
            QPushButton.secondary {{ background: transparent; color: {theme.TEXT}; border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 6px 12px; }}
            QPushButton.secondary:hover {{ background: {theme.HOVER}; }}
        """)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.resize(360, 420)
        self.setAutoFillBackground(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Profile")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold;")
        close_btn = QPushButton("X")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {theme.MUTED}; }} QPushButton:hover {{ color: {theme.DANGER}; }}")
        close_btn.clicked.connect(self.reject)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self.pic_path = self.store.setting("profile_pic", "")
        self.avatar_preview = QLabel()
        self.avatar_preview.setFixedSize(80, 80)
        self.avatar_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_layout = QHBoxLayout()
        avatar_layout.addWidget(self.avatar_preview)
        avatar_layout.addStretch(1)

        change_pic_btn = QPushButton("Change photo")
        change_pic_btn.setProperty("class", "secondary")
        change_pic_btn.clicked.connect(self._choose_picture)
        avatar_layout.addWidget(change_pic_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(avatar_layout)

        layout.addWidget(QLabel("Display name"))
        self.name_input = QLineEdit()
        self.name_input.setText(self.store.setting("profile_name", "Boss"))
        self.name_input.textChanged.connect(self._update_preview)
        layout.addWidget(self.name_input)

        self._update_preview()

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "primary")
        save_btn.clicked.connect(self._save)
        footer.addWidget(save_btn)
        layout.addLayout(footer)

    def _update_preview(self):
        if self.pic_path and os.path.exists(self.pic_path):
            from PySide6.QtGui import QImage, QImageReader
            reader = QImageReader(self.pic_path)
            reader.setAutoTransform(True)
            img = reader.read()
            if not img.isNull():
                render_size = 80 * 3
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
                self.avatar_preview.setPixmap(final_pixmap)
        else:
            name = self.name_input.text() or "Boss"
            target = QPixmap(80, 80)
            target.fill(Qt.GlobalColor.transparent)
            painter = QPainter(target)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, 80, 80)
            painter.setClipPath(path)
            painter.fillPath(path, QColor(self.theme.AVATAR_BG))
            painter.setPen(Qt.GlobalColor.white)
            f = painter.font()
            f.setPixelSize(36)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(target.rect(), Qt.AlignmentFlag.AlignCenter, name[0].upper())
            painter.end()
            self.avatar_preview.setPixmap(target)

    def _choose_picture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Profile Picture", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            from PySide6.QtGui import QPixmap
            pix = QPixmap(path)
            if pix.isNull():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Invalid Image", "The selected file is not a valid image.")
                return
            ext = os.path.splitext(path)[1]
            dest = str(self.store.database.parent / f"profile_pic{ext}")
            try:
                shutil.copy2(path, dest)
                self.pic_path = dest
                self._update_preview()
            except Exception as e:
                print(f"Failed to copy image: {e}")

    def _save(self):
        name = self.name_input.text().strip() or "Boss"
        self.store.set_setting("profile_name", name)
        if self.pic_path:
            self.store.set_setting("profile_pic", self.pic_path)
        self.profile_updated.emit(name, self.pic_path)
        self.accept()
