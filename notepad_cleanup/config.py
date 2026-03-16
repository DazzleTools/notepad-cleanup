"""Configuration manager for notepad-cleanup.

Manages the unified folder registry, MRU extraction history,
... notation expansion, and all persistent settings.

Config file: ~/.notepad-cleanup.json

Folder registry:
  - Folders are stored in an ordered list
  - Position 0 is always the output folder (referenced as '...')
  - Other folders are referenced as '...1', '...2', etc.
  - Each folder can be assigned roles: output (always [0]) and/or search
  - Roles are independent -- a folder can be output, search, both, or neither

MRU (Most Recently Used) extractions:
  - Recent extractions stored as '...-1' (most recent), '...-2', etc.
  - Configurable depth (default 10)

... notation:
  - '...'   = output folder (always folders[0])
  - '...N'  = folder at index N
  - '...-N' = Nth most recent extraction
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

DEFAULT_MRU_DEPTH = 10
DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "notepad-cleanup"


def _clean_path(s: str) -> str:
    """Clean a path string: strip quotes, expand env vars, resolve to absolute.

    Used for storage -- preserves display case.
    """
    import os
    cleaned = s.strip().strip('"').strip("'")
    cleaned = os.path.expandvars(cleaned)  # %USERPROFILE%, $HOME, etc.
    cleaned = os.path.expanduser(cleaned)  # ~/...
    try:
        return str(Path(cleaned).resolve())
    except (OSError, ValueError):
        return cleaned


def _paths_equal(a: str, b: str) -> bool:
    """Compare two paths for equality, case-insensitive on Windows."""
    import sys
    pa = str(Path(a).resolve())
    pb = str(Path(b).resolve())
    if sys.platform == "win32":
        return pa.lower() == pb.lower()
    return pa == pb


def _is_too_broad(path_str: str) -> bool:
    """Check if a path is too broad to be a useful search dir.

    Rejects home dirs, drive roots, and system folders.
    """
    p = Path(path_str).resolve()
    # Drive root: C:\, D:\, etc.
    if p == p.anchor or str(p).rstrip("\\") == str(p.drive):
        return True
    # Home directory itself
    if p == Path.home():
        return True
    # Windows system dirs
    too_broad = {
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path("C:/Windows"),
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
    }
    if p in {tb.resolve() for tb in too_broad}:
        return True
    return False


class ConfigManager:
    """Manages notepad-cleanup configuration and folder registry."""

    def __init__(self, config_path: Path = None):
        self._config_path = config_path or (Path.home() / ".notepad-cleanup.json")

    @property
    def path(self) -> Path:
        return self._config_path

    # --- Low-level I/O ---

    def load(self) -> dict:
        """Load config from disk."""
        try:
            if self._config_path.exists():
                return json.loads(self._config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def save(self, config: dict):
        """Save config to disk."""
        try:
            self._config_path.write_text(
                json.dumps(config, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def get(self, key: str, default=None):
        """Get a single config value."""
        return self.load().get(key, default)

    def set(self, key: str, value):
        """Set a single config value."""
        config = self.load()
        config[key] = value
        self.save(config)

    def unset(self, key: str):
        """Remove a config key."""
        config = self.load()
        config.pop(key, None)
        self.save(config)

    # --- Migration ---

    def _migrate(self, config: dict) -> dict:
        """Migrate old output_dir/search_dirs format to unified folders."""
        if "folders" in config:
            return config

        folders = []
        search_indices = []

        old_output = config.pop("output_dir", None)
        if old_output:
            folders.append(_clean_path(old_output))

        old_search = config.pop("search_dirs", [])
        if isinstance(old_search, str):
            old_search = [old_search]
        for d in old_search:
            cleaned = _clean_path(d)
            existing_idx = next((i for i, f in enumerate(folders) if _paths_equal(f, cleaned)), None)
            if existing_idx is None:
                folders.append(cleaned)
                existing_idx = len(folders) - 1
            search_indices.append(existing_idx)

        if folders:
            config["folders"] = folders
            config["output_folder"] = 0
            if search_indices:
                config["search_folders"] = search_indices
            self.save(config)

        return config

    def _load_migrated(self) -> dict:
        """Load config with automatic migration."""
        return self._migrate(self.load())

    # --- Index resolution (shared by all folder operations) ---

    def resolve_index(self, ref, auto_add: bool = False) -> Optional[int]:
        """Resolve a folder reference to an integer index.

        Accepts:
          - int: used directly
          - "0", "1": parsed as int
          - "...": 0 (output folder)
          - "...N": N
          - path string: looked up in folder list

        If auto_add=True and ref is a valid path not in the list,
        it's added automatically and the new index is returned.

        Returns index or None if not found.
        """
        folders = self.get_folders()

        if isinstance(ref, int):
            return ref if 0 <= ref < len(folders) else None

        ref = str(ref)

        if ref.isdigit():
            idx = int(ref)
            return idx if 0 <= idx < len(folders) else None

        if ref == "...":
            return 0 if folders else None

        if ref.startswith("...") and not ref.startswith("...-"):
            try:
                idx = int(ref[3:])
                return idx if 0 <= idx < len(folders) else None
            except ValueError:
                return None

        # Path lookup (case-insensitive on Windows)
        cleaned = _clean_path(ref)
        for i, f in enumerate(folders):
            if _paths_equal(f, cleaned):
                return i

        # Auto-add if it's a valid path
        if auto_add and (Path(cleaned).exists() or Path(cleaned).parent.exists()):
            return self.add_folder(cleaned)

        return None

    def dots_label(self, index: int) -> str:
        """Get the ... label for a folder index."""
        return "..." if index == 0 else f"...{index}"

    # --- Folder registry ---

    def get_folders(self) -> list:
        """Get the folder list. Handles migration."""
        config = self._load_migrated()
        folders = config.get("folders", [])
        if isinstance(folders, str):
            folders = [folders]
        return folders

    def ensure_defaults(self):
        """Seed the folder list with the default output dir if empty.

        Called on first use so users always have at least one folder
        registered as ... (output).
        """
        config = self._load_migrated()
        folders = config.get("folders", [])
        if not folders:
            default = str(DEFAULT_OUTPUT_DIR)
            folders = [default]
            config["folders"] = folders
            config["output_folder"] = 0
            self.save(config)

    def add_folder(self, path: str) -> int:
        """Add a folder to the registry. Returns its index. No duplicates."""
        config = self._load_migrated()
        folders = config.get("folders", [])
        cleaned = _clean_path(path)

        # Case-insensitive duplicate check on Windows
        for i, f in enumerate(folders):
            if _paths_equal(f, cleaned):
                return i

        folders.append(cleaned)
        config["folders"] = folders

        if len(folders) == 1:
            config["output_folder"] = 0

        self.save(config)
        return len(folders) - 1

    def remove_folder(self, ref) -> Optional[str]:
        """Remove a folder by index, ... ref, or path.

        Returns the removed path, or None if not found.
        Adjusts output_folder and search_folders indices.
        """
        config = self._load_migrated()
        folders = config.get("folders", [])
        idx = self.resolve_index(ref)

        if idx is None or idx >= len(folders):
            return None

        removed = folders.pop(idx)
        config["folders"] = folders

        # Adjust output_folder
        output_idx = config.get("output_folder", 0)
        if idx == output_idx:
            config["output_folder"] = 0
        elif idx < output_idx:
            config["output_folder"] = output_idx - 1

        # Adjust search_folders
        search = config.get("search_folders", [])
        config["search_folders"] = [
            (si - 1 if si > idx else si)
            for si in search if si != idx
        ]

        self.save(config)
        return removed

    # --- Output folder ---

    def get_output_index(self) -> int:
        """Output folder is always index 0."""
        return 0

    def set_output_folder(self, ref) -> bool:
        """Set a folder as the output target, moving it to position 0.

        If ref is a path not yet in the folder list, it's auto-added first.
        """
        config = self._load_migrated()
        folders = config.get("folders", [])
        idx = self.resolve_index(ref, auto_add=True)

        if idx is None:
            return False

        # Re-read in case auto_add modified the config
        config = self._load_migrated()
        folders = config.get("folders", [])
        if idx == 0:
            return True  # Already output

        # Move to position 0
        folder_path = folders.pop(idx)
        folders.insert(0, folder_path)
        config["folders"] = folders
        config["output_folder"] = 0

        # Adjust search_folders: idx moved to 0, everything <idx shifts right
        search = config.get("search_folders", [])
        config["search_folders"] = [
            0 if si == idx else (si + 1 if si < idx else si)
            for si in search
        ]

        self.save(config)
        return True

    def get_output_dir(self) -> Path:
        """Get the output folder path. Falls back to default."""
        folders = self.get_folders()
        if folders:
            return Path(folders[0])
        return DEFAULT_OUTPUT_DIR

    def get_session_dir(self) -> Path:
        """Generate a timestamped output directory for a new extraction."""
        base = self.get_output_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        return base / f"nc-{timestamp}"

    # --- Search folders ---

    def get_search_indices(self) -> list:
        """Get indices of folders designated as search directories."""
        config = self._load_migrated()
        indices = config.get("search_folders", [])
        if isinstance(indices, int):
            indices = [indices]
        return indices

    def get_search_dirs(self) -> list:
        """Get paths of search-designated folders (only existing ones)."""
        folders = self.get_folders()
        return [folders[i] for i in self.get_search_indices()
                if i < len(folders) and Path(folders[i]).is_dir()]

    def add_search(self, ref) -> bool:
        """Add a folder to the search list by ref.

        If ref is a path not in the folder list, auto-adds it first.
        """
        idx = self.resolve_index(ref, auto_add=True)
        if idx is None:
            return False
        indices = self.get_search_indices()
        if idx not in indices:
            indices.append(idx)
            config = self._load_migrated()
            config["search_folders"] = indices
            self.save(config)
        return True

    def remove_search(self, ref) -> bool:
        """Remove a folder from the search list by ref."""
        idx = self.resolve_index(ref)
        if idx is None:
            return False
        indices = self.get_search_indices()
        if idx in indices:
            indices.remove(idx)
            config = self._load_migrated()
            config["search_folders"] = indices
            self.save(config)
            return True
        return False

    def clear_search(self):
        """Remove all folders from the search list."""
        config = self._load_migrated()
        config["search_folders"] = []
        self.save(config)

    # --- MRU (recent extractions) ---

    def get_mru(self) -> list:
        """Get the MRU list of recent extraction paths."""
        config = self.load()
        mru = config.get("last_extracts", [])
        if not isinstance(mru, list):
            mru = [mru] if mru else []
        # Backward compat with old single-value key
        if not mru:
            old = config.get("last_extract")
            if old:
                mru = [old]
        return mru

    def get_last_extract(self, depth: int = 1) -> Optional[Path]:
        """Get Nth most recent extraction. depth=1 is most recent."""
        mru = self.get_mru()
        idx = depth - 1
        if 0 <= idx < len(mru):
            p = Path(mru[idx])
            if p.exists() and p.is_dir():
                return p
        return None

    def push_extract(self, path: Path):
        """Push a new extraction onto the MRU list."""
        config = self.load()
        mru = config.get("last_extracts", [])
        if not isinstance(mru, list):
            mru = [mru] if mru else []

        # Migrate old single-value key
        old = config.pop("last_extract", None)
        if old and old not in mru:
            mru.insert(0, old)

        path_str = str(path)
        mru = [m for m in mru if m != path_str]  # Remove if already present
        mru.insert(0, path_str)  # Push to front

        max_depth = config.get("mru_depth", DEFAULT_MRU_DEPTH)
        config["last_extracts"] = mru[:max_depth]
        self.save(config)

    # --- ... expansion ---

    def expand_dots(self, path_str: str) -> str:
        """Expand ... notation in a path string.

        '...'   = output folder (folders[0])
        '...N'  = folder at index N
        '...-N' = Nth most recent extraction
        """
        if "..." not in path_str:
            return path_str

        config = self._load_migrated()
        folders = config.get("folders", [])
        mru = self.get_mru()

        def _replace(match):
            token = match.group(0)
            if token == "...":
                if folders:
                    return folders[0]
                return str(DEFAULT_OUTPUT_DIR)
            elif token.startswith("...-"):
                depth = abs(int(token[3:]))
                idx = depth - 1
                if 0 <= idx < len(mru):
                    return mru[idx]
                return token
            else:
                idx = int(token[3:])
                if idx < len(folders):
                    return folders[idx]
                return token

        expanded = re.sub(r"\.\.\.([-]?\d+)?", _replace, path_str)
        return str(Path(expanded).resolve())

    def resolve_path_value(self, value: str) -> str:
        """Clean and expand a path value for storage. Never stores '...'."""
        cleaned = value.strip().strip('"').strip("'")
        expanded = self.expand_dots(cleaned)
        return str(Path(expanded).resolve())

    def resolve_folder(self, folder_arg, use_last: bool = False) -> Optional[Path]:
        """Resolve extraction folder from argument or --last."""
        if folder_arg:
            expanded = self.expand_dots(str(folder_arg))
            return Path(expanded)
        if use_last:
            return self.get_last_extract()
        return None

    # --- Folder roles display ---

    def get_folder_roles(self, index: int) -> list:
        """Get the roles assigned to a folder by index."""
        roles = []
        if index == 0:
            roles.append("output")
        if index in self.get_search_indices():
            roles.append("search")
        return roles

    @staticmethod
    def shorten_path(path_str: str) -> str:
        """Shorten a path for display by replacing home dir with ~."""
        home = str(Path.home())
        if path_str.startswith(home):
            return "~" + path_str[len(home):]
        return path_str

    def format_search_list(self) -> list:
        """Get search dirs as (path, dots_label) tuples."""
        folders = self.get_folders()
        result = []
        for i in self.get_search_indices():
            if i < len(folders):
                result.append((folders[i], self.dots_label(i)))
        return result


# --- Module-level singleton ---
# All module-level functions delegate to this instance.
# Tests can replace it via _set_manager().

_manager = ConfigManager()


def _set_manager(mgr: ConfigManager):
    """Replace the global ConfigManager (for testing)."""
    global _manager
    _manager = mgr


def _get_config_path() -> Path:
    return _manager.path


# Convenience functions delegating to _manager

def load_config() -> dict:
    return _manager.load()

def save_config(config: dict):
    _manager.save(config)

def config_get(key, default=None):
    return _manager.get(key, default)

def config_set(key, value):
    _manager.set(key, value)

def config_unset(key):
    _manager.unset(key)

def get_folders():
    return _manager.get_folders()

def add_folder(path):
    return _manager.add_folder(path)

def remove_folder(ref):
    return _manager.remove_folder(ref)

def set_output_folder(ref):
    return _manager.set_output_folder(ref)

def get_output_folder_index():
    return _manager.get_output_index()

def get_search_folder_indices():
    return _manager.get_search_indices()

def get_search_dirs():
    return _manager.get_search_dirs()

def add_search_folder(ref):
    return _manager.add_search(ref)

def remove_search_folder(ref):
    return _manager.remove_search(ref)

def set_search_folders(indices):
    _manager.clear_search()
    config = _manager._load_migrated()
    config["search_folders"] = indices
    _manager.save(config)

def get_default_output_dir():
    return _manager.get_output_dir()

def get_output_dir_for_session():
    return _manager.get_session_dir()

def get_last_extract(depth=1):
    return _manager.get_last_extract(depth)

def set_last_extract(path):
    _manager.push_extract(path)

def get_mru_list():
    return _manager.get_mru()

def expand_dots(path_str):
    return _manager.expand_dots(path_str)

def resolve_path_value(value):
    return _manager.resolve_path_value(value)

def resolve_folder(folder_arg, use_last=False):
    return _manager.resolve_folder(folder_arg, use_last)

def shorten_path(path_str):
    return ConfigManager.shorten_path(str(path_str))
