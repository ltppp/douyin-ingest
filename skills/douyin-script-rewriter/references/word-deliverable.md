# Fixed Word Deliverable

## Authority

Use `scripts/build_word.py` as the only Word implementation. Template version `douyin-script-rewriter-word-v1` is the visually certified compact content-book layout. Do not reproduce the builder in a task-local script and do not restyle individual runs.

Resolve the script path from this skill directory. Do not assume the current working directory contains `scripts/`.

## Normal Run

After `result.json` and every per-video artifact are final:

```bash
python scripts/build_word.py --run <rewrite-run-directory>
```

The builder requires `python-docx`. Install the project Word extra in the same Python
environment before the first build:

```bash
python -m pip install 'douyin-ingest[word]'
```

For an editable source checkout, use `python -m pip install -e '.[word]'` from the
repository root. Do not search an agent application's private runtime or modify
`sys.path` to locate an undeclared dependency.

The script accepts a run directory, `result.json`, or `report.md`. It:

1. Validates `result.json`, video order, ranks, and required artifact paths.
2. Builds one consolidated `.docx` under `<run>/deliverables/`.
3. Verifies the OOXML package, template version, complete text, section counts, Top labels, and Douyin links.
4. Writes `word_file` and `word_template_version` to `result.json` only after verification passes.
5. Inserts or replaces the single Word link in `report.md` idempotently.

Treat nonzero exit or `"ok": false` as a failed deliverable. Do not link the DOCX in the user reply.

## Existing Completed Run

When the user provides an existing run path and requests Word only, run the same command against that run. Do not repeat crawling, transcription, correction, analysis, or rewriting.

## Verification and Template Certification

To verify an existing Word without rebuilding:

```bash
python scripts/build_word.py \
  --run <rewrite-run-directory> \
  --output <word-file> \
  --verify-only
```

The fixed template removes routine per-run visual review. Perform a full render-and-inspect certification only when any of these changes:

- `TEMPLATE_VERSION` or Word layout code;
- fonts or font configuration;
- LibreOffice/renderer environment;
- content roles or section order.

Also render when structural verification fails. After a layout change passes full-page visual inspection, increment `TEMPLATE_VERSION`; never silently alter a certified version.

Use `--no-record` only for regression tests so test runs do not mutate `result.json` or `report.md`.

## User Handoff

For successful rewrite runs, return only `已完成` and the clickable absolute path stored in `result.json.word_file`. Keep `report.md` as the internal traceability index.
