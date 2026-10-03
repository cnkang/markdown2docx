# Changelog

## 0.2.0 — Unreleased

- Convert CJK and UN official languages within the same paragraphs, headings and table cells, including local language/direction scopes and Arabic RTL.
- Generate a content-free Pandoc reference automatically; default fonts are verified Noto builds rather than Calibri/Consolas.
- Resolve exact approved system fonts or download checksum-pinned fonts and licenses to a private cache. No automatic font installation or embedding.
- Add `convert_with_report()`, JSON CLI results, English/Chinese UI, offline mode, diagnostics, explicit font-license exceptions and optional previews.
- Preserve secure POSIX publication from main; add a Windows directory-handle implementation. Preserve caller-requested paths in validation errors.
- Add a distributable Agent skill with an immutable execution-package revision, a comprehensive Markdown fixture and three-platform CI artifacts.

### Migration

`convert()` still returns `Path`. `--no-validate` and `validate_output=False` cannot disable mandatory structure/text/font/direction checks. A missing or corrupt requested template now fails. Custom template/config fonts without an approved record require the explicit `allow_unverified_fonts` exception and must be installed. Template layout/styles remain, but script-aware run fonts are managed by the converter. Reserved input/output/template Pandoc switches should use the corresponding converter arguments instead of `extra_args`.

Cached fonts must be installed separately on viewing machines. Rendering and manual visual review have separate statuses. Old Pandoc versions are not covered by the new CI suite (Pandoc 3.12).
