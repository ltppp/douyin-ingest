# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `project/`. `main.py` and `cli.py` expose the command-line entry points; `service.py` coordinates crawling; `capture.py` and `login.py` manage Playwright browser work; `api.py`, `parser.py`, and `models.py` handle API data; and `media.py` prepares speech audio. Tests mirror these modules under `tests/` as `test_<module>.py`.

Runtime artifacts belong in `storage/`, `output/`, and `logs/`. Their generated contents are ignored by Git. Keep design notes, such as `douyin-audio-workflow-plan.md`, at the repository root.

## Build, Test, and Development Commands

Use Python 3.12 and the project virtual environment:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/playwright install chromium
```

Run the CLI with `.venv/bin/python -m project.main '<Douyin URL>'`, or use the installed `douyin-ingest` command. Before submitting changes, run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check project tests
.venv/bin/mypy project
```

## Coding Style & Naming Conventions

Follow Python 3.12 conventions with four-space indentation and a 100-character line limit. Ruff enforces `E`, `F`, import sorting, Python upgrades, bugbear, and async rules. Mypy runs in strict mode, so add complete type annotations and avoid untyped escape hatches. Use `snake_case` for functions and modules, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Prefer async APIs for network and browser operations.

## Testing Guidelines

Tests use pytest and `pytest-asyncio` with automatic async mode. Name files `test_<module>.py` and functions `test_<behavior>`. Isolate filesystem work with `tmp_path`, replace external calls with `monkeypatch`, and assert both return values and stable JSON/error contracts. No coverage threshold is configured; add focused regression tests for every behavioral change.

## Commit & Pull Request Guidelines

Use short Conventional Commit subjects such as `feat: add cache expiry validation`, and keep each commit focused. Pull requests should explain the user-visible behavior, list verification commands, link related issues, and call out changes to CLI output or stored JSON schemas.

## Security & Configuration

Never commit `storage_state.json`, debug request headers/cookies, logs, or generated output. Debug captures may contain active Douyin credentials. Preserve restrictive permissions and use synthetic fixtures in tests and reviews.
