"""Friday 1.0 — local-first desktop AI assistant entrypoint."""

import os
import sys


# When frozen, prefer the matching Qt and Shiboken C runtime DLLs before any
# copies exposed by the host's PATH (for example from media or Python tools).
_DLL_DIRECTORY_HANDLES = []
if getattr(sys, "frozen", False) and sys.platform == "win32":
    _bundle_root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    _dll_dirs = [os.path.join(_bundle_root, name) for name in ("PySide6", "shiboken6")]
    for _dll_dir in _dll_dirs:
        if os.path.isdir(_dll_dir):
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(_dll_dir))
    os.environ["PATH"] = os.pathsep.join(_dll_dirs + [os.environ.get("PATH", "")])

from friday.app import FridayApp


if __name__ == "__main__":
    FridayApp().run()
