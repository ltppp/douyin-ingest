from __future__ import annotations

import project.main as main_module


def test_dispatch_routes_setup_and_doctor(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "setup_main", lambda args: 10 if args == ["--json"] else 99)
    monkeypatch.setattr(
        main_module,
        "doctor_main",
        lambda args: 20 if args == ["--profile", "agent"] else 99,
    )

    assert main_module.dispatch(["setup", "--json"]) == 10
    assert main_module.dispatch(["doctor", "--profile", "agent"]) == 20


def test_dispatch_leaves_existing_crawl_arguments_unchanged() -> None:
    assert main_module.dispatch(["https://v.douyin.com/example/", "--json"]) is None
    assert main_module.dispatch(["--help"]) is None
