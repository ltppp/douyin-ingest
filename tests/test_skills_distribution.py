from __future__ import annotations

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]
SKILLS_DIRECTORY = REPOSITORY_ROOT / "skills"
EXPECTED_SKILLS = {"douyin-content-ingest", "douyin-script-rewriter"}


def skill_name(skill_file: Path) -> str:
    source = skill_file.read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*([^\n]+)$", source)
    assert match is not None, f"missing name in {skill_file}"
    return match.group(1).strip()


def skill_description(skill_file: Path) -> str:
    source = skill_file.read_text(encoding="utf-8")
    match = re.search(r"(?m)^description:\s*([^\n]+)$", source)
    assert match is not None, f"missing description in {skill_file}"
    return match.group(1).strip()


def test_skills_sh_catalog_matches_repository_skills() -> None:
    config = json.loads((REPOSITORY_ROOT / "skills.sh.json").read_text(encoding="utf-8"))
    skill_files = sorted(SKILLS_DIRECTORY.glob("*/SKILL.md"))
    repository_skills = {skill_file.parent.name for skill_file in skill_files}
    declared_skills = {
        skill
        for grouping in config["groupings"]
        for skill in grouping["skills"]
    }

    assert config["$schema"] == "https://skills.sh/schemas/skills.sh.schema.json"
    assert config["notGrouped"] == "bottom"
    assert repository_skills == EXPECTED_SKILLS
    assert declared_skills == EXPECTED_SKILLS
    assert {skill_name(skill_file) for skill_file in skill_files} == EXPECTED_SKILLS


def test_readme_has_skills_sh_badge_and_remote_install_command() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "[![skills.sh](https://skills.sh/b/ltppp/douyin-ingest)]" in readme
    assert "(https://skills.sh/ltppp/douyin-ingest)" in readme
    assert "npx skills add https://github.com/ltppp/douyin-ingest" in readme
    assert "npx skills add ltppp/douyin-ingest@douyin-content-ingest" in readme
    assert "npx skills add ltppp/douyin-ingest@douyin-script-rewriter" in readme


def test_skill_descriptions_cover_common_search_intents() -> None:
    expected_terms = {
        "douyin-content-ingest": {
            "douyin",
            "抖音",
            "chinese tiktok",
            "creator profile",
            "top n",
            "viral",
            "video metadata",
            "download",
            "speech-to-text",
            "transcript",
        },
        "douyin-script-rewriter": {
            "douyin",
            "抖音",
            "chinese tiktok",
            "short-video",
            "copywriting",
            "文案",
            "口播",
            "transcript",
            "viral",
            "rewrite",
            "docx",
            "word",
        },
    }

    for skill, terms in expected_terms.items():
        description = skill_description(SKILLS_DIRECTORY / skill / "SKILL.md")
        normalized = description.casefold()
        assert description.startswith("Use when")
        assert len(description) <= 500
        assert not {term for term in terms if term.casefold() not in normalized}
