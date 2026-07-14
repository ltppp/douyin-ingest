from __future__ import annotations

import tomllib
from pathlib import Path


def test_optional_dependency_profiles_are_complete() -> None:
    project_root = Path(__file__).parents[1]
    payload = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert payload["project"]["version"] == "0.3.0"
    extras = payload["project"]["optional-dependencies"]

    assert any(dependency.startswith("faster-whisper") for dependency in extras["transcribe"])
    assert any(dependency.startswith("python-docx") for dependency in extras["word"])
    assert any(dependency.startswith("faster-whisper") for dependency in extras["agent"])
    assert any(dependency.startswith("python-docx") for dependency in extras["agent"])

    scripts = payload["project"]["scripts"]
    assert scripts["douyin-setup"] == "project.setup_cli:run"
