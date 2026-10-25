from friday.ui_components import IconTextButton
import json
import urllib.parse
from PySide6.QtCore import Qt, QUrl, Signal, QThread
from PySide6.QtGui import QCursor, QDesktopServices, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget, QSizePolicy
from PySide6.QtWebEngineWidgets import QWebEngineView

class ThumbnailLoader(QThread):
    finished = Signal(bytes)
    def __init__(self, url):
        super().__init__()
        self.url = url
    def run(self):
        try:
            import urllib.request
            req = urllib.request.Request(self.url, headers={'User-Agent': 'Mozilla/5.0'})
            data = urllib.request.urlopen(req, timeout=5).read()
            self.finished.emit(data)
        except Exception:
            pass

class MediaCard(QFrame):
    def __init__(self, media_data: dict, theme):
        super().__init__()
        self.media = media_data
        self.theme = theme
        self.setObjectName("mediaCard")

        self.setStyleSheet(f"""
            QFrame#mediaCard {{
                background-color: {theme.PANEL};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                margin-top: 8px;
            }}
            QLabel {{ color: {theme.TEXT}; }}
        """)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self._build_preview()

    def _build_preview(self):
        self.preview_container = QWidget()
        preview_layout = QHBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(12)

        if self.media.get("thumbnail"):
            self.thumb_label = QLabel()
            self.thumb_label.setFixedSize(120, 68)
            self.thumb_label.setStyleSheet(f"background-color: {self.theme.BORDER}; border-radius: 4px;")
            self.thumb_label.setScaledContents(True)
            preview_layout.addWidget(self.thumb_label)

            self.loader = ThumbnailLoader(self.media["thumbnail"])
            self.loader.finished.connect(self._set_thumbnail)
            self.loader.start()

        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(self.media.get("title", "Unknown"))
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        info_layout.addWidget(title)

        source_txt = self.media.get("source", "")
        if self.media.get("duration"):
            source_txt += f" • {self.media.get('duration')}"
        source = QLabel(source_txt)
        source.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 12px;")
        info_layout.addWidget(source)

        snippet_text = self.media.get("snippet", "")
        if snippet_text:
            snippet = QLabel(snippet_text)
            snippet.setWordWrap(True)
            snippet.setStyleSheet("font-size: 13px;")
            info_layout.addWidget(snippet)

        info_layout.addStretch(1)
        preview_layout.addLayout(info_layout, 1)

        self.main_layout.addWidget(self.preview_container)

        actions = QWidget()
        actions.setStyleSheet(f"background-color: {self.theme.BG}; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;")
        act_layout = QHBoxLayout(actions)
        act_layout.setContentsMargins(12, 8, 12, 8)
        act_layout.addStretch(1)

        if self.media.get("type") == "video" and self.media.get("embed_url"):
            play_btn = QPushButton("▶ Play Inline")
            play_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            play_btn.setStyleSheet(f"background-color: #ff4757; color: white; border: none; border-radius: 4px; padding: 4px 12px; font-weight: bold;")
            play_btn.clicked.connect(self._play_inline)
            act_layout.addWidget(play_btn)

            fs_btn = QPushButton("⛶ Full Screen")
            fs_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            fs_btn.setStyleSheet(f"background-color: {self.theme.BORDER}; color: {self.theme.TEXT}; border: none; border-radius: 4px; padding: 4px 12px;")
            fs_btn.clicked.connect(self._request_fullscreen)
            act_layout.addWidget(fs_btn)

        open_btn = QPushButton("↗ Open Link")
        open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        open_btn.setStyleSheet(f"background-color: {self.theme.BORDER}; color: {self.theme.TEXT}; border: none; border-radius: 4px; padding: 4px 12px;")
        open_btn.clicked.connect(self._open_external)
        act_layout.addWidget(open_btn)

        self.main_layout.addWidget(actions)

    def _set_thumbnail(self, data):
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if not pixmap.isNull():
            self.thumb_label.setPixmap(pixmap)

    def _open_external(self):
        url = self.media.get("url", "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _play_inline(self):
        self.preview_container.hide()
        self.player = QWebEngineView()
        self.player.setFixedHeight(315)
        self.player.settings().setAttribute(self.player.settings().WebAttribute.FullScreenSupportEnabled, True)
        self.player.page().fullScreenRequested.connect(self._handle_fullscreen)
        embed_url = self.media["embed_url"]
        if "?" in embed_url:
            embed_url += "&origin=http://localhost"
        else:
            embed_url += "?origin=http://localhost"

        html = f'''<!DOCTYPE html><html><head><style>body {{margin:0;padding:0;background:#000;overflow:hidden;}} iframe {{width:100%;height:100vh;border:0;}}</style></head><body>
        <iframe src="{embed_url}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
        </body></html>'''

        self.player.setHtml(html, QUrl("http://localhost"))
        self.main_layout.insertWidget(0, self.player)

    def _request_fullscreen(self):
        if not hasattr(self, 'player') or not self.player:
            self._play_inline()
        if hasattr(self, 'player') and self.player:
            self._original_parent = self.player.parent()
            self.player.setParent(None)
            self.player.showFullScreen()

            if not hasattr(self, '_esc_shortcut'):
                from PySide6.QtGui import QKeySequence
                from PySide6.QtWidgets import QShortcut
                from PySide6.QtCore import Qt
                self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.player)
                self._esc_shortcut.activated.connect(self._exit_fullscreen)

    def _exit_fullscreen(self):
        if hasattr(self, 'player') and self.player and self.player.isFullScreen():
            self.player.showNormal()
            if hasattr(self, '_original_parent') and self._original_parent:
                self.player.setParent(self._original_parent)
                self.main_layout.insertWidget(0, self.player)

    def _handle_fullscreen(self, request):
        request.accept()
        if request.toggleOn():
            self._original_parent = self.player.parent()
            self.player.setParent(None)
            self.player.showFullScreen()
        else:
            self.player.showNormal()
            if hasattr(self, '_original_parent') and self._original_parent:
                self.player.setParent(self._original_parent)
                self.main_layout.insertWidget(0, self.player)

import urllib.request
import urllib.parse
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QGridLayout, QComboBox, QWidget, QScrollArea)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QImage
import threading

class ImageSearchWidget(QFrame):
    thumbnail_loaded = Signal(str, QImage, object)

    def __init__(self, query: str, results: list, theme, on_download=None, parent=None):
        super().__init__(parent)
        self.on_download = on_download
        self.theme = theme
        self.query = query
        self.all_results = results
        self.current_page = 1
        self.page_size = 20
        self.current_filter = "All"
        self.thumbnails = {}
        self.thumbnail_loaded.connect(self._on_thumbnail_loaded)

        self.setObjectName("imageSearchWidget")
        self.setStyleSheet(f"""
            QFrame#imageSearchWidget {{
                background-color: {theme.PANEL};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                margin-top: 8px;
            }}
        """)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel(f"Image Search: {query}")
        title.setStyleSheet(f"color: {theme.TEXT}; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self.filter_cb = QComboBox()
        self.filter_cb.addItems(["All", "High Resolution", "4K+", "8K+"])
        self.filter_cb.currentTextChanged.connect(self._apply_filter)
        self.filter_cb.setStyleSheet(f"background-color: {theme.BG}; color: {theme.TEXT}; border: 1px solid {theme.BORDER};")
        header.addWidget(QLabel("Quality:"))
        header.addWidget(self.filter_cb)

        layout.addLayout(header)

        self.grid = QGridLayout()
        self.grid.setSpacing(10)

        grid_widget = QWidget()
        grid_widget.setLayout(self.grid)
        layout.addWidget(grid_widget)

        footer = QHBoxLayout()
        self.status_lbl = QLabel()
        self.status_lbl.setStyleSheet(f"color: {theme.MUTED}; font-size: 10px;")
        footer.addWidget(self.status_lbl)
        footer.addStretch()

        self.load_more_btn = QPushButton("Load More")
        self.load_more_btn.setStyleSheet(f"background-color: {theme.ACCENT}; color: white; border: none; padding: 6px 12px; border-radius: 4px;")
        self.load_more_btn.clicked.connect(self._load_more)
        footer.addWidget(self.load_more_btn)

        layout.addLayout(footer)

        self._render_grid()

    def _apply_filter(self, val):
        self.current_filter = val
        self.current_page = 1
        self._render_grid()

    def _load_more(self):
        self.current_page += 1
        self._render_grid()

    def _get_filtered(self):
        f = self.current_filter
        if f == "All": return self.all_results

        res = []
        for r in self.all_results:
            q = r.get("quality", "")
            if f == "8K+" and q == "8K": res.append(r)
            elif f == "4K+" and q in ["8K", "4K"]: res.append(r)
            elif f == "High Resolution" and q in ["8K", "4K", "High"]: res.append(r)
        return res

    def _render_grid(self):
        for i in reversed(range(self.grid.count())):
            w = self.grid.itemAt(i).widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        filtered = self._get_filtered()
        visible = filtered[:self.current_page * self.page_size]

        self.status_lbl.setText(f"Showing {len(visible)} of {len(filtered)} matches (from {len(self.all_results)} total)")

        self.load_more_btn.setVisible(len(visible) < len(filtered))

        cols = 3
        for i, r in enumerate(visible):
            row = i // cols
            col = i % cols

            card = QFrame()
            card.setStyleSheet(f"background-color: {self.theme.BG}; border: 1px solid {self.theme.BORDER}; border-radius: 4px;")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(4,4,4,4)

            img_lbl = QLabel()
            img_lbl.setFixedSize(200, 150)
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(img_lbl)

            meta_lbl = QLabel(f"{r.get('resolution', 'Unknown')} • {r.get('provider', 'Unknown')}")
            meta_lbl.setStyleSheet(f"color: {self.theme.MUTED}; font-size: 9px;")
            cl.addWidget(meta_lbl)

            btn_layout = QHBoxLayout()
            btn_layout.setContentsMargins(0,0,0,0)

            btn = QPushButton("Open")
            btn.setStyleSheet(f"color: {self.theme.ACCENT}; border: none; font-size: 10px;")
            btn.clicked.connect(lambda checked, url=r.get("image_url"): self._open_url(url))
            btn_layout.addWidget(btn)

            dl_btn = QPushButton("Save")
            dl_btn.setStyleSheet(f"color: {self.theme.ACCENT}; border: none; font-size: 10px;")
            dl_btn.clicked.connect(lambda checked, res=r, b=dl_btn: self._do_download(res, b))
            btn_layout.addWidget(dl_btn)

            cl.addLayout(btn_layout)

            self.grid.addWidget(card, row, col)

            t_url = r.get("thumbnail_url")
            if t_url:
                if t_url in self.thumbnails:
                    img_lbl.setPixmap(self.thumbnails[t_url])
                else:
                    img_lbl.setText("Loading...")
                    threading.Thread(target=self._fetch_thumb, args=(t_url, img_lbl), daemon=True).start()

    def _fetch_thumb(self, url, lbl):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
            img = QImage()
            img.loadFromData(data)
            try:
                self.thumbnail_loaded.emit(url, img, lbl)
            except RuntimeError:
                pass
        except Exception:
            try:
                self.thumbnail_loaded.emit(url, QImage(), lbl)
            except RuntimeError:
                pass

    def _on_thumbnail_loaded(self, url, img, lbl):
        import shiboken6
        if not shiboken6.isValid(self):
            return
        if not shiboken6.isValid(lbl):
            return

        if not img.isNull():
            pix = QPixmap.fromImage(img).scaled(200, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.thumbnails[url] = pix
            lbl.setPixmap(pix)
        else:
            lbl.setText("Failed")

    def _open_url(self, url):
        import os
        os.startfile(url)

    def _do_download(self, res, btn):
        btn.setText("Saving...")
        btn.setEnabled(False)
        def _dl():
            if self.on_download:
                saved_path = self.on_download(res)
                if saved_path:
                    from PySide6.QtCore import QMetaObject, Q_ARG
                    QMetaObject.invokeMethod(btn, "setText", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Saved"))
                else:
                    from PySide6.QtCore import QMetaObject, Q_ARG
                    QMetaObject.invokeMethod(btn, "setText", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Failed"))
        threading.Thread(target=_dl, daemon=True).start()
