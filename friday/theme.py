
class Theme:
    def __init__(self, is_light: bool):
        self.is_light = is_light
        if is_light:
            self.BG = "#ffffff"
            self.PANEL = "#f7f7f8"
            self.SIDEBAR = "#f7f7f8"
            self.TEXT = "#0d0d0d"
            self.MUTED = "#8e8ea0"
            self.ACCENT = "#10a37f"
            self.USER = "#f4f4f4"
            self.BORDER = "#e5e5e5"
            self.HOVER = "#ececec"
            self.SELECTED = "#e5e5e5"
            self.DANGER = "#ef4444"
            self.AVATAR_BG = "#10a37f"
            self.AVATAR_FG = "#ffffff"
        else:
            self.BG = "#212121"
            self.PANEL = "#2f2f2f"
            self.SIDEBAR = "#171717"
            self.TEXT = "#ececec"
            self.MUTED = "#b4b4b4"
            self.ACCENT = "#10a37f"
            self.USER = "#2f2f2f"
            self.BORDER = "#383838"
            self.HOVER = "#2a2a2a"
            self.SELECTED = "#343434"
            self.DANGER = "#ef4444"
            self.AVATAR_BG = "#10a37f"
            self.AVATAR_FG = "#ffffff"

    def get_style(self):
        return f"""
        QWidget {{
            color: {self.TEXT};
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 14px;
        }}
        QMainWindow, #messageHost {{
            background: {self.BG};
        }}
        #sidebar {{
            background: {self.SIDEBAR};
            border-right: 1px solid {self.BORDER};
        }}
        #topBar {{
            background: {self.BG};
            border-bottom: 1px solid {self.BORDER};
        }}
        QListWidget {{
            background: transparent;
            border: none;
            outline: none;
        }}
        QListWidget::item {{
            padding: 10px;
            border-radius: 6px;
            margin: 2px 8px;
        }}
        QListWidget::item:hover {{
            background: {self.HOVER};
        }}
        QListWidget::item:selected {{
            background: {self.SELECTED};
        }}
        QPushButton {{
            background: transparent;
            border: none;
            border-radius: 6px;
            padding: 8px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background: {self.HOVER};
        }}
        #primaryBtn {{
            background: {self.ACCENT};
            color: white;
        }}
        #primaryBtn:hover {{
            background: #0e8c6d;
        }}
        #composer {{
            background: {self.BG};
            border: 1px solid {self.BORDER};
            border-radius: 12px;
        }}
        #composerInput {{
            background: transparent;
            border: none;
            padding: 10px;
        }}
        #suggestionCard {{
            background: {self.BG};
            border: 1px solid {self.BORDER};
            border-radius: 8px;
            padding: 16px;
        }}
        #suggestionCard:hover {{
            background: {self.HOVER};
        }}
        QComboBox {{
            background: transparent;
            border: 1px solid {self.BORDER};
            border-radius: 6px;
            padding: 6px 12px;
        }}
        QComboBox:hover {{
            background: {self.HOVER};
        }}
        QComboBox::drop-down {{
            border: none;
        }}
        QMenu {{
            background: {self.PANEL};
            border: 1px solid {self.BORDER};
            border-radius: 8px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 8px 24px 8px 12px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background: {self.HOVER};
        }}
        """
