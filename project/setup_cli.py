from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from project import __version__
from project.doctor import PROFILE_CHOICES, DoctorProfile
from project.paths import default_runtime_root

SetupStatus = Literal["pass", "skip", "fail"]

RUNTIME_ROOT = default_runtime_root()
RUNTIME_DIRECTORIES = (
    Path("storage"),
    Path("output"),
    Path("logs"),
    Path("models") / "faster-whisper",
)


@dataclass(frozen=True)
class SetupAction:
    id: str
    label: str
    status: SetupStatus
    message: str
    fix_command: str | None


@dataclass(frozen=True)
class SetupReport:
    schema_version: str
    ok: bool
    profile: DoctorProfile
    runtime_root: str
    actions: tuple[SetupAction, ...]
    next_command: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "profile": self.profile,
            "runtime_root": self.runtime_root,
            "actions": [asdict(action) for action in self.actions],
            "next_command": self.next_command,
        }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-setup",
        description="初始化 DouyinIngest 运行目录并安装 Playwright Chromium。",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default="core",
        help="完成后建议检查的能力范围（默认 core）",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="仅创建运行目录，不安装 Chromium",
    )
    parser.add_argument(
        "--with-deps",
        action="store_true",
        help="安装 Chromium 时同时请求 Playwright 安装 Linux 系统依赖",
    )
    parser.add_argument("--json", action="store_true", help="输出适合 Agent 解析的 JSON")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def perform_setup(
    profile: DoctorProfile,
    *,
    skip_browser: bool,
    with_deps: bool,
    capture_browser_output: bool = True,
    runtime_root: Path | None = None,
) -> SetupReport:
    root = (runtime_root or RUNTIME_ROOT).expanduser().resolve()
    actions = [_create_runtime_directories(root)]

    if skip_browser:
        actions.append(
            SetupAction(
                id="chromium",
                label="Playwright Chromium",
                status="skip",
                message="Browser installation was explicitly skipped.",
                fix_command=_format_command(_playwright_install_command(with_deps=False)),
            )
        )
    else:
        completed = _run_playwright_install(
            with_deps, capture_output=capture_browser_output
        )
        command = _format_command(_playwright_install_command(with_deps))
        if completed.returncode == 0:
            actions.append(
                SetupAction(
                    id="chromium",
                    label="Playwright Chromium",
                    status="pass",
                    message="Chromium installation completed or was already current.",
                    fix_command=None,
                )
            )
        else:
            stderr = completed.stderr or ""
            stdout = completed.stdout or ""
            output = stderr.strip() or stdout.strip() or "unknown error"
            details = output[-800:]
            actions.append(
                SetupAction(
                    id="chromium",
                    label="Playwright Chromium",
                    status="fail",
                    message=f"Chromium installation failed: {details}",
                    fix_command=command,
                )
            )

    ok = all(action.status != "fail" for action in actions)
    next_command = _format_command(
        [sys.executable, "-m", "project.main", "doctor", "--profile", profile]
    )
    return SetupReport(
        schema_version="1.0",
        ok=ok,
        profile=profile,
        runtime_root=str(root),
        actions=tuple(actions),
        next_command=next_command,
    )


def format_text(report: SetupReport) -> str:
    lines = [
        f"DouyinIngest setup ({report.profile})",
        f"Runtime: {report.runtime_root}",
        "",
    ]
    for action in report.actions:
        lines.append(f"[{action.status.upper():4}] {action.label}")
        lines.append(f"       {action.message}")
        if action.fix_command:
            lines.append(f"       Fix: {action.fix_command}")
    lines.extend(
        (
            "",
            f"Next: {report.next_command}",
            "Result: ready" if report.ok else "Result: setup failed",
        )
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.skip_browser and args.with_deps:
        parser.error("--skip-browser 不能与 --with-deps 同时使用")
    profile = cast(DoctorProfile, args.profile)
    report = perform_setup(
        profile,
        skip_browser=bool(args.skip_browser),
        with_deps=bool(args.with_deps),
        capture_browser_output=bool(args.json),
    )
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, separators=(",", ":")))
    else:
        print(format_text(report))
    return 0 if report.ok else 1


def run() -> None:
    raise SystemExit(main())


def _create_runtime_directories(runtime_root: Path) -> SetupAction:
    try:
        for relative in RUNTIME_DIRECTORIES:
            (runtime_root / relative).mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return SetupAction(
            id="runtime_directories",
            label="Runtime directories",
            status="fail",
            message=f"Could not initialize {runtime_root}: {error}",
            fix_command=f"Check write permissions for {runtime_root}",
        )
    return SetupAction(
        id="runtime_directories",
        label="Runtime directories",
        status="pass",
        message=f"Runtime directories are ready under {runtime_root}.",
        fix_command=None,
    )


def _playwright_install_command(with_deps: bool) -> list[str]:
    command = [sys.executable, "-m", "playwright", "install"]
    if with_deps:
        command.append("--with-deps")
    command.append("chromium")
    return command


def _run_playwright_install(
    with_deps: bool, *, capture_output: bool
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _playwright_install_command(with_deps),
        capture_output=capture_output,
        text=True,
        check=False,
    )


def _format_command(command: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


if __name__ == "__main__":
    run()
