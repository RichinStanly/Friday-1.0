from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


if getattr(sys, "frozen", False):
    # Keep writable app data beside the executable, outside PyInstaller's temporary extraction directory.
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / ".friday_data"
DATABASE_PATH = DATA_DIR / "friday.db"
OLLAMA_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path = DATA_DIR
    database: Path = DATABASE_PATH

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
