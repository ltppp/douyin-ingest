from __future__ import annotations

import json
import subprocess

import pytest

import project.doctor as doctor
from project.doctor import DoctorCheck, DoctorReport


def _report(*checks: DoctorCheck) -> DoctorReport:
    return DoctorReport(
        schema_version="1.1",
        ok=all(check.status != "fail" for check in checks if check.required),
        profile="core",
        platform="linux",
        python_executable="/venv/bin/python",
        runtime_root="/runtime",
        checks=checks,
    )


def test_main_json_emits_machine_readable_report(monkeypatch, capsys) -> None:
    report = _report(
        DoctorCheck("python", "Python", "pass", True, "3.12.4", "ready", None),
        DoctorCheck(
            "package:faster-whisper",
            "faster-whisper",
            "warn",
            False,
            None,
            "optional",
            "python -m pip install -e '.[transcribe]'",
        ),
    )
    monkeypatch.setattr(doctor, "run_checks", lambda profile: report)

    assert doctor.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.1"
    assert payload["profile"] == "core"
    assert payload["runtime_root"] == "/runtime"
    assert payload["ok"] is True
    assert payload["summary"] == {"pass": 1, "warn": 1, "fail": 0}
    assert payload["checks"][1]["required"] is False
    assert payload["checks"][1]["fix_command"].endswith("'.[transcribe]'")


def test_main_returns_nonzero_when_required_check_fails(monkeypatch, capsys) -> None:
    report = _report(
        DoctorCheck(
            "chromium",
            "Playwright Chromium",
            "fail",
            True,
            None,
            "missing",
            "python -m playwright install chromium",
        )
    )
    monkeypatch.setattr(doctor, "run_checks", lambda profile: report)

    assert doctor.main(["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_package_check_reports_version_or_fix(monkeypatch) -> None:
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: object())
    monkeypatch.setattr(doctor.metadata, "version", lambda name: "1.2.3")
    installed = doctor._check_package("example", "example", required=True, fix_command="install")
    assert installed.status == "pass"
    assert installed.version == "1.2.3"
    assert installed.fix_command is None

    def fail_import(name):
        raise ImportError(name)

    monkeypatch.setattr(doctor.importlib, "import_module", fail_import)
    missing = doctor._check_package("example", "example", required=False, fix_command="install")
    assert missing.status == "warn"
    assert missing.version is None
    assert missing.fix_command == "install"


@pytest.mark.parametrize(
    ("system", "expected"),
    [("Darwin", "macos"), ("Linux", "linux"), ("Windows", "windows"), ("Plan9", "unknown")],
)
def test_detect_platform(system, expected) -> None:
    assert doctor.detect_platform(system) == expected


@pytest.mark.parametrize(
    ("current_platform", "expected"),
    [
        ("macos", "brew install ffmpeg"),
        ("linux", "apt-get install -y ffmpeg"),
        ("windows", "winget install --id Gyan.FFmpeg -e"),
    ],
)
def test_ffmpeg_install_hints_are_actionable(current_platform, expected) -> None:
    assert expected in doctor._ffmpeg_install_hint(current_platform)


def test_login_state_check_accepts_unexpired_douyin_cookie(tmp_path) -> None:
    state_path = tmp_path / "storage_state.json"
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "sessionid",
                        "value": "secret",
                        "domain": ".douyin.com",
                        "expires": -1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    check = doctor._check_login_state(state_path)
    assert check.status == "pass"
    assert check.fix_command is None


def test_login_state_check_reports_relogin_command(tmp_path) -> None:
    check = doctor._check_login_state(tmp_path / "missing.json")
    assert check.status == "warn"
    assert check.required is False
    assert check.fix_command and "--force-login" in check.fix_command


def test_executable_check_reports_detected_version(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version_command", lambda executable, argument: "8.0")

    check = doctor._check_executable("ffprobe", required=False, current_platform="linux")
    assert check.status == "pass"
    assert check.version == "8.0"
    assert check.fix_command is None


def test_executable_check_warns_when_binary_cannot_run(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version_command", lambda executable, argument: None)

    check = doctor._check_executable("ffmpeg", required=False, current_platform="linux")
    assert check.status == "warn"
    assert check.version is None
    assert check.fix_command and "apt-get" in check.fix_command


def test_version_command_rejects_nonzero_exit(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "tool"
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=[], returncode=1, stderr="broken"),
    )

    assert doctor._run_version_command(executable, "--version") is None


def test_agent_profile_requires_full_pipeline_dependencies(monkeypatch, tmp_path) -> None:
    required_by_id: dict[str, bool] = {}

    def check(identifier: str, required: bool = True) -> DoctorCheck:
        required_by_id[identifier] = required
        return DoctorCheck(identifier, identifier, "pass", required, "1", "ready", None)

    monkeypatch.setattr(doctor, "_check_python", lambda platform: check("python"))
    monkeypatch.setattr(doctor, "_check_runtime_directories", lambda root: check("runtime"))
    monkeypatch.setattr(
        doctor, "_check_chromium", lambda *, required: check("chromium", required)
    )
    monkeypatch.setattr(
        doctor,
        "_check_executable",
        lambda name, *, required, current_platform: check(name, required),
    )
    monkeypatch.setattr(doctor, "_check_login_state", lambda path: check("login_state", False))
    monkeypatch.setattr(
        doctor,
        "_check_package",
        lambda distribution, import_name, *, required, fix_command: check(
            f"package:{distribution}", required
        ),
    )

    report = doctor.run_checks("agent", runtime_root=tmp_path)

    assert report.profile == "agent"
    for identifier in (
        "ffmpeg",
        "ffprobe",
        "package:faster-whisper",
        "package:python-docx",
    ):
        assert required_by_id[identifier] is True


def test_core_profile_keeps_pipeline_extensions_optional(monkeypatch, tmp_path) -> None:
    required_by_id: dict[str, bool] = {}

    def check(identifier: str, required: bool = True) -> DoctorCheck:
        required_by_id[identifier] = required
        return DoctorCheck(identifier, identifier, "pass", required, "1", "ready", None)

    monkeypatch.setattr(doctor, "_check_python", lambda platform: check("python"))
    monkeypatch.setattr(doctor, "_check_runtime_directories", lambda root: check("runtime"))
    monkeypatch.setattr(
        doctor, "_check_chromium", lambda *, required: check("chromium", required)
    )
    monkeypatch.setattr(
        doctor,
        "_check_executable",
        lambda name, *, required, current_platform: check(name, required),
    )
    monkeypatch.setattr(doctor, "_check_login_state", lambda path: check("login_state", False))
    monkeypatch.setattr(
        doctor,
        "_check_package",
        lambda distribution, import_name, *, required, fix_command: check(
            f"package:{distribution}", required
        ),
    )

    doctor.run_checks("core", runtime_root=tmp_path)

    for identifier in (
        "ffmpeg",
        "ffprobe",
        "package:faster-whisper",
        "package:python-docx",
    ):
        assert required_by_id[identifier] is False


def test_word_profile_does_not_require_browser_or_media(monkeypatch, tmp_path) -> None:
    required_by_id: dict[str, bool] = {}

    def check(identifier: str, required: bool = True) -> DoctorCheck:
        required_by_id[identifier] = required
        return DoctorCheck(identifier, identifier, "pass", required, "1", "ready", None)

    monkeypatch.setattr(doctor, "_check_python", lambda platform: check("python"))
    monkeypatch.setattr(doctor, "_check_runtime_directories", lambda root: check("runtime"))
    monkeypatch.setattr(
        doctor, "_check_chromium", lambda *, required: check("chromium", required)
    )
    monkeypatch.setattr(
        doctor,
        "_check_executable",
        lambda name, *, required, current_platform: check(name, required),
    )
    monkeypatch.setattr(doctor, "_check_login_state", lambda path: check("login_state", False))
    monkeypatch.setattr(
        doctor,
        "_check_package",
        lambda distribution, import_name, *, required, fix_command: check(
            f"package:{distribution}", required
        ),
    )

    doctor.run_checks("word", runtime_root=tmp_path)

    assert required_by_id["chromium"] is False
    assert required_by_id["ffmpeg"] is False
    assert required_by_id["ffprobe"] is False
    assert required_by_id["package:faster-whisper"] is False
    assert required_by_id["package:python-docx"] is True


def test_runtime_directory_check_points_to_setup_when_missing(tmp_path) -> None:
    check = doctor._check_runtime_directories(tmp_path / "missing")

    assert check.status == "fail"
    assert check.required is True
    assert check.fix_command and "setup --skip-browser" in check.fix_command
