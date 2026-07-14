from __future__ import annotations

from pathlib import Path


def test_readme_leads_with_runnable_quick_start() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert readme.index("## 快速开始") < readme.index("## 架构")
    assert "douyin-ingest[agent] @ git+https://github.com/ltppp/douyin-ingest.git" in readme
    assert "pip install -e '.[dev,agent]'" in readme
    assert "douyin-ingest setup" in readme
    assert "douyin-ingest doctor --profile agent" in readme
    assert "npx skills add https://github.com/ltppp/douyin-ingest" in readme
