from __future__ import annotations

import sys
from collections.abc import Sequence

from project.cli import run as crawl_run
from project.doctor import main as doctor_main
from project.setup_cli import main as setup_main


def dispatch(argv: Sequence[str]) -> int | None:
    if argv and argv[0] == "setup":
        return setup_main(list(argv[1:]))
    if argv and argv[0] == "doctor":
        return doctor_main(list(argv[1:]))
    return None


def run() -> None:
    result = dispatch(sys.argv[1:])
    if result is None:
        crawl_run()
    raise SystemExit(result)

if __name__ == "__main__":
    run()
