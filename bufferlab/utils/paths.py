"""Per-user data locations (no third-party dependency).

Override everything with the ``BUFFERLAB_HOME`` environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("BUFFERLAB_HOME")
    if override:
        base = Path(override).expanduser()
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "BufferLab"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "BufferLab"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "bufferlab"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "bufferlab.sqlite3"


def exports_dir() -> Path:
    p = data_dir() / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    return data_dir() / "settings.json"


def log_path() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p / "bufferlab.log"
