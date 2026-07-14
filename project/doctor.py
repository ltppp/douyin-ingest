from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from time import time as epoch_time
from typing import Literal, cast

from project import __version__
from project.paths import SOURCE_ROOT, default_runtime_root

CheckStatus = Literal["pass", "warn", "fail"]
PlatformName = Literal["linux", "macos", "windows", "unknown"]
DoctorProfile = Literal["core", "media", "transcribe", "word", "agent"]

PROFILE_CHOICES: tuple[DoctorProfile, ...] = (
    "core",
    "media",
    "transcribe",
    "word",
    "agent",
)

RUNTIME_ROOT = default_runtime_root()
AUTH_COOKIE_NAMES = frozenset({"sessionid", "sessionid_ss", "sid_guard", "uid_tt", "uid_tt_ss"})
CORE_PACKAGES = (
    ("anyio", "anyio"),
    ("httpx", "httpx"),
    ("loguru", "loguru"),
    ("playwright", "playwright"),
    ("pydantic", "pydantic"),
)


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    label: str
    status: CheckStatus
    required: bool
    version: str | None
    message: str
    fix_command: str | None


@dataclass(frozen=True)
class DoctorReport:
    schema_version: str
    ok: bool
    profile: DoctorProfile
    platform: PlatformName
    python_executable: str
    runtime_root: str
    checks: tuple[DoctorCheck, ...]

    def to_dict(self) -> dict[str, object]:
        counts = {status: 0 for status in ("pass", "warn", "fail")}
        for check in self.checks:
            counts[check.status] += 1
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "profile": self.profile,
            "platform": self.platform,
            "python_executable": self.python_executable,
            "runtime_root": self.runtime_root,
            "summary": counts,
            "checks": [asdict(check) for check in self.checks],
        }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-doctor",
        description="检查 DouyinIngest 的 Python、浏览器、媒体工具和登录环境。",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default="core",
        help="检查 core、media、transcribe、word 或完整 agent 能力（默认 core）",
    )
    parser.add_argument("--json", action="store_true", help="输出适合 Agent 解析的 JSON")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def run_checks(
    profile: DoctorProfile = "core", *, runtime_root: Path | None = None
) -> DoctorReport:
    current_platform = detect_platform()
    root = (runtime_root or RUNTIME_ROOT).expanduser().resolve()
    python_extra = profile if profile in {"transcribe", "word", "agent"} else None
    install_core = _pip_install_command(python_extra)
    media_required = profile in {"media", "transcribe", "agent"}
    transcribe_required = profile in {"transcribe", "agent"}
    word_required = profile in {"word", "agent"}
    checks = [
        _check_python(current_platform),
        _check_runtime_directories(root),
        *(
            _check_package(
                distribution,
                import_name,
                required=True,
                fix_command=install_core,
            )
            for distribution, import_name in CORE_PACKAGES
        ),
        _check_chromium(required=profile != "word"),
        _check_executable(
            "ffmpeg", required=media_required, current_platform=current_platform
        ),
        _check_executable(
            "ffprobe", required=media_required, current_platform=current_platform
        ),
        _check_login_state(root / "storage" / "storage_state.json"),
        _check_package(
            "faster-whisper",
            "faster_whisper",
            required=transcribe_required,
            fix_command=_pip_install_command("agent" if profile == "agent" else "transcribe"),
        ),
        _check_package(
            "python-docx",
            "docx",
            required=word_required,
            fix_command=_pip_install_command("agent" if profile == "agent" else "word"),
        ),
    ]
    ok = all(check.status != "fail" for check in checks if check.required)
    return DoctorReport(
        schema_version="1.1",
        ok=ok,
        profile=profile,
        platform=current_platform,
        python_executable=sys.executable,
        runtime_root=str(root),
        checks=tuple(checks),
    )


def detect_platform(system: str | None = None) -> PlatformName:
    name = (system or platform.system()).lower()
    if name == "darwin":
        return "macos"
    if name == "linux":
        return "linux"
    if name == "windows":
        return "windows"
    return "unknown"


def format_text(report: DoctorReport) -> str:
    lines = [
        f"DouyinIngest doctor ({report.platform})",
        f"Profile: {report.profile}",
        f"Python: {report.python_executable}",
        f"Runtime: {report.runtime_root}",
        "",
    ]
    for check in report.checks:
        required = "required" if check.required else "optional"
        version = f" ({check.version})" if check.version else ""
        lines.append(f"[{check.status.upper():4}] {check.label}{version} [{required}]")
        lines.append(f"       {check.message}")
        if check.fix_command:
            lines.append(f"       Fix: {check.fix_command}")
    lines.extend(("", "Result: ready" if report.ok else "Result: required checks failed"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    profile = cast(DoctorProfile, args.profile)
    report = run_checks(profile)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, separators=(",", ":")))
    else:
        print(format_text(report))
    return 0 if report.ok else 1


def run() -> None:
    raise SystemExit(main())


def _check_python(current_platform: PlatformName) -> DoctorCheck:
    version = platform.python_version()
    supported = sys.version_info >= (3, 12)
    return DoctorCheck(
        id="python",
        label="Python",
        status="pass" if supported else "fail",
        required=True,
        version=version,
        message="Python 3.12 or newer is available." if supported else "Python 3.12+ is required.",
        fix_command=None if supported else _python_install_hint(current_platform),
    )


def _check_runtime_directories(runtime_root: Path) -> DoctorCheck:
    required_directories = tuple(
        runtime_root / relative for relative in ("storage", "output", "logs")
    )
    missing = [path for path in required_directories if not path.is_dir()]
    not_writable = [
        path for path in required_directories if path.is_dir() and not os.access(path, os.W_OK)
    ]
    ready = not missing and not not_writable
    problems: list[str] = []
    if missing:
        problems.append("missing: " + ", ".join(str(path) for path in missing))
    if not_writable:
        problems.append("not writable: " + ", ".join(str(path) for path in not_writable))
    return DoctorCheck(
        id="runtime_directories",
        label="Runtime directories",
        status="pass" if ready else "fail",
        required=True,
        version=None,
        message=(
            f"Runtime directories are writable under {runtime_root}."
            if ready
            else "Runtime directories are not ready (" + "; ".join(problems) + ")."
        ),
        fix_command=(
            None
            if ready
            else _python_command("-m", "project.main", "setup", "--skip-browser")
        ),
    )


def _check_package(
    distribution: str,
    import_name: str,
    *,
    required: bool,
    fix_command: str,
) -> DoctorCheck:
    version = _installed_package_version(distribution, import_name)
    available = version is not None
    status: CheckStatus = "pass" if available else ("fail" if required else "warn")
    return DoctorCheck(
        id=f"package:{distribution}",
        label=distribution,
        status=status,
        required=required,
        version=version,
        message=(
            "Package is importable." if available else "Package is not installed or importable."
        ),
        fix_command=None if available else fix_command,
    )


def _installed_package_version(distribution: str, import_name: str) -> str | None:
    try:
        importlib.import_module(import_name)
        return metadata.version(distribution)
    except Exception:
        return None


def _check_chromium(*, required: bool = True) -> DoctorCheck:
    fix_command = _python_command("-m", "playwright", "install", "chromium")
    failure_status: CheckStatus = "fail" if required else "warn"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
            if not executable.is_file():
                return DoctorCheck(
                    id="chromium",
                    label="Playwright Chromium",
                    status=failure_status,
                    required=required,
                    version=None,
                    message=f"Chromium executable is missing: {executable}",
                    fix_command=fix_command,
                )
            version = _run_version_command(executable, "--version")
            if version is None:
                return DoctorCheck(
                    id="chromium",
                    label="Playwright Chromium",
                    status=failure_status,
                    required=required,
                    version=None,
                    message=f"Chromium exists but could not be executed: {executable}",
                    fix_command=fix_command,
                )
            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        return DoctorCheck(
            id="chromium",
            label="Playwright Chromium",
            status=failure_status,
            required=required,
            version=None,
            message=f"Could not launch Chromium: {exc}",
            fix_command=fix_command,
        )
    return DoctorCheck(
        id="chromium",
        label="Playwright Chromium",
        status="pass",
        required=required,
        version=version,
        message=f"Chromium launched successfully: {executable}",
        fix_command=None,
    )


def _check_executable(
    name: Literal["ffmpeg", "ffprobe"],
    *,
    required: bool,
    current_platform: PlatformName,
) -> DoctorCheck:
    executable = shutil.which(name)
    if executable is None:
        return DoctorCheck(
            id=name,
            label=name,
            status="fail" if required else "warn",
            required=required,
            version=None,
            message=f"{name} is not on PATH; speech audio materialization may be unavailable.",
            fix_command=_ffmpeg_install_hint(current_platform),
        )
    version = _run_version_command(Path(executable), "-version")
    if version is None:
        return DoctorCheck(
            id=name,
            label=name,
            status="fail" if required else "warn",
            required=required,
            version=None,
            message=f"{name} is on PATH but could not be executed: {executable}",
            fix_command=_ffmpeg_install_hint(current_platform),
        )
    return DoctorCheck(
        id=name,
        label=name,
        status="pass",
        required=required,
        version=version,
        message=f"Executable found: {executable}",
        fix_command=None,
    )


def _check_login_state(path: Path) -> DoctorCheck:
    valid = _storage_state_has_session(path)
    return DoctorCheck(
        id="login_state",
        label="Douyin login state",
        status="pass" if valid else "warn",
        required=False,
        version=None,
        message=(
            f"Valid saved session found: {path}"
            if valid
            else f"No valid saved session found: {path}"
        ),
        fix_command=(
            None
            if valid
            else _python_command(
                "-m", "project.main", "https://www.douyin.com/user/xxx", "--force-login"
            )
        ),
    )


def _storage_state_has_session(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    if not isinstance(cookies, list):
        return False
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name", "")).lower()
        value = cookie.get("value")
        domain = str(cookie.get("domain", "")).lower().lstrip(".")
        expires = cookie.get("expires")
        domain_valid = domain == "douyin.com" or domain.endswith(".douyin.com")
        expiry_valid = (
            not isinstance(expires, (int, float)) or expires <= 0 or expires > epoch_time()
        )
        if (
            name in AUTH_COOKIE_NAMES
            and isinstance(value, str)
            and value
            and domain_valid
            and expiry_valid
        ):
            return True
    return False


def _run_version_command(executable: Path, argument: str) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), argument],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else None


def _python_command(*arguments: str) -> str:
    parts = [sys.executable, *arguments]
    if detect_platform() == "windows":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _pip_install_command(extra: str | None = None) -> str:
    if (SOURCE_ROOT / "pyproject.toml").is_file():
        target = f"{SOURCE_ROOT}[{extra}]" if extra else str(SOURCE_ROOT)
        return _python_command("-m", "pip", "install", "-e", target)
    target = f"douyin-ingest[{extra}]" if extra else "douyin-ingest"
    return _python_command("-m", "pip", "install", target)


def _python_install_hint(current_platform: PlatformName) -> str:
    if current_platform == "macos":
        return "brew install python@3.12"
    if current_platform == "linux":
        return "sudo apt-get install -y python3.12 python3.12-venv"
    if current_platform == "windows":
        return "winget install --id Python.Python.3.12 -e"
    return "Install Python 3.12+ from https://www.python.org/downloads/"


def _ffmpeg_install_hint(current_platform: PlatformName) -> str:
    if current_platform == "macos":
        return "brew install ffmpeg"
    if current_platform == "linux":
        return "sudo apt-get update && sudo apt-get install -y ffmpeg"
    if current_platform == "windows":
        return "winget install --id Gyan.FFmpeg -e"
    return "Install FFmpeg and ensure ffmpeg and ffprobe are on PATH."


if __name__ == "__main__":
    run()
