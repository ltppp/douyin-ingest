from __future__ import annotations

from project.paths import default_runtime_root


def test_runtime_root_uses_source_checkout(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "pyproject.toml").touch()

    assert default_runtime_root(environ={}, source_root=source_root) == source_root


def test_runtime_root_honors_explicit_override(tmp_path) -> None:
    override = tmp_path / "runtime"

    assert default_runtime_root(
        environ={"DOUYIN_INGEST_HOME": str(override)},
        source_root=tmp_path / "installed-package",
    ) == override


def test_installed_runtime_root_is_user_writable_on_each_platform(tmp_path) -> None:
    installed = tmp_path / "site-packages"
    home = tmp_path / "home"

    assert default_runtime_root(
        environ={}, system="Darwin", home=home, source_root=installed
    ) == home / "Library" / "Application Support" / "douyin-ingest"
    assert default_runtime_root(
        environ={}, system="Linux", home=home, source_root=installed
    ) == home / ".local" / "share" / "douyin-ingest"
    assert default_runtime_root(
        environ={"LOCALAPPDATA": str(tmp_path / "local")},
        system="Windows",
        home=home,
        source_root=installed,
    ) == tmp_path / "local" / "douyin-ingest"
