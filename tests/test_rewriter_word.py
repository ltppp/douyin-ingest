from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[1]
SKILL_DIRECTORY = REPOSITORY_ROOT / "skills" / "douyin-script-rewriter"
WORD_BUILDER = SKILL_DIRECTORY / "scripts" / "build_word.py"


def load_word_builder() -> ModuleType:
    pytest.importorskip("docx")
    spec = importlib.util.spec_from_file_location("douyin_script_rewriter_build_word", WORD_BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_rewrite_run(tmp_path: Path, *, count: int = 10) -> Path:
    run = tmp_path / "20260714-120000"
    videos: list[dict[str, object]] = []

    for rank in range(1, count + 1):
        video_directory = run / "videos" / str(rank)
        video_directory.mkdir(parents=True)
        clean_file = video_directory / "transcript_clean.txt"
        rewrite_file = video_directory / "rewrite.md"
        clean_file.write_text(f"第 {rank} 条 AI 校正版逐字稿。\n第二段内容。\n", encoding="utf-8")
        rewrite_file.write_text(
            f"# 原创口播稿\n\n第 {rank} 条原创口播稿。\n新的收束内容。\n",
            encoding="utf-8",
        )
        videos.append(
            {
                "aweme_id": str(rank),
                "title": f"测试标题 {rank}",
                "source_url": f"https://www.douyin.com/video/{rank}",
                "digg_count": 100_000 - rank,
                "rank": rank,
                "status": "success",
                "quality_grade": "usable",
                "clean_transcript_file": str(clean_file),
                "rewrite_file": str(rewrite_file),
                "error": None,
            }
        )

    result = {
        "schema_version": "1.1",
        "status": "success",
        "source": {
            "collection_mode": "profile",
            "account_name": "测试账号",
            "selection_limit": count,
        },
        "videos": videos,
        "report_file": str(run / "report.md"),
    }
    (run / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run / "report.md").write_text(
        "# 测试账号的热门视频改写结果\n\n**状态：已完成**\n",
        encoding="utf-8",
    )
    return run


def test_rewriter_skill_is_repository_portable() -> None:
    skill_file = SKILL_DIRECTORY / "SKILL.md"
    assert skill_file.is_file()
    assert (SKILL_DIRECTORY / "references" / "word-deliverable.md").is_file()
    assert WORD_BUILDER.is_file()

    skill_source = skill_file.read_text(encoding="utf-8")
    assert "$douyin-content-ingest" not in skill_source

    builder_source = WORD_BUILDER.read_text(encoding="utf-8")
    for forbidden in (
        ".cache/codex-runtimes",
        "Codex workspace dependencies",
        "CODEX_HOME",
        "/Users/",
        "sys.path.insert",
    ):
        assert forbidden not in builder_source
    assert "pip install 'douyin-ingest[word]'" in builder_source


def test_fixed_word_template_builds_and_verifies_top10(tmp_path: Path) -> None:
    builder = load_word_builder()
    run = create_rewrite_run(tmp_path)
    result = builder.load_result(run)
    output = builder.default_output_path(run, result)

    builder.build_document(run, result, output)
    summary = builder.verify_document(result, output)
    builder.record_deliverable(run, result, output)
    builder.record_deliverable(run, result, output)

    assert output.name == "测试账号-Top10内容改写-简洁版.docx"
    assert summary["ok"] is True
    assert summary["template_version"] == "douyin-script-rewriter-word-v1"
    assert summary["video_count"] == 10
    assert summary["source_links"] == 10
    assert summary["clean_sections"] == 10
    assert summary["rewrite_sections"] == 10

    recorded = json.loads((run / "result.json").read_text(encoding="utf-8"))
    assert recorded["word_file"] == str(output.resolve())
    assert recorded["word_template_version"] == "douyin-script-rewriter-word-v1"
    report = (run / "report.md").read_text(encoding="utf-8")
    assert report.count("**Word 版：") == 1
    assert output.name in report

    completed = subprocess.run(
        [
            sys.executable,
            str(WORD_BUILDER),
            "--run",
            str(run),
            "--output",
            str(output),
            "--verify-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    cli_summary = json.loads(completed.stdout)
    assert cli_summary["ok"] is True
    assert cli_summary["video_count"] == 10


def test_word_verifier_rejects_contract_drift(tmp_path: Path) -> None:
    builder = load_word_builder()
    run = create_rewrite_run(tmp_path)
    result = builder.load_result(run)
    output = builder.default_output_path(run, result)
    builder.build_document(run, result, output)

    result["videos"][0]["source_url"] = "https://www.douyin.com/video/changed"

    with pytest.raises(ValueError, match="原视频链接不匹配"):
        builder.verify_document(result, output)
