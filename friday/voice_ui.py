import math
import random
import psutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QPropertyAnimation, QPropertyAnimation, QPropertyAnimation, QPropertyAnimation, Qt, QTimer, QRectF, QPointF, QThread, Signal
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QPen, QFont, QLinearGradient, QPainterPath, QImage, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QGraphicsOpacityEffect, QGraphicsOpacityEffect, QGraphicsOpacityEffect, QGraphicsOpacityEffect, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QSizePolicy, QSpacerItem, QScrollArea


class _ImageLoadWorker(QThread):
    """Decode local search results off the GUI thread."""
    loaded = Signal(str, QImage)
    failed = Signal(str)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.paths = paths

    def run(self):
        for raw_path in self.paths:
            path = Path(raw_path)
            image = QImage(str(path))
            if image.isNull():
                self.failed.emit(str(path))
            else:
                self.loaded.emit(str(path), image)

class HUDBracketPanel(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 25, 20, 20)

        self.title_lbl = QLabel(title)
        self.title_lbl.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet("color: rgba(0, 255, 255, 200); letter-spacing: 2px;")
        self.layout.addWidget(self.title_lbl)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, QColor(10, 20, 35, 150))

        pen = QPen(QColor(0, 200, 255, 100))
        pen.setWidth(2)
        painter.setPen(pen)

        c = 15
        painter.drawLine(0, c, 0, 0)
        painter.drawLine(0, 0, c, 0)
        painter.drawLine(w-c, 0, w, 0)
        painter.drawLine(w, 0, w, c)
        painter.drawLine(0, h-c, 0, h)
        painter.drawLine(0, h, c, h)
        painter.drawLine(w-c, h, w, h)
        painter.drawLine(w, h, w, h-c)


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.history = [0.0] * 60
        self.target_amp = 0.0
        self.current_amp = 0.0
        self.state = "IDLE"

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_wave)
        self.timer.start(16)

    def set_amplitude(self, amp: float):
        self.target_amp = min(amp / 8000.0, 1.0)

    def update_wave(self):
        self.current_amp += (self.target_amp - self.current_amp) * 0.3
        if self.current_amp < 0.02: self.current_amp = 0.0

        self.history.pop(0)
        noise = random.uniform(0.5, 1.0) if self.current_amp > 0.05 else 0.0
        self.history.append(self.current_amp * noise)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        mid_y = h / 2

        if self.state == "LISTENING": color = QColor(0, 255, 255, 220)
        elif self.state == "SPEAKING": color = QColor(0, 255, 100, 220)
        elif self.state == "PROCESSING": color = QColor(100, 50, 255, 220)
        elif self.state == "TOOL EXECUTION": color = QColor(0, 255, 150, 220)
        elif self.state == "ERROR": color = QColor(255, 80, 0, 220)
        else: color = QColor(0, 150, 255, 100)

        pen = QPen(color)
        pen.setWidth(3)
        painter.setPen(pen)

        num_bars = len(self.history)
        bar_w = w / num_bars

        for i, val in enumerate(self.history):
            x = i * bar_w
            bar_h = val * (h / 2.2)
            if bar_h < 1: bar_h = 1

            painter.drawLine(int(x), int(mid_y - bar_h), int(x), int(mid_y + bar_h))

class CinematicCoreWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 600)
        self.amplitude = 0.0
        self.target_amplitude = 0.0
        self.state = "IDLE"

        self.angle_slow = 0.0
        self.angle_mid = 0.0
        self.angle_fast = 0.0
        self.radar_angle = 0.0
        self.pulse = 0.0

        self.particles = [{"angle": random.uniform(0, 360), "dist": random.uniform(0.1, 1.0), "speed": random.uniform(0.002, 0.015), "size": random.uniform(1, 3)} for _ in range(60)]

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(16)

    def set_amplitude(self, amp: float):
        self.target_amplitude = min(amp / 10000.0, 1.0)

    def set_state(self, state: str):
        self.state = state

    def update_animation(self):
        self.amplitude += (self.target_amplitude - self.amplitude) * 0.2
        if self.amplitude < 0.01: self.amplitude = 0

        speed_mult = 1.0
        if self.state == "PROCESSING": speed_mult = 3.0
        elif self.state == "TOOL EXECUTION": speed_mult = 4.0
        elif self.state == "LISTENING": speed_mult = 1.5 + (self.amplitude * 2)
        elif self.state == "SPEAKING": speed_mult = 1.5 + (self.amplitude * 2)
        else: speed_mult = 0.5

        self.angle_slow = (self.angle_slow + 0.3 * speed_mult) % 360
        self.angle_mid = (self.angle_mid - 1.2 * speed_mult) % 360
        self.angle_fast = (self.angle_fast + 2.5 * speed_mult) % 360
        self.radar_angle = (self.radar_angle - 5.0 * speed_mult) % 360
        self.pulse += 0.05 * speed_mult

        for p in self.particles:
            p["dist"] += p["speed"] * speed_mult
            if p["dist"] > 1.3:
                p["dist"] = 0.1
                p["angle"] = random.uniform(0, 360)

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        center = QPointF(w / 2, h / 2)
        base_r = min(w, h) / 2.5

        amp_mod = self.amplitude * 20

        if self.state == "LISTENING":
            core = QColor(0, 200, 255, 200)
            glow = QColor(0, 150, 255, 40)
            accent = QColor(200, 255, 255, 200)
        elif self.state == "PROCESSING":
            core = QColor(50, 100, 255, 200)
            glow = QColor(0, 50, 255, 40)
            accent = QColor(150, 180, 255, 200)
        elif self.state == "TOOL EXECUTION":
            core = QColor(255, 180, 0, 200)
            glow = QColor(0, 200, 255, 30)
            accent = QColor(0, 255, 255, 200)
        elif self.state == "SPEAKING":
            core = QColor(0, 220, 120, 200)
            glow = QColor(0, 150, 80, 40)
            accent = QColor(150, 255, 200, 200)
        elif self.state == "ERROR":
            core = QColor(255, 50, 50, 200)
            glow = QColor(255, 0, 0, 40)
            accent = QColor(255, 150, 150, 200)
        else:
            core = QColor(50, 120, 200, 100)
            glow = QColor(0, 50, 150, 20)
            accent = QColor(100, 150, 255, 80)

        grad = QRadialGradient(center, base_r * 1.5)
        grad.setColorAt(0, glow)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, base_r * 1.5, base_r * 1.5)

        pen = QPen(core, 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        br = base_r * 1.15
        cs = 15
        painter.drawPolyline([QPointF(center.x() - br, center.y() - br + cs), QPointF(center.x() - br, center.y() - br), QPointF(center.x() - br + cs, center.y() - br)])
        painter.drawPolyline([QPointF(center.x() + br - cs, center.y() - br), QPointF(center.x() + br, center.y() - br), QPointF(center.x() + br, center.y() - br + cs)])
        painter.drawPolyline([QPointF(center.x() - br, center.y() + br - cs), QPointF(center.x() - br, center.y() + br), QPointF(center.x() - br + cs, center.y() + br)])
        painter.drawPolyline([QPointF(center.x() + br - cs, center.y() + br), QPointF(center.x() + br, center.y() + br), QPointF(center.x() + br, center.y() + br - cs)])

        painter.setPen(QColor(255, 255, 255, 100))
        painter.setFont(QFont("Consolas", 6))
        painter.drawText(int(center.x() - br + 5), int(center.y() - br - 5), f"STATE: {self.state}")
        painter.drawText(int(center.x() + br - 45), int(center.y() - br - 5), f"AZM: {int(self.angle_slow):03d}")
        painter.drawText(int(center.x() - br + 5), int(center.y() + br + 10), f"PWR: {int(self.amplitude*100)}%")
        painter.drawText(int(center.x() + br - 45), int(center.y() + br + 10), f"SYNC: OK")

        if self.state in ["PROCESSING", "TOOL EXECUTION"]:
            radar_grad = QRadialGradient(center, base_r)
            radar_grad.setColorAt(0, QColor(core.red(), core.green(), core.blue(), 15))
            radar_grad.setColorAt(1, QColor(0,0,0,0))
            painter.setBrush(radar_grad)
            painter.setPen(Qt.PenStyle.NoPen)
            rect_radar = QRectF(center.x() - base_r, center.y() - base_r, base_r*2, base_r*2)
            painter.drawPie(rect_radar, int(self.radar_angle * 16), 30 * 16)

        tick_r_inner = base_r * 0.95
        tick_r_outer = base_r * 0.98
        for i in range(0, 360, 2):
            if i % 10 == 0:
                painter.setPen(QPen(accent, 1))
                tr_out = base_r * 1.02
            else:
                painter.setPen(QPen(core, 1))
                tr_out = tick_r_outer
            rad = math.radians(i + self.angle_slow*0.1)
            p1 = QPointF(center.x() + math.cos(rad)*tick_r_inner, center.y() + math.sin(rad)*tick_r_inner)
            p2 = QPointF(center.x() + math.cos(rad)*tr_out, center.y() + math.sin(rad)*tr_out)
            painter.drawLine(p1, p2)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect_1 = QRectF(center.x() - base_r*0.9, center.y() - base_r*0.9, base_r*1.8, base_r*1.8)
        painter.setPen(QPen(core, 1))
        for i in range(6): painter.drawArc(rect_1, int((self.angle_slow + i*60) * 16), 25 * 16)

        rect_2 = QRectF(center.x() - base_r*0.8, center.y() - base_r*0.8, base_r*1.6, base_r*1.6)
        painter.setPen(QPen(accent, 1))
        for i in range(4): painter.drawArc(rect_2, int((-self.angle_mid + i*90) * 16), 15 * 16)

        pen = QPen(core, 2)
        pen.setDashPattern([1, 8])
        painter.setPen(pen)
        rect_dot = QRectF(center.x() - base_r*0.7, center.y() - base_r*0.7, base_r*1.4, base_r*1.4)
        painter.drawArc(rect_dot, int(self.angle_fast * 16), 360 * 16)

        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawLine(int(center.x() - base_r*0.65), int(center.y()), int(center.x() + base_r*0.65), int(center.y()))
        painter.drawLine(int(center.x()), int(center.y() - base_r*0.65), int(center.x()), int(center.y() + base_r*0.65))

        r_in = base_r * 0.5
        pen = QPen(accent, 1.5)
        pen.setDashPattern([2, 6, 4, 6])
        painter.setPen(pen)
        rect_in = QRectF(center.x() - r_in, center.y() - r_in, r_in*2, r_in*2)
        painter.drawArc(rect_in, int(-self.angle_fast * 16), 360 * 16)

        painter.setPen(QColor(255, 255, 255, 80))
        painter.setFont(QFont("Consolas", 6))
        painter.drawText(int(center.x() + base_r*0.3), int(center.y() - base_r*0.3), f"{math.sin(self.pulse):.3f}")
        painter.drawText(int(center.x() - base_r*0.4), int(center.y() + base_r*0.4), f"RX: {int(self.target_amplitude*1000)}")

        painter.setPen(Qt.PenStyle.NoPen)
        for p in self.particles:
            painter.setBrush(QColor(core.red(), core.green(), core.blue(), int(200 * (1.3 - p["dist"]))))
            rad = math.radians(p["angle"] + self.angle_slow)
            pr = base_r * p["dist"]
            px = center.x() + math.cos(rad) * pr
            py = center.y() + math.sin(rad) * pr
            painter.drawEllipse(QPointF(px, py), p["size"]*0.5, p["size"]*0.5)

        core_r = (base_r * 0.15) + amp_mod
        if self.state in ["PROCESSING", "SPEAKING", "TOOL EXECUTION"]:
            core_r += math.sin(self.pulse * 15) * 3

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(accent, 1))
        painter.drawEllipse(center, core_r + 5, core_r + 5)

        core_grad = QRadialGradient(center, core_r)
        core_grad.setColorAt(0, QColor(255, 255, 255, 150))
        core_grad.setColorAt(0.4, QColor(core.red(), core.green(), core.blue(), 100))
        core_grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(core_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, core_r, core_r)

class FridayVoiceExperience(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QWidget {
                color: white;
                font-family: "Segoe UI";
            }
            QProgressBar {
                background-color: rgba(0, 50, 100, 100);
                border: 1px solid rgba(0, 200, 255, 40);
                height: 4px;
            }
            QProgressBar::chunk {
                background-color: #00e5ff;
            }
        """)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.on_exit = None
        self.bg_angle = 0.0

        self.bg_timer = QTimer(self)
        self.bg_timer.timeout.connect(self.update_bg)
        self.bg_timer.start(50)


        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        header = QHBoxLayout()

        title_box = QVBoxLayout()
        title = QLabel("FRIDAY")
        title.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        title.setStyleSheet("color: #fff; letter-spacing: 6px;")
        sub = QLabel("YOUR PERSONAL AI ASSISTANT")
        sub.setFont(QFont("Segoe UI", 8))
        sub.setStyleSheet("color: #00e5ff; letter-spacing: 3px;")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        header.addLayout(title_box)

        header.addStretch()

        self.top_status = HUDBracketPanel("")
        self.top_status.title_lbl.hide()
        self.top_status.setFixedSize(350, 70)

        status_h = QHBoxLayout()

        self.icon_lbl = QLabel("◈")
        self.icon_lbl.setFont(QFont("Segoe UI", 20))
        self.icon_lbl.setStyleSheet("color: #00e5ff;")
        status_h.addWidget(self.icon_lbl)

        self.status_label = QLabel("FRIDAY // IDLE")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.status_label.setStyleSheet("color: #00e5ff; letter-spacing: 2px;")
        status_h.addWidget(self.status_label)
        self.top_status.layout.addLayout(status_h)

        header.addWidget(self.top_status)

        header.addStretch()

        ind_box = QVBoxLayout()
        ind1 = QLabel("● LOCAL AI READY")
        ind2 = QLabel("● INTERNET CONNECTED")
        ind1.setStyleSheet("color: #00ff00; font-family: Consolas; font-size: 10px;")
        ind2.setStyleSheet("color: #00ff00; font-family: Consolas; font-size: 10px;")
        ind_box.addWidget(ind1)
        ind_box.addWidget(ind2)

        self.exit_btn = QPushButton("✕ EXIT")
        self.exit_btn.setFixedSize(100, 25)
        self.exit_btn.setStyleSheet("QPushButton { background: transparent; border: 1px solid rgba(255,0,0,100); color: #f55; font-family: Consolas; }")
        self.exit_btn.clicked.connect(self._do_exit)
        ind_box.addWidget(self.exit_btn)
        header.addLayout(ind_box)

        main_layout.addLayout(header)

        mid_layout = QHBoxLayout()

        left_box = QVBoxLayout()
        left_box.setSpacing(20)
        left_box.setContentsMargins(0, 10, 0, 10)

        nav_panel = HUDBracketPanel("SYSTEM NAV")
        nav_panel.setFixedWidth(220)
        for nav in ["VOICE", "CHAT", "TOOLS", "IMAGES", "VIDEOS", "FILES", "SETTINGS"]:
            btn = QLabel(f"> {nav}")
            btn.setFont(QFont("Consolas", 10))
            color = "#00e5ff" if nav == "VOICE" else "#558"
            btn.setStyleSheet(f"color: {color}; padding: 5px 0;")
            nav_panel.layout.addWidget(btn)
        left_box.addWidget(nav_panel)

        sys_panel = HUDBracketPanel("SYSTEM STATUS")
        sys_panel.setFixedWidth(220)
        self.cpu_bar = QProgressBar(); self.cpu_bar.setTextVisible(False)
        self.ram_bar = QProgressBar(); self.ram_bar.setTextVisible(False)
        self.gpu_bar = QProgressBar(); self.gpu_bar.setTextVisible(False)
        self.gpu_bar.setValue(18)

        def add_stat(name, bar):
            row = QHBoxLayout()
            lbl = QLabel(name)
            lbl.setFixedWidth(40)
            lbl.setFont(QFont("Consolas", 9))
            lbl.setStyleSheet("color: #88a;")
            row.addWidget(lbl)
            row.addWidget(bar)
            sys_panel.layout.addLayout(row)

        add_stat("CPU", self.cpu_bar)
        add_stat("GPU", self.gpu_bar)
        add_stat("RAM", self.ram_bar)
        left_box.addWidget(sys_panel)
        left_box.addStretch()
        mid_layout.addLayout(left_box)

        center_stage = QHBoxLayout()
        self.core = CinematicCoreWidget()
        center_stage.addWidget(self.core, alignment=Qt.AlignmentFlag.AlignCenter)
        mid_layout.addLayout(center_stage, stretch=1)

        right_box = QVBoxLayout()
        right_box.setSpacing(12)
        right_box.setContentsMargins(0, 10, 0, 10)

        task_panel = HUDBracketPanel("CURRENT TASK")
        task_panel.setFixedWidth(300)
        self.task_label = QLabel("Listening for your command...")
        self.task_label.setFont(QFont("Consolas", 9))
        self.task_label.setStyleSheet("color: #ccc;")
        self.task_label.setWordWrap(True)
        task_panel.layout.addWidget(self.task_label)
        right_box.addWidget(task_panel)

        tool_panel = HUDBracketPanel("TOOLS")
        tool_panel.setFixedWidth(300)
        self.tool_label = QLabel("> STANDBY")
        self.tool_label.setFont(QFont("Consolas", 9))
        self.tool_label.setStyleSheet("color: #00e5ff;")
        self.tool_label.setWordWrap(True)
        tool_panel.layout.addWidget(self.tool_label)
        right_box.addWidget(tool_panel)

        image_panel = HUDBracketPanel("IMAGE RESULTS")
        image_panel.setFixedWidth(300)
        self.image_host = QWidget()
        self.image_layout = QHBoxLayout(self.image_host)
        self.image_layout.setContentsMargins(2, 2, 2, 2)
        self.image_layout.setSpacing(6)
        self.image_empty = QLabel("No image search active")
        self.image_empty.setFont(QFont("Consolas", 8))
        self.image_empty.setStyleSheet("color: #557;")
        self.image_layout.addWidget(self.image_empty)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setWidget(self.image_host)
        self.image_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.image_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.image_scroll.setFixedHeight(115)
        image_panel.layout.addWidget(self.image_scroll)
        right_box.addWidget(image_panel)
        self.image_panel = image_panel
        self.image_panel.hide()
        self._image_worker = None

        you_panel = HUDBracketPanel("YOU SAID")
        you_panel.setFixedWidth(300)
        self.you_label = QLabel("—")
        self.you_label.setFont(QFont("Segoe UI", 11))
        self.you_label.setStyleSheet("color: #fff; padding: 4px 0;")
        self.you_label.setWordWrap(True)
        you_panel.layout.addWidget(self.you_label)
        right_box.addWidget(you_panel)

        friday_panel = HUDBracketPanel("FRIDAY")
        friday_panel.setFixedWidth(300)
        self.friday_label = QTextBrowser()
        self.friday_label.setFont(QFont("Segoe UI", 11))
        self.friday_label.setStyleSheet("""
            QTextBrowser {
                background: transparent;
                border: none;
                color: #00e5ff;
                padding: 4px 0;
            }
        """)
        self.friday_label.setMaximumHeight(200)
        self.friday_label.setHtml("<p style='color:#555;'>—</p>")
        friday_panel.layout.addWidget(self.friday_label)
        right_box.addWidget(friday_panel)

        right_box.addStretch()
        mid_layout.addLayout(right_box)

        main_layout.addLayout(mid_layout, stretch=1)

        bot_layout = QHBoxLayout()

        self.time_lbl = QLabel()
        self.time_lbl.setFont(QFont("Consolas", 14))
        self.time_lbl.setStyleSheet("color: #00e5ff;")
        bot_layout.addWidget(self.time_lbl)

        bot_layout.addStretch()

        voice_box = HUDBracketPanel("")
        voice_box.title_lbl.hide()
        voice_box.setMinimumWidth(600)
        voice_box.setFixedHeight(100)
        v_layout = QHBoxLayout()

        mic_icon = QLabel("🎤")
        mic_icon.setFont(QFont("Segoe UI", 24))
        mic_icon.setStyleSheet("color: #00e5ff; background: rgba(0, 200, 255, 20); border-radius: 20px; padding: 5px;")
        v_layout.addWidget(mic_icon)

        inner_v = QVBoxLayout()
        self.subtitle_label = QLabel("Speak now, Boss...")
        self.subtitle_label.setFont(QFont("Segoe UI", 12))
        self.subtitle_label.setStyleSheet("color: #fff;")
        inner_v.addWidget(self.subtitle_label)

        self.wave = WaveformWidget()
        inner_v.addWidget(self.wave)
        v_layout.addLayout(inner_v)

        voice_box.layout.addLayout(v_layout)
        bot_layout.addWidget(voice_box)

        bot_layout.addStretch()
        main_layout.addLayout(bot_layout)

        self.sys_timer = QTimer(self)
        self.sys_timer.timeout.connect(self._update_system_stats)
        self.sys_timer.start(1000)
        self._update_system_stats()

    def _update_system_stats(self):
        self.cpu_bar.setValue(int(psutil.cpu_percent()))
        self.ram_bar.setValue(int(psutil.virtual_memory().percent))
        now = datetime.now()
        self.time_lbl.setText(now.strftime("%H:%M<br><span style='font-size:10px;color:#88a'>%a, %b %d %Y</span>"))

    def _do_exit(self):
        if self.on_exit:
            self.on_exit()

    def set_state(self, state: str):
        self.core.set_state(state)
        self.wave.state = state
        self.status_label.setText(f"FRIDAY // {state}")

        if state == "IDLE":
            self.icon_lbl.setText("◈")
            self.subtitle_label.setText("")
            self.task_label.setText("Standing by.")
            self.tool_label.setText("> STANDBY")
        elif state == "LISTENING":
            self.icon_lbl.setText("🎙")
            self.subtitle_label.setText("Listening, Boss...")
            self.task_label.setText("Recording microphone input...")
            self.tool_label.setText("> STANDBY")
        elif state == "PROCESSING":
            self.icon_lbl.setText("⚙")
            self.task_label.setText("Analyzing query...")
            self.tool_label.setText("> THINKING...")
            self.friday_label.setHtml("<p style='color:#555; font-size:11px;'>⚙ Generating response...</p>")
        elif state == "SPEAKING":
            self.icon_lbl.setText("🔊")
            self.task_label.setText("Speaking response...")
            self.tool_label.setText("> SPEAKING")

    def set_amplitude(self, amp: float):
        scaled = min(amp / 30.0, 1.0)
        self.core.set_amplitude(scaled * 10000.0)
        self.wave.set_amplitude(scaled * 8000.0)

    def set_user_query(self, text: str):
        """Display the user's transcribed speech."""
        self.you_label.setText(text)
        self.subtitle_label.setText(f'"{text}"')
        self.task_label.setText("Query received — processing...")
        self.friday_label.setHtml("<p style='color:#555; font-size:11px;'>⚙ Generating response...</p>")
        self.image_panel.hide()

    def set_transcript(self, text: str):
        """Display Friday's response."""
        if not text:
            return
        import html as _html
        if "```" in text or "**" in text or "#" in text:
            self.friday_label.setMarkdown(text)
        else:
            safe = _html.escape(text).replace('\n', '<br>')
            self.friday_label.setHtml(f"<p style='color:#00e5ff; font-size:12px; line-height:1.5;'>{safe}</p>")
        self.task_label.setText("Response delivered.")
        self.tool_label.setText("> COMPLETE")
        short = text[:100] + "..." if len(text) > 100 else text
        self.subtitle_label.setText(short)

    def set_tool_activity(self, tool_name: str):
        """Show which tool is being used."""
        self.tool_label.setText(f"> 🔧 {tool_name.upper()}")
        self.task_label.setText(f"Tool: {tool_name}")
        self.core.set_state("TOOL EXECUTION")
        self.wave.state = "TOOL EXECUTION"
        self.status_label.setText("FRIDAY // TOOL EXECUTION")
        self.friday_label.setHtml(
            f"<p style='color:#ffaa00; font-size:11px;'>🔧 Running: {tool_name}</p>"
        )

    def set_images(self, paths: list[str]):
        """Render image-search artifacts after asynchronous decoding."""
        valid_paths = [str(Path(path)) for path in paths if Path(path).is_file()]
        while self.image_layout.count():
            item = self.image_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not valid_paths:
            self.image_panel.hide()
            return
        self.image_panel.show()
        loading = QLabel("Loading images…")
        loading.setStyleSheet("color: #00e5ff;")
        self.image_layout.addWidget(loading)
        worker = _ImageLoadWorker(valid_paths, self)
        self._image_worker = worker
        worker.loaded.connect(self._add_image)
        worker.failed.connect(self._image_failed)
        worker.finished.connect(lambda: setattr(self, "_image_worker", None))
        worker.start()

    def _add_image(self, path: str, image: QImage):
        if self.image_layout.count() == 1:
            item = self.image_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        label = QLabel()
        label.setToolTip(path)
        pixmap = QPixmap.fromImage(image).scaled(118, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pixmap)
        label.setFixedSize(122, 100)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid rgba(0, 229, 255, 90); background: #06101c;")
        self.image_layout.addWidget(label)
        self.tool_label.setText("> IMAGE SEARCH: RESULTS READY")

    def _image_failed(self, path: str):
        self.task_label.setText(f"Could not load image: {Path(path).name}")

    def update_bg(self):
        self.bg_angle += 0.5
        if self.bg_angle >= 360: self.bg_angle -= 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        center = QPointF(w / 2, h / 2)

        painter.fillRect(0, 0, w, h, QColor(2, 5, 12))

        bg_grad = QRadialGradient(center, w / 1.2)
        bg_grad.setColorAt(0, QColor(0, 40, 80, 40))
        bg_grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(bg_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, w, h)

        painter.setPen(QPen(QColor(0, 150, 255, 3), 1))
        grid_size = 80
        for x in range(0, w, grid_size): painter.drawLine(x, 0, x, h)
        for y in range(0, h, grid_size): painter.drawLine(0, y, w, y)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 150, 255, 6), 1))
        for r in [h*0.4, h*0.6, h*0.8, h*1.1]:
            painter.drawEllipse(center, r, r)

        painter.setPen(QPen(QColor(0, 150, 255, 4), 2))
        rect_bg = QRectF(center.x() - h*0.7, center.y() - h*0.7, h*1.4, h*1.4)
        painter.drawArc(rect_bg, int(self.bg_angle * 16), 50 * 16)
        painter.drawArc(rect_bg, int((self.bg_angle + 180) * 16), 50 * 16)

        painter.setPen(QPen(QColor(0, 150, 255, 4), 1))
        for i in range(0, 360, 15):
            rad = math.radians(i + self.bg_angle*0.05)
            p2 = QPointF(center.x() + math.cos(rad)*w, center.y() + math.sin(rad)*w)
            painter.drawLine(center, p2)

        painter.setPen(QColor(0, 200, 255, 15))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(w - 200, h - 100, f"SYS.NET.UPLINK {int(self.bg_angle)}")
        painter.drawText(50, 80, f"FRIDAY_OS v2.0 // SECTOR 04")

        scan_y = (self.bg_angle * 8) % h
        painter.fillRect(0, int(scan_y), w, 2, QColor(0, 255, 255, 5))

        vig = QRadialGradient(center, w / 1.5)
        vig.setColorAt(0, QColor(0, 0, 0, 0))
        vig.setColorAt(0.7, QColor(0, 0, 0, 100))
        vig.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.setBrush(vig)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, w, h)
