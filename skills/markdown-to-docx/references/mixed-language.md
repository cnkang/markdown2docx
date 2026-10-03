# Local language and direction

Use BCP 47 `lang` on Pandoc spans/divs when the glyph region matters:

```markdown
---
lang: en
---

[简体中文 骨]{lang=zh-Hans} [繁體中文 骨]{lang=zh-Hant}
[日本語の漢字 骨]{lang=ja} [한국어 骨]{lang=ko}
English, Français : café, Español: niño, Русский, العربية 123.

::: {lang=ar dir=rtl}
مَرْحَبًا بالعالم مع [English 中文 123 (https://example.com)]{dir=ltr}.
:::
```

Local tags override their scope. Without local tags, script detection chooses fonts; ambiguous shared Han uses paragraph context/main language and finally Simplified Chinese, with a warning. A language tag cannot translate or fix incorrectly entered text.

Explicit `dir` determines paragraph base direction on a div and run direction on a span. Otherwise the first strong prose character sets paragraph direction, excluding inline code. Numbers, URLs and code remain LTR where appropriate; never reverse strings to imitate RTL.

The converter covers headings, paragraphs, lists, table cells, notes, links, inline/block code and math. Use Markdown formatting normally. Color emoji and raw HTML are outside complete verification; inspect reported statuses. DOCX contents are fields and may need refreshing in the viewing application.

Font/cache exceptions remain visible in reports. A successful text/structure check alone is not evidence that Arabic joining or pagination was visually reviewed.
