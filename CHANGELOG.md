# Changelog

## Unreleased

- Validate explicit configuration and resource budgets early; isolate converter configuration snapshots.
- Bound Pandoc parsing/reference/writing stages and reject compact reserved output/format arguments.
- Unify CLI report conversion and logging, quiet/JSON behavior and content-free template defaults.
- Add optional remote-image offline and restricted resource policies with private image staging.
- Stream DOCX entries, preserve user styles, independently verify serialized font/language/direction properties, and support refreshing font metadata/discovery.
- Publish isolated preview generations, preserve previous results on failure, and sort pages numerically.
- Version report schemas and record conversion IDs, actual tool versions and stage timings.
- Use locked Ruff/mypy/pytest/Bandit checks, checksum-pinned Pandoc installs, offline fixture preparation, installed-wheel smoke tests and manual OIDC publishing workflows.

Compatibility: missing/invalid explicit configurations now fail instead of silently falling back. Mutating the configuration passed to an existing converter no longer changes that converter. CLI templates omit sample content unless `--template-sample` is requested. Preview paths now point into generation directories. `create_backup=true` is rejected because it was not implemented. Each Pandoc stage has its own timeout rather than a shared task deadline.

## 0.2.0 — Unreleased

- Convert CJK and UN official languages within the same paragraphs, headings and table cells, including local language/direction scopes and Arabic RTL.
- Generate a content-free Pandoc reference automatically; default fonts are verified Noto builds rather than Calibri/Consolas.
- Resolve exact approved system fonts or download checksum-pinned fonts and licenses to a private cache. No automatic font installation or embedding.
- Add `convert_with_report()`, JSON CLI results, English/Chinese UI, offline mode, diagnostics, explicit font-license exceptions and optional previews.
- Preserve secure POSIX publication from main; add a Windows directory-handle implementation. Preserve caller-requested paths in validation errors.
- Add a distributable Agent skill with an immutable execution-package revision, a comprehensive Markdown fixture and three-platform CI artifacts.

- Apply template configuration in every CLI mode, show optional preview status/reasons, preserve hyperlink character styles, warn for emoji sequences across code/generated runs, and clear stale raster pages.

- Preserve scoped character styles and code-block link anchors; acquire localized TOC fonts only when a TOC is requested.

### Migration

`convert()` still returns `Path`. `--no-validate` and `validate_output=False` cannot disable mandatory structure/text/font/direction checks. A missing or corrupt requested template now fails. Custom template/config fonts without an approved record require the explicit `allow_unverified_fonts` exception and must be installed. Template layout/styles remain, but script-aware run fonts are managed by the converter. Reserved input/output/template Pandoc switches should use the corresponding converter arguments instead of `extra_args`.

Cached fonts must be installed separately on viewing machines. Rendering and manual visual review have separate statuses. Old Pandoc versions are not covered by the new CI suite (Pandoc 3.12).
