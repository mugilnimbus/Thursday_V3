"""Where services keep their data and logs: outside the repository, per user."""

import os
import pathlib
import sys

APP_DIR_NAME = "Thursday"


def data_root(configured: str = "") -> pathlib.Path:
    """The configured folder, or the platform's per-user application data folder."""
    if configured:
        return pathlib.Path(configured).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
        return pathlib.Path(base) / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(pathlib.Path.home() / ".local" / "share")
    return pathlib.Path(base) / APP_DIR_NAME.lower()


def service_data_dir(service: str, configured: str = "") -> pathlib.Path:
    path = data_root(configured) / "services" / service
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir(configured: str = "") -> pathlib.Path:
    path = data_root(configured) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
