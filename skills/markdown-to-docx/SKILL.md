---
name: markdown-to-docx
description: Convert Markdown to editable DOCX with automatic open fonts, CJK and UN-language mixing, Arabic RTL, and machine-readable validation. Use when an agent needs a Word deliverable from Markdown, with or without a user template.
---

# Markdown to DOCX

Use the bundled launcher rather than recreating conversion logic. It runs an immutable execution-package revision through `uv tool run` (the same runtime as `uvx`), independent of a repository checkout. Requires Python for this launcher, `uv`, and Pandoc. The runtime uses Python 3.14; uv can acquire it. First-time package/font acquisition requires network access.

Resolve `scripts/run.py` relative to this installed skill directory. Paths below are placeholders for absolute paths to the launcher and user files:

```bash
python /path/to/skill/scripts/run.py --doctor --json
python /path/to/skill/scripts/run.py /path/to/input.md -o /path/to/output.docx --json
```

No template is needed. Pass `--template` only when the user supplies one; missing/corrupt requested templates fail. Use `--toc` when a contents field is wanted; refresh that field in Word/LibreOffice to populate entries. Use `--lang` to set the main document language, and `--ui-lang zh` only for Chinese CLI messages.

For shared Han characters or RTL scopes, read [mixed-language.md](references/mixed-language.md). Ordinary unmarked script mixing needs no manual segmentation. Supported priority languages are Simplified/Traditional Chinese, Japanese, Korean, English, French, Spanish, Russian and Arabic. Do not translate content or infer the main language from the machine locale.

Read the JSON result before delivering:

- `checks` separates structure, text integrity, font coverage, language/direction and rendering. Required checks run before replacing the output. Errors are nonzero with stable JSON codes.
- `fonts` lists required family names, provenance and file paths. Verified fonts are selected from the system, cache or pinned official downloads; fonts are never embedded or automatically installed.
- Cached fonts are not available to Word/LibreOffice until installed. Explain the recipient's font dependencies. Do not claim consistent display on a machine missing them.
- Preserve and disclose warnings about ambiguous regional Han glyphs, emoji or explicit unverified-font exceptions. Use `--allow-unverified-fonts` only when the user authorizes that exception.

Use `--offline` when downloads must be disabled; the package/runtime must also have been acquired previously (uv's package offline mode is separate). Optional `--render --preview-dir /path/to/previews` uses LibreOffice and Poppler when the required fonts are installed. Inspect page images for shaping, order, punctuation and layout. Report rendering as unverified when unavailable; generated previews do not constitute manual Word approval.

Deliver the DOCX and a concise report of checks, warnings and recipient fonts. Include preview/report files when requested. Keep the user’s existing output if conversion fails.
