# markdown2docx Remediation Design

Date: 2026-11-25

Source revision: `bac6731231a38f9873fd1dfeba02ce1c8a448a76`

## Goal

Fix the correctness, security, resource-boundary, release, packaging, testing, and maintainability findings from the full-project review. Preserve the existing public `convert()` contract while adding an explicit safe path for untrusted documents.

## Non-goals

- Do not change the canonical package name from `markdown2docx` to `markdown2pdf`.
- Do not embed fonts automatically; font installation remains an explicit viewing requirement.
- Do not replace Pandoc or LibreOffice.
- Do not claim an OS sandbox is implemented by the Python resource policy alone.

## Design

### 1. Conversion identity and immutable context

At the start of each conversion:

- Resolve input, output, template, cache, preview, and log paths to absolute paths.
- Reject input/output and template/output identity collisions using normalized paths plus `samefile()` for existing files.
- Deep-copy configuration into a per-conversion context and never read mutable converter configuration after the context is created.
- Open and validate input/template snapshots before passing them to Pandoc.

### 2. Core document integrity

- Split mixed-script text runs without dropping non-text children; fail closed when a run cannot be safely split.
- Set `xml:space="preserve"` on split text nodes with edge whitespace.
- Separate explicit direction from script-inferred direction so local `dir=rtl` applies to Latin/Common runs.
- Verify ordered text, whitespace, block boundaries, and final serialized run font coverage instead of relying only on marker aggregation.
- Normalize generated OOXML property order.

### 3. Scalable annotation

- Replace one unique character style per fragment with a bounded set of context styles plus an ordered run ledger.
- Add fragment/run/node budgets before Pandoc writes the intermediate DOCX.
- Avoid unnecessary AST copies and repeated whole-document parsing.

### 4. Untrusted-document boundary

- Add `convert_untrusted()` and `--untrusted`, defaulting to remote-resource rejection, restricted local resources, and raw/filter rejection.
- Keep ordinary `convert()` behavior for explicitly trusted callers.
- Use verified temporary roots and descriptor-relative operations for conversion and preview workspaces.
- Add aggregate image, Pandoc stdout, AST, archive, and preview budgets.
- Harden font cache opens and renderer process-tree cleanup.

### 5. Release and packaging

- Update the Agent skill execution pin to a reviewed immutable revision and add a real launcher smoke test.
- Scope Windows skips to POSIX-only tests and add Windows-specific output tests.
- Make release depend on the same-SHA three-platform test workflow and pin Python 3.14.
- Validate wheel console entry points, metadata, licenses, assets, and sdist rebuild/install.
- Pin build backend requirements and retain release evidence.

### 6. Quality and maintainability

- Split multilingual annotation, rewriting, and verification into focused modules.
- Audit all visible font sources, including numbering, docDefaults, themes, and linked styles.
- Add current coverage thresholds, meaningful pytest markers, self-contained offline fixtures, and stronger TOC/PDF assertions.
- Regenerate schema-valid example artifacts, implement docs build, and clean development targets.

## PR sequence

1. **Core correctness and release blockers** — conversion identity, run/text/direction integrity, skill pin, Windows tests, release gating.
2. **Untrusted input and resource boundaries** — safe entry point, secure workspaces, aggregate budgets, cache and renderer hardening.
3. **Quality, maintainability, and packaging** — module split, OOXML/font audit, configuration/logging, tests, docs, artifacts, dependency governance.

Each PR must pass Ruff, formatting, mypy, Bandit, pytest, installed-wheel smoke, and the relevant regression tests before review.

## Acceptance criteria

- No conversion can overwrite its input or template.
- Mixed-script and whitespace corruption cannot report `text_integrity=passed`.
- Explicit local RTL/LTR direction survives serialization.
- Untrusted conversion rejects remote and out-of-root images before Pandoc resource loading.
- Resource budgets fail before unbounded allocation or staging.
- Windows output tests execute on Windows.
- Release publication requires the same commit to pass all three platforms.
- All new behavior has regression tests observed failing before implementation.
