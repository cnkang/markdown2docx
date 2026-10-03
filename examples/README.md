# Examples and acceptance artifacts

[`multilingual.md`](multilingual.md) is the primary acceptance fixture. It combines Simplified/Traditional Chinese, Japanese, Korean, English, French, Spanish, Russian and Arabic within one document, paragraph and table cell. It exercises emphasis, links, regional glyphs, combining marks, nested/ordered/task lists, tables, quotations, RTL scopes, code, footnotes, a generated TOC, inline/display math and a local image.

```bash
uv run python scripts/validate_multilingual.py --output-dir artifacts/multilingual
```

Outputs:

- `multilingual.docx`: the editable Word artifact.
- `report.json`: language/font provenance and separate validation statuses.
- `preview/preview.pdf` and `preview/page-*.png`: produced with `--render` when required fonts are installed and LibreOffice/Poppler are available.

No template is needed. The first run downloads missing approved fonts to the application cache. Install reported fonts on machines used to view or render the DOCX. `--offline` reuses the verified cache.

```bash
uv run python scripts/validate_multilingual.py --offline --render --output-dir artifacts/multilingual
```

GitHub Actions retains per-platform `multilingual-<OS>` artifacts; Linux additionally renders pages and checks expected PDF fonts. Artifacts are available from the workflow run's summary. Rendering is evidence for inspection, not automatic approval of Arabic shaping or layout. Check the previews and open the DOCX in Word/LibreOffice before a release.

[`example.md`](example.md) remains a general Markdown example. Emoji in that legacy fixture are explicitly outside full font/display verification.

综合样例可用于检查所有首批语言在同一个文件、同段落和同表格单元格中的混排。CI 上传 DOCX、报告和 Linux 页面预览；字体仅在缓存时需要另行安装，人工展示验收与自动结构检查分别记录。

The TOC is a Word field: refresh it in Word/LibreOffice to populate entries. The headless PDF preview may show only the contents heading until fields are updated.

Committed Linux sample: [DOCX](output/multilingual.docx), [PDF](output/preview/preview.pdf), [report](output/report.json), [page 1](output/preview/page-1.png), [page 2](output/preview/page-2.png), [page 3](output/preview/page-3.png). The report records the generating commit/workflow, with machine-specific paths sanitized. Regenerate from the fixture after changing conversion behavior.
