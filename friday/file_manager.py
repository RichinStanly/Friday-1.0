import os
from pathlib import Path
import fnmatch
from typing import List, Dict, Any

class FileManager:
    def __init__(self, allowed_roots: List[str] = None):
        pass

    @property
    def allowed_roots(self) -> List[Path]:
        from friday.permission_manager import engine
        return engine.get_allowed_folders()

    def _is_safe_path(self, target_path: str) -> bool:
        """Check if the path is within the allowed roots and not trying to traverse out."""
        try:
            clean_path = target_path.strip().strip('"').strip("'")
            p = Path(clean_path).resolve()

            # Check if p is relative to any allowed root
            for root in self.allowed_roots:
                try:
                    p.relative_to(root)
                    return True
                except ValueError:
                    continue
            return False
        except Exception:
            return False

    def get_safe_path(self, target_path: str) -> Path | None:
        """Return the resolved Path object if it's safe, otherwise None."""
        try:
            clean_path = target_path.strip().strip('"').strip("'")
            p = Path(clean_path).resolve()

            is_safe = False
            for root in self.allowed_roots:
                try:
                    p.relative_to(root)
                    is_safe = True
                    break
                except ValueError:
                    continue

            if not is_safe:
                return None

            if p.exists():
                return p

            name_to_find = p.name.lower()
            if name_to_find == "friday" or name_to_find == "friday project":
                return self.allowed_roots[0]

            for root in self.allowed_roots:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
                    for f in filenames:
                        if f.lower() == name_to_find:
                            return Path(dirpath) / f
                    for d in dirnames:
                        if d.lower() == name_to_find:
                            return Path(dirpath) / d

            return p
        except Exception:
            return None

    def search_files(self, pattern: str, limit: int = 20) -> List[Path]:
        """Search for files matching the pattern within the allowed roots."""
        results = []
        for root in self.allowed_roots:
            if not root.exists() or not root.is_dir():
                continue

            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']

                for filename in filenames:
                    if pattern.lower() in filename.lower() or fnmatch.fnmatch(filename.lower(), pattern.lower()):
                        results.append(Path(dirpath) / filename)
                        if len(results) >= limit:
                            return results
        return results

    def list_directory(self, target_path: str = None) -> List[str]:
        """List contents of a directory. Defaults to the first allowed root if None."""
        if not target_path:
            p = self.allowed_roots[0]
        else:
            p = self.get_safe_path(target_path)

        if not p or not p.exists() or not p.is_dir():
            raise PermissionError(f"Directory access denied or not found: {target_path}")

        contents = []
        for child in p.iterdir():
            if child.name.startswith('.') or child.name == '__pycache__':
                continue
            if child.is_dir():
                contents.append(f"[DIR] {child.name}")
            else:
                contents.append(f"[FILE] {child.name}")
        return contents

    def file_info(self, target_path: str) -> Dict[str, Any]:
        """Get metadata for a file."""
        p = self.get_safe_path(target_path)
        if not p or not p.exists():
            raise PermissionError(f"File access denied or not found: {target_path}")

        stat = p.stat()
        import datetime
        return {
            "name": p.name,
            "path": str(p),
            "size_bytes": stat.st_size,
            "type": "directory" if p.is_dir() else "file",
            "modified": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        }

    def open_file(self, target_path: str) -> bool:
        """Open a file with the system's default application."""
        p = self.get_safe_path(target_path)
        if not p or not p.exists() or not p.is_file():
            raise PermissionError(f"File access denied or not found: {target_path}")

        # Ensure it's not a direct executable to be safe
        if p.suffix.lower() in ['.exe', '.bat', '.cmd', '.msi']:
            raise PermissionError(f"Execution of binaries/scripts is blocked: {p.name}")

        if hasattr(os, 'startfile'):
            os.startfile(str(p))
            return True
        return False

    def delete_file(self, target_path: str) -> bool:
        """Delete a file if it is within the allowed workspace."""
        p = self.get_safe_path(target_path)
        if not p or not p.exists() or not p.is_file():
            raise PermissionError(f"File access denied or not found: {target_path}")

        p.unlink()
        return True
