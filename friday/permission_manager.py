import logging
import threading
from enum import Enum
from dataclasses import dataclass
from typing import Any, Callable, List
from pathlib import Path
import os
from friday.config import APP_DIR

logger = logging.getLogger(__name__)
DEFAULT_ALLOWED_FOLDER = APP_DIR.resolve()
_DEFAULT_ALLOWED_FOLDER_SETTING = str(DEFAULT_ALLOWED_FOLDER).replace("\\", "/")

class PermissionLevel(Enum):
    SAFE = 1
    CONFIRM = 2
    BLOCKED = 3

@dataclass
class PermissionRequest:
    action_name: str
    target: str
    consequence: str

class PermissionEngine:
    def __init__(self):
        # A callback to present UI (must be injected by app.py)
        self.ui_confirm_callback: Callable[[PermissionRequest], bool] | None = None
        self.store = None

        self._allowed_folders: List[Path] = [DEFAULT_ALLOWED_FOLDER]
        self._allowed_apps: dict[str, str] = {
            "chrome": "chrome",
            "notepad": "notepad",
            "calculator": "calc",
            "calc": "calc",
            "explorer": "explorer",
            "figma": "figma",
            "vscode": "code",
            "code": "code"
        }

    def set_store(self, store):
        self.store = store
        self.reload_permissions()

    def reload_permissions(self):
        if not self.store: return

        folders = self.store.setting("allowed_folders", [_DEFAULT_ALLOWED_FOLDER_SETTING])
        self._allowed_folders = []
        for f in folders:
            try:
                p = Path(f).resolve()
                if p.drive.upper() != "C:":
                    self._allowed_folders.append(p)
            except Exception:
                pass

        # Keep the application folder available as the default workspace.
        default_root = DEFAULT_ALLOWED_FOLDER
        if default_root not in self._allowed_folders:
            self._allowed_folders.insert(0, default_root)

        base_apps = {
            "chrome": "chrome", "notepad": "notepad", "calculator": "calc",
            "calc": "calc", "explorer": "explorer", "figma": "figma",
            "vscode": "code", "code": "code"
        }
        user_apps = self.store.setting("allowed_apps", {})
        self._allowed_apps = {**base_apps, **user_apps}

    def is_app_allowed(self, app_name: str) -> str | None:
        return self._allowed_apps.get(app_name.lower().strip())

    def add_app(self, app_name: str, executable_path: str):
        if not self.store: return
        user_apps = self.store.setting("allowed_apps", {})
        user_apps[app_name.lower().strip()] = executable_path
        self.store.set_setting("allowed_apps", user_apps)
        self.reload_permissions()

    def remove_app(self, app_name: str):
        if not self.store: return
        user_apps = self.store.setting("allowed_apps", {})
        key = app_name.lower().strip()
        if key in user_apps:
            del user_apps[key]
            self.store.set_setting("allowed_apps", user_apps)
            self.reload_permissions()

    def get_custom_apps(self) -> dict[str, str]:
        return self.store.setting("allowed_apps", {}) if self.store else {}

    def get_allowed_folders(self) -> List[Path]:
        return self._allowed_folders

    def add_folder(self, folder_path: str) -> bool:
        if not self.store: return False
        try:
            p = Path(folder_path).resolve()
            if p.drive.upper() == "C:": return False # Hard block C:
            if not p.exists() or not p.is_dir(): return False

            folders = self.store.setting("allowed_folders", [_DEFAULT_ALLOWED_FOLDER_SETTING])
            str_path = str(p).replace("\\", "/")
            if str_path not in folders:
                folders.append(str_path)
                self.store.set_setting("allowed_folders", folders)
                self.reload_permissions()
            return True
        except Exception:
            return False

    def remove_folder(self, folder_path: str):
        if not self.store: return
        try:
            p = Path(folder_path).resolve()
            str_path = str(p).replace("\\", "/")
            # Prevent removing the application folder entirely from settings,
            # but user can remove it from their custom list. The reload_permissions hardcodes it anyway.
            folders = self.store.setting("allowed_folders", [_DEFAULT_ALLOWED_FOLDER_SETTING])
            if str_path in folders:
                folders.remove(str_path)
                self.store.set_setting("allowed_folders", folders)
                self.reload_permissions()
        except Exception:
            pass

    def get_custom_folders(self) -> List[str]:
        folders = self.store.setting("allowed_folders", [_DEFAULT_ALLOWED_FOLDER_SETTING])
        default_root = _DEFAULT_ALLOWED_FOLDER_SETTING
        return [f for f in folders if str(Path(f).resolve()).replace("\\", "/") != default_root]

    def check_permission(self, level: PermissionLevel, action_name: str, target: str, consequence: str = "") -> bool:
        if action_name == "launch_app":
            pass

        if level == PermissionLevel.SAFE:
            return True

        if level == PermissionLevel.BLOCKED:
            logger.warning(f"Blocked action attempted: {action_name} on {target}")
            return False

        if level == PermissionLevel.CONFIRM:
            if not self.ui_confirm_callback:
                logger.warning(f"No UI callback registered for confirmation. Blocking {action_name}.")
                return False

            req = PermissionRequest(
                action_name=action_name,
                target=target,
                consequence=consequence or "This action requires user approval."
            )
            return self.ui_confirm_callback(req)

        return False

engine = PermissionEngine()
