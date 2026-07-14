from __future__ import annotations

import json
import subprocess
import sys

import project.setup_cli as setup_cli


def test_setup_creates_runtime_directories_and_installs_chromium(
    monkeypatch, tmp_path, capsys
) -> None:
    runtime_root = tmp_path / "runtime"
    calls: list[tuple[bool, bool]] = []

    def fake_install(
        with_deps: bool, *, capture_output: bool
    ) -> subprocess.CompletedProcess[str]:
        calls.append((with_deps, capture_output))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(setup_cli, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(setup_cli, "_run_playwright_install", fake_install)

    assert setup_cli.main(["--profile", "agent"]) == 0
    assert calls == [(False, False)]
    for relative in ("storage", "output", "logs", "models/faster-whisper"):
        assert (runtime_root / relative).is_dir()
    output = capsys.readouterr().out
    assert "Result: ready" in output
    assert "doctor --profile agent" in output


def test_setup_is_idempotent_and_can_skip_browser(monkeypatch, tmp_path, capsys) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(setup_cli, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(
        setup_cli,
        "_run_playwright_install",
        lambda with_deps, *, capture_output: (_ for _ in ()).throw(
            AssertionError("browser install must be skipped")
        ),
    )

    assert setup_cli.main(["--skip-browser", "--json"]) == 0
    assert setup_cli.main(["--skip-browser", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["ok"] is True
    assert payload["actions"][1]["id"] == "chromium"
    assert payload["actions"][1]["status"] == "skip"


def test_setup_json_reports_browser_install_failure(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(setup_cli, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(
        setup_cli,
        "_run_playwright_install",
        lambda with_deps, *, capture_output: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="download failed"
        ),
    )

    assert setup_cli.main(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.0"
    assert payload["ok"] is False
    chromium = payload["actions"][1]
    assert chromium["status"] == "fail"
    assert "playwright install chromium" in chromium["fix_command"]
    assert "download failed" in chromium["message"]


def test_playwright_with_deps_command_uses_current_python(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run(command, **kwargs):
        captured.append(command)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(setup_cli.subprocess, "run", fake_run)

    setup_cli._run_playwright_install(with_deps=True, capture_output=True)

    assert captured == [
        [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"]
    ]
