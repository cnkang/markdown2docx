# Remediation Implementation Plan

> **For agentic workers:** Use `test-driven-development` for every behavior change. Run the named failing test before production changes, then run the focused and full suites after each task.

**Goal:** Fix all reviewed findings and land CI-green PRs.

**Architecture:** Preserve the Pandoc-based pipeline; harden conversion identity, integrity verification, resource boundaries, and release evidence around it.

**Tech Stack:** Python 3.14, pytest/Hypothesis, lxml, python-docx, Pandoc, LibreOffice/Poppler, GitHub Actions, uv.

---

## PR1 — Core correctness and release blockers

### Task 1: Reject input/template/output identity collisions

**Files:** `src/markdown2docx/converter.py`, `tests/test_converter.py`, `tests/test_output.py`

- [x] Add failing tests for default output equal to a `.docx`-named Markdown input, explicit output equal to input, output equal to template, and relative path aliases.
- [x] Run `uv run --locked pytest tests/test_output.py -q` and confirm the new tests fail (`9 failed, 28 passed`).
- [x] Add normalized path and `samefile()` checks before Pandoc/font work.
- [x] Re-run focused tests, then `uv run --locked pytest -q` (`275 passed, 1 skipped`).
- [x] Commit `fix: harden path identity checks` (`480912e`).

### Task 2: Split mixed runs safely and preserve whitespace

**Files:** `src/markdown2docx/multilingual.py`, `tests/test_multilingual.py`

- [x] Add failing tests for mixed-script runs containing `<w:br/>`, multiple `<w:t>`, split fragments with edge spaces, nested shapes, neutral text, heading roles, and empty text nodes.
- [x] Implement text-node-aware splitting that preserves non-text children and order; fail closed when unsafe.
- [x] Set and verify `xml:space="preserve"` where split text begins/ends with whitespace.
- [x] Verify every serialized text run's order, text, shape, and independently derived font coverage.
- [x] Run focused and full tests (`308 passed, 1 skipped`); final fix `a707604`.

### Task 3: Make text integrity ordered and structural

**Files:** `src/markdown2docx/multilingual.py`, `tests/test_multilingual.py`

- [x] Add fault-injection tests for reordered runs, deleted spaces, lost hard breaks, merged/split paragraphs, moved parts, code anchors, TOC, raw isolation, LineBlock, and DefinitionList.
- [x] Replace marker-only aggregation with ordered marker/text/block verification and linear event assembly.
- [x] Keep raw-content and emoji status semantics explicit and scoped.
- [x] Run focused/full tests (`350 passed, 1 skipped`); final fix `107e65d`.

### Task 4: Honor explicit local direction

**Files:** `src/markdown2docx/multilingual.py`, `tests/test_multilingual.py`

- [x] Add failing tests for Latin/Common `dir=rtl`, numeric/punctuation spans, nested direction, `dir=ltr` inside Arabic, code, tables, footnotes, and conflicting controls.
- [x] Separate explicit direction from script inference using LRI/RLI/PDI isolates; keep `w:rtl` script-accurate and verify serialized direction.
- [x] Run focused/full tests (`396 passed, 1 skipped`); final fix `02d3234`.

### Task 5: Repair Agent skill execution pin

**Files:** `skills/markdown-to-docx/scripts/run.py`, `skills/markdown-to-docx/SKILL.md`, `tests/test_skill.py`, `.github/workflows/test.yml`

- [ ] Add failing launcher tests for immutable revision, offline flag forwarding, and argument preservation.
- [ ] Update pin to reviewed `bac6731231a38f9873fd1dfeba02ce1c8a448a76` or the final reviewed remediation commit.
- [ ] Add CI smoke for revision resolution/version/doctor/minimal conversion.
- [ ] Run focused/full tests; commit `fix: verify immutable agent skill runtime`.

### Task 6: Scope Windows skips and add Windows output coverage

**Files:** `tests/test_output.py`, `tests/test_multilingual.py`, `.github/workflows/test.yml`

- [ ] Replace module-level Windows skip with per-test POSIX markers.
- [ ] Add Windows reparse-point, pinned-handle, no-overwrite, and failure-preservation tests.
- [ ] Make CI report collected/skipped counts and fail on unexpected skips in `test_output.py`.
- [ ] Run focused/full tests; commit `test: restore Windows output coverage`.

### Task 7: Bind release to same-SHA three-platform quality gates

**Files:** `.github/workflows/test.yml`, `.github/workflows/release.yml`, `.python-version`

- [ ] Add `.python-version` with `3.14`.
- [ ] Convert Test jobs to a reusable workflow callable by release.
- [ ] Make release wait for quality and all three OS jobs for `github.sha`.
- [ ] Run pre-commit and the same quality command in release.
- [ ] Validate workflows with actionlint or equivalent and commit `ci: require three-platform release gates`.

### Task 8: Validate distribution entry points and metadata

**Files:** `scripts/validate_wheel.py`, `pyproject.toml`, `.github/workflows/test.yml`, `.github/workflows/release.yml`

- [ ] Add failing script tests for console entry point, version assertion, package location, LICENSE, METADATA, JSON assets, and sdist rebuild.
- [ ] Implement artifact inventory and sdist install/rebuild smoke.
- [ ] Pin Hatchling build requirement and record tool versions/hashes.
- [ ] Run script tests and build/install smoke; commit `build: verify complete distribution artifacts`.

## PR2 — Untrusted input and resource boundaries

### Task 9: Add a default-safe untrusted conversion entry point

**Files:** `src/markdown2docx/converter.py`, `src/markdown2docx/cli.py`, `src/markdown2docx/__init__.py`, `tests/test_optimization.py`, `tests/test_cli.py`

- [ ] Add failing API/CLI tests proving `convert_untrusted()` and `--untrusted` reject remote/out-of-root images, raw nodes, filters, and defaults before writer execution.
- [ ] Implement safe defaults while preserving trusted `convert()` behavior.
- [ ] Run focused/full tests; commit `feat: add safe untrusted conversion entry point`.

### Task 10: Secure conversion and preview workspaces

**Files:** `src/markdown2docx/output.py`, `src/markdown2docx/converter.py`, `src/markdown2docx/report.py`, `tests/test_output.py`, `tests/test_report.py`

- [ ] Add failing race tests for hostile `TMPDIR`, renamed conversion root, symlinked preview ancestors, replaced render root, and pre-planted PDF symlink.
- [ ] Reuse verified temporary roots and descriptor-relative file operations; open PDFs with `O_NOFOLLOW` and `fstat`.
- [ ] Run focused/full tests; commit `fix: pin conversion and preview workspaces`.

### Task 11: Add aggregate resource budgets

**Files:** `src/markdown2docx/config.py`, `src/markdown2docx/resources.py`, `src/markdown2docx/runner.py`, `src/markdown2docx/converter.py`, `tests/test_optimization.py`

- [ ] Add failing tests for cumulative image overflow, duplicate references, Pandoc stdout overflow, AST node/fragment/run overflow, and shared deadline expiry.
- [ ] Add configurable `resource_bytes`, `pandoc_stdout_bytes`, `ast_nodes`, `fragments`, `runs`, and `total_timeout_seconds`.
- [ ] Enforce budgets before allocation/staging and stream bounded output.
- [ ] Run focused/full tests; commit `fix: enforce aggregate conversion budgets`.

### Task 12: Harden archive and font cache handling

**Files:** `src/markdown2docx/archive.py`, `src/markdown2docx/fonts.py`, `tests/test_optimization.py`, `tests/test_fonts.py`

- [ ] Add failing tests for oversized ZIP files/central directories, encrypted/unsupported/corrupt entries, `.rels` limits, cache symlinks/FIFOs, and checksum-to-use replacement.
- [ ] Add physical/central-directory budgets and normalize archive failures to `ValidationError`.
- [ ] Open cache files with `O_NOFOLLOW`, verify regular files/ownership, and use verified snapshots.
- [ ] Run focused/full tests; commit `fix: harden archive and font cache boundaries`.

### Task 13: Clean up renderer process trees and preview limits

**Files:** `src/markdown2docx/report.py`, `tests/test_report.py`

- [ ] Add failing tests for orphaned renderer children, missing `pdftoppm` with over-limit PDF, oversized output, and pixel-dimension bombs.
- [ ] Use process-group cleanup and independent page/output/pixel budgets.
- [ ] Run focused/full tests; commit `fix: bound and reap preview renderers`.

## PR3 — Quality, maintainability, and packaging

### Task 14: Split multilingual responsibilities and bound styles

**Files:** `src/markdown2docx/multilingual.py`, new `annotator.py`/`rewriter.py`/`verifier.py`, `tests/test_multilingual.py`

- [ ] Add failing scale tests proving alternating scripts use bounded styles/runs and fail before intermediate explosion.
- [ ] Extract AST annotation, DOCX rewriting, and verification with table-driven properties.
- [ ] Remove duplicate whole-document parsing and unnecessary AST copies.
- [ ] Run focused/full tests and benchmark; commit `refactor: split multilingual pipeline and bound styles`.

### Task 15: Normalize OOXML and audit all visible fonts

**Files:** `src/markdown2docx/multilingual.py`, `src/markdown2docx/converter.py`, `src/markdown2docx/templates.py`, `tests/test_styles.py`, `tests/test_templates.py`

- [ ] Add failing schema-order tests and numbering/docDefaults/theme/linked-style font tests.
- [ ] Normalize `rPr`/`pPr` child order and audit all visible font sources.
- [ ] Align template creation and conversion font policy.
- [ ] Run focused/full tests; commit `fix: normalize OOXML and audit visible fonts`.

### Task 16: Immutable conversion context and safe logging

**Files:** `src/markdown2docx/converter.py`, `src/markdown2docx/cli.py`, `src/markdown2docx/config.py`, `tests/test_config.py`, `tests/test_cli.py`

- [ ] Add failing tests for config mutation during conversion, cwd changes, log/input/output collisions, invalid UTF-8 config, invalid log format, and cache lock/I/O errors.
- [ ] Snapshot config and paths per conversion; validate log paths before opening; normalize errors.
- [ ] Run focused/full tests; commit `fix: isolate conversion context and logging`.

### Task 17: Repair test governance and offline fixtures

**Files:** `tests/conftest.py`, `tests/*.py`, `pyproject.toml`, `Makefile`, `.github/workflows/test.yml`

- [ ] Add failing tests for clean-home/empty-cache offline operation and subprocess network prohibition.
- [ ] Mark real integration/CLI/template/slow tests or remove empty markers/targets.
- [ ] Add branch coverage thresholds and skip reporting.
- [ ] Remove required-dependency skips and strengthen TOC/large-document assertions.
- [ ] Run focused/full tests; commit `test: make suite self-contained and enforceable`.

### Task 18: Regenerate examples, complete docs, and dependency governance

**Files:** `examples/output/*`, `README.md`, `README_zh.md`, `CHANGELOG.md`, `Makefile`, `docs/`, `.github/dependabot.yml`, `scripts/setup-env.sh`, `.gitignore`

- [ ] Regenerate and schema-validate example DOCX/PDF/report; include code/math/symbol PDF font checks.
- [ ] Implement Sphinx docs and API/architecture pages; fix README links and canonical naming note.
- [ ] Add dependency/workflow auditing, locked setup defaults, ignore rules, and PHONY targets.
- [ ] Run docs build, quality, full tests, wheel/sdist smoke; commit `docs: complete release and development governance`.

## Final verification

- [ ] `make quality`
- [ ] `uv run --locked pre-commit run --all-files`
- [ ] `uv run --locked pytest --cov=src --cov-branch --cov-report=term-missing`
- [ ] `uv run --locked python scripts/validate_multilingual.py --offline --output-dir artifacts/multilingual`
- [ ] `uv build` and installed wheel/sdist smoke
- [ ] Push branches, open PRs, inspect GitHub Actions until green (Snyk quota-only failures documented).
