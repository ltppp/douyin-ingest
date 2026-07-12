from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent.parent


def default_runtime_root(
    *,
    environ: Mapping[str, str] | None = None,
    system: str | None = None,
    home: Path | None = None,
    source_root: Path = SOURCE_ROOT,
) -> Path:
    values = os.environ if environ is None else environ
    override = values.get("DOUYIN_INGEST_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if (source_root / "pyproject.toml").is_file():
        return source_root

    user_home = home or Path.home()
    current_system = (system or platform.system()).lower()
    if current_system == "darwin":
        return user_home / "Library" / "Application Support" / "douyin-ingest"
    if current_system == "windows":
        local_app_data = values.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return base / "douyin-ingest"
    xdg_data_home = values.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else user_home / ".local" / "share"
    return base / "douyin-ingest"
