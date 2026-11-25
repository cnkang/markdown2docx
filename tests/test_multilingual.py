"""Round-trip acceptance for CJK + UN languages in the same document."""

import copy
import json
import os
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from markdown2docx import MarkdownToDocxConfig, MarkdownToDocxConverter
from markdown2docx.exceptions import ConfigurationError, ValidationError
from markdown2docx.fonts import FontResolver
from markdown2docx.multilingual import NS, W, fragments

ROOT = Path(__file__).resolve().parents[1]


def parts(path):
    with zipfile.ZipFile(path) as archive:
        return {
            name: etree.fromstring(archive.read(name))
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        }


BIDI_CONTROLS = "\u2066\u2067\u2068\u2069"
ISOLATE_STARTS = {"\u2066": "ltr", "\u2067": "rtl", "\u2068": "auto"}


def paragraph_text(paragraph):
    return "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))


def bidi_scopes(paragraph):
    """Group exact text by a nested Unicode isolate stack and run direction."""
    scopes = [[]]
    stack = [0]
    for run in paragraph.iter(W + "r"):
        text = "".join(run.xpath("./w:t/text()", namespaces=NS))
        if not text:
            continue
        rtl = run.find(W + "rPr/" + W + "rtl")
        cs = run.find(W + "rPr/" + W + "cs")
        direction = (
            rtl.get(W + "val") if rtl is not None else None,
            cs.get(W + "val") if cs is not None else None,
        )
        for char in text:
            if char in ISOLATE_STARTS:
                scopes.append([])
                stack.append(len(scopes) - 1)
            elif char == "\u2069":
                assert len(stack) > 1
                stack.pop()
            else:
                scopes[stack[-1]].append((char, *direction))

    assert len(stack) == 1
    result = []
    for scope in scopes:
        merged = []
        for text, rtl, cs in scope:
            if merged and merged[-1][1:] == (rtl, cs):
                merged[-1] = (merged[-1][0] + text, rtl, cs)
            else:
                merged.append((text, rtl, cs))
        if merged:
            result.append(merged)
    return result


def test_bidi_scope_helper_tracks_nested_isolates_and_whitespace():
    paragraph = etree.fromstring(
        f'<w:p xmlns:w="{NS["w"]}"><w:r><w:rPr>'
        '<w:rtl w:val="0"/><w:cs w:val="0"/></w:rPr>'
        "<w:t>pre \u2067outer \u2066inner\u2069 tail\u2069 post</w:t>"
        "</w:r></w:p>"
    )

    assert paragraph_text(paragraph) == (
        "pre \u2067outer \u2066inner\u2069 tail\u2069 post"
    )
    assert bidi_scopes(paragraph) == [
        [("pre  post", "0", "0")],
        [("outer  tail", "0", "0")],
        [("inner", "0", "0")],
    ]


@pytest.mark.parametrize("text", ["\u2067ABC", "\u2069ABC"])
def test_bidi_scope_helper_rejects_unbalanced_isolates(text):
    paragraph = etree.fromstring(
        f'<w:p xmlns:w="{NS["w"]}"><w:r><w:t>{text}</w:t></w:r></w:p>'
    )

    with pytest.raises(AssertionError):
        bidi_scopes(paragraph)


def generated_docx(tmp_path, paragraph, name="generated.docx"):
    path = tmp_path / name
    xml = (
        f'<w:document xmlns:w="{NS["w"]}"><w:body><w:p>'
        f"{paragraph}</w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


def generated_body_docx(tmp_path, body, name="generated.docx"):
    path = tmp_path / name
    xml = f'<w:document xmlns:w="{NS["w"]}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


def rewrite_docx(path, mutations):
    with zipfile.ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    updated = []
    for info, data in entries:
        if info.filename in mutations:
            root = etree.fromstring(data)
            mutations[info.filename](root)
            data = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
        updated.append((info, data))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for info, data in updated:
            archive.writestr(info, data)


def test_comprehensive_single_file(tmp_path):
    output = tmp_path / "mixed.docx"
    report = MarkdownToDocxConverter().convert_with_report(
        ROOT / "examples/multilingual.md", output, toc=True
    )
    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    assert report.checks["rendering"] == "unverified"
    assert set(report.languages) >= {
        "zh-Hans",
        "zh-Hant",
        "ja",
        "ko",
        "en",
        "fr",
        "es",
        "ru",
        "ar",
    }
    roots = parts(output)
    document = roots["word/document.xml"]
    text = "".join(document.xpath("//w:t/text()", namespaces=NS))
    for value in [
        "简体中文",
        "繁體中文",
        "日本語",
        "한국어",
        "Français",
        "Español",
        "Русский",
        "العربية",
        "café",
        "مَرْحَبًا",
    ]:
        assert unicodedata.normalize("NFD", value) in unicodedata.normalize("NFD", text)
    # All regional CJK fonts appear in the same paragraph and the same cell.
    expected_fonts = {
        "Noto Sans CJK SC",
        "Noto Sans CJK TC",
        "Noto Sans CJK JP",
        "Noto Sans CJK KR",
        "Noto Sans",
        "Noto Sans Arabic",
    }
    assert any(
        set(p.xpath(".//w:rFonts/@w:ascii", namespaces=NS)) >= expected_fonts
        for p in document.iter(W + "p")
    )
    assert any(
        set(cell.xpath(".//w:rFonts/@w:ascii", namespaces=NS)) >= expected_fonts
        for cell in document.iter(W + "tc")
    )
    assert document.xpath("//w:pPr/w:bidi[@w:val='1']", namespaces=NS)
    assert document.xpath("//w:rPr[w:b and w:bCs and w:rtl[@w:val='1']]", namespaces=NS)
    assert document.xpath("//w:hyperlink", namespaces=NS)
    assert "word/footnotes.xml" in roots
    assert roots["word/footnotes.xml"].xpath("//w:lang[@w:val='ar']", namespaces=NS)
    assert not roots["word/styles.xml"].xpath(
        "//w:style[starts-with(@w:styleId,'MD2D')]", namespaces=NS
    )
    assert not document.xpath("//w:rStyle[starts-with(@w:val,'MD2D')]", namespaces=NS)
    assert document.xpath("//w:instrText[contains(., 'TOC')]", namespaces=NS)
    assert document.xpath("//m:oMath", namespaces=NS)
    assert document.xpath("//w:drawing", namespaces=NS)
    numbering = roots["word/numbering.xml"]
    assert all(
        font.startswith("Noto ")
        for font in numbering.xpath("//w:rFonts/@w:ascii", namespaces=NS)
    )
    assert not any(
        "\uf0b7" in value or "\uf0a7" in value
        for value in numbering.xpath("//w:lvlText/@w:val", namespaces=NS)
    )


def test_local_language_and_code_region(tmp_path):
    source = tmp_path / "local.md"
    source.write_text(
        "[骨]{lang=zh-Hans} [骨]{lang=zh-Hant} [骨]{lang=ja} [骨]{lang=ko}\n\n::: {lang=ja}\n\n```text\n漢字 骨\n```\n\n:::\n"
    )
    result = MarkdownToDocxConverter().convert(source)
    root = parts(result)["word/document.xml"]
    families = [
        run.find(W + "rPr/" + W + "rFonts").get(W + "eastAsia")
        for run in root.iter(W + "r")
        if "骨" in "".join(run.xpath("./w:t/text()", namespaces=NS))
    ]
    assert families[:4] == [
        "Noto Sans CJK SC",
        "Noto Sans CJK TC",
        "Noto Sans CJK JP",
        "Noto Sans CJK KR",
    ]
    code = root.xpath("//w:p[w:pPr/w:pStyle[@w:val='SourceCode']]", namespaces=NS)[0]
    assert set(
        code.xpath(
            ".//w:r[w:t[contains(.,'漢字') or contains(.,'骨')]]/w:rPr/w:rFonts/@w:eastAsia",
            namespaces=NS,
        )
    ) == {"Noto Sans CJK JP"}


def test_graphemes_and_arabic_numbers():
    text = "cafe\u0301 مَرْحَبًا 123"
    pieces = fragments(text, "ar", text)
    assert "".join(part for _, part, _, _ in pieces) == text
    assert any("e\u0301" in part for _, part, _, _ in pieces)
    assert any("مَ" in part for _, part, _, _ in pieces)
    assert all(
        not rtl for _, part, rtl, _ in pieces if any(char.isdecimal() for char in part)
    )


@pytest.mark.parametrize(("code", "key"), [(False, "sans"), (True, "mono")])
def test_bidi_controls_are_separate_font_neutral_fragments(code, key):
    controls = "\u2066\u2067\u2069"
    assert fragments(controls, "ar", "ABC", code=code) == [
        (key, "\u2066", False, "Common"),
        (key, "\u2067", False, "Common"),
        (key, "\u2069", False, "Common"),
    ]
    assert fragments("\u2066ABC\u2069", "ar", "ABC", code=code) == [
        (key, "\u2066", False, "Common"),
        (key, "ABC", False, "Latin"),
        (key, "\u2069", False, "Common"),
    ]


def test_heading_bidi_controls_use_sans_instead_of_heading_font():
    from markdown2docx.multilingual import MultilingualDocument

    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="ar"
    )
    document._role = "heading"
    document._mark("\u2066ABC\u2069", "ar", "ABC", "ltr")

    assert [(spec.font, spec.script, spec.rtl) for spec in document.runs.values()] == [
        ("sans", "Common", False),
        ("heading", "Latin", False),
        ("sans", "Common", False),
    ]
    assert document.scripts == {"Common", "Latin"}


def test_heading_control_runs_serialize_with_neutral_fonts(tmp_path, monkeypatch):
    resolver = FontResolver()
    resolver.aliases["heading"] = "mono"
    body_font = resolver.resolve("sans").family
    heading_font = resolver.resolve("heading").family
    code_font = resolver.resolve("mono").family
    assert heading_font != body_font
    monkeypatch.setattr(
        "markdown2docx.converter.FontResolver", lambda **kwargs: resolver
    )
    source = tmp_path / "heading.md"
    source.write_text("# [ABC]{dir=rtl} `DEF`\n", encoding="utf-8")

    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="en", offline=True
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    paragraph = parts(report.output_path)["word/document.xml"].find(
        W + "body/" + W + "p"
    )
    runs = [
        (
            "".join(run.xpath("./w:t/text()", namespaces=NS)),
            run.find(W + "rPr/" + W + "rFonts").get(W + "ascii"),
        )
        for run in paragraph.iter(W + "r")
        if paragraph_text(run)
    ]
    assert [(text, font) for text, font in runs if set(text) <= set(BIDI_CONTROLS)] == [
        ("\u2067", body_font),
        ("\u2069", body_font),
        ("\u2066", code_font),
        ("\u2069", code_font),
    ]
    assert next(font for text, font in runs if text == "ABC") == heading_font
    assert next(font for text, font in runs if text == "DEF") == code_font


def test_text_structure_defers_text_coalescing():
    from markdown2docx.multilingual import TextStructure

    structure = TextStructure("document")
    for _ in range(100):
        structure.add_text("x")
    assert len(structure.events) == 100


def test_direction_auto_ignores_inline_code(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text("`ABC` العربية 123\n\n中文 العربية\n")
    root = parts(MarkdownToDocxConverter().convert(source))["word/document.xml"]
    paragraphs = root.findall(".//" + W + "p")
    assert [p.find(W + "pPr/" + W + "bidi").get(W + "val") for p in paragraphs] == [
        "1",
        "0",
    ]
    for run in paragraphs[0].iter(W + "r"):
        if "123" in "".join(run.xpath("./w:t/text()", namespaces=NS)):
            assert run.find(W + "rPr/" + W + "rtl").get(W + "val") == "0"


def test_explicit_local_rtl_isolates_latin_without_forcing_run_rtl(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text("[ABC]{dir=rtl}\n", encoding="utf-8")
    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="en", offline=True
    )
    paragraph = parts(report.output_path)["word/document.xml"].find(
        W + "body/" + W + "p"
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    assert paragraph.find(W + "pPr/" + W + "bidi").get(W + "val") == "0"
    assert paragraph_text(paragraph) == "\u2067ABC\u2069"
    assert bidi_scopes(paragraph) == [[("ABC", "0", "0")]]


def test_arabic_language_latin_isolate_needs_no_arabic_font(tmp_path, monkeypatch):
    import shutil

    cache = tmp_path / "fonts"
    cache.mkdir()
    prepared = FontResolver(directories=[])
    font = prepared.resolve("sans")
    entry = prepared.manifest["fonts"]["sans"]
    shutil.copyfile(font.path, cache / entry["filename"])
    shutil.copyfile(
        prepared.cache / entry["license_filename"], cache / entry["license_filename"]
    )
    resolver = FontResolver(cache=cache, offline=True, directories=[])
    monkeypatch.setattr(
        "markdown2docx.converter.FontResolver", lambda **kwargs: resolver
    )
    source = tmp_path / "direction.md"
    source.write_text("[ABC]{dir=rtl}\n", encoding="utf-8")

    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="ar", offline=True
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    assert {item["key"] for item in report.fonts} == {"sans"}
    paragraph = parts(report.output_path)["word/document.xml"].find(
        W + "body/" + W + "p"
    )
    assert paragraph_text(paragraph) == "\u2067ABC\u2069"
    assert {
        run.find(W + "rPr/" + W + "rFonts").get(W + "ascii")
        for run in paragraph.iter(W + "r")
        if paragraph_text(run)
    } == {resolver.resolve("sans").family}
    assert not paragraph.xpath(".//w:r[w:t]/w:rPr/w:cs[@w:val='1']", namespaces=NS)


def test_explicit_local_ltr_isolates_latin_in_arabic_paragraph(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text("العربية [ABC 123.]{dir=ltr} العربية\n", encoding="utf-8")
    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="ar", offline=True
    )
    paragraph = parts(report.output_path)["word/document.xml"].find(
        W + "body/" + W + "p"
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    assert paragraph.find(W + "pPr/" + W + "bidi").get(W + "val") == "1"
    assert paragraph_text(paragraph) == "العربية \u2066ABC 123.\u2069 العربية"
    assert bidi_scopes(paragraph) == [
        [
            ("العربية", "1", "1"),
            ("  ", "0", "1"),
            ("العربية", "1", "1"),
        ],
        [("ABC", "0", "0"), (" 123.", "0", "1")],
    ]


def test_explicit_local_rtl_isolates_digits_without_forcing_run_rtl(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text("العربية [123.,!]{dir=rtl} العربية\n", encoding="utf-8")
    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="ar", offline=True
    )
    paragraph = parts(report.output_path)["word/document.xml"].find(
        W + "body/" + W + "p"
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    assert paragraph.find(W + "pPr/" + W + "bidi").get(W + "val") == "1"
    assert paragraph_text(paragraph) == "العربية \u2067123.,!\u2069 العربية"
    assert bidi_scopes(paragraph) == [
        [
            ("العربية", "1", "1"),
            ("  ", "0", "1"),
            ("العربية", "1", "1"),
        ],
        [("123.,!", "0", "1")],
    ]


def test_image_alt_bidi_control_is_outside_body_direction_validation(tmp_path):
    import base64

    (tmp_path / "image.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    source = tmp_path / "direction.md"
    source.write_text("[![alt\u2069](image.png)]{dir=rtl}\n", encoding="utf-8")

    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="en", offline=True, restricted=True
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    paragraph = parts(report.output_path)["word/document.xml"].find(
        W + "body/" + W + "p"
    )
    assert paragraph_text(paragraph) == "\u2067\u2069"
    assert "alt" not in paragraph_text(paragraph)


@pytest.mark.parametrize(
    "control",
    [chr(codepoint) for codepoint in range(0x202A, 0x202F)]
    + [chr(codepoint) for codepoint in range(0x2066, 0x206A)],
)
@pytest.mark.parametrize("inline", ["text", "code"])
def test_explicit_span_rejects_conflicting_direction_controls(control, inline):
    from markdown2docx.multilingual import MultilingualDocument

    text = "ABC" + control
    child = (
        {"t": "Code", "c": [["", [], []], text]}
        if inline == "code"
        else {"t": "Str", "c": text}
    )
    document = MultilingualDocument(
        {
            "meta": {},
            "blocks": [
                {
                    "t": "Para",
                    "c": [
                        {
                            "t": "Span",
                            "c": [["", [], [["dir", "rtl"]]], [child]],
                        }
                    ],
                }
            ],
        },
        FontResolver(),
        lang="en",
    )

    with pytest.raises(ConfigurationError, match="bidi control"):
        document.annotate()


@pytest.mark.parametrize(
    "source_text",
    [
        pytest.param("`ABC\u2069`\n", id="standalone"),
        pytest.param("::: {dir=rtl}\n\n`ABC\u2069`\n\n:::\n", id="directional-div"),
        pytest.param("| `ABC\u2069` |\n|---|\n", id="table-cell"),
        pytest.param("text[^n]\n\n[^n]: `ABC\u2069`\n", id="footnote"),
    ],
)
def test_code_branch_rejects_directional_controls_in_every_scope(tmp_path, source_text):
    source = tmp_path / "direction.md"
    source.write_text(source_text, encoding="utf-8")

    with pytest.raises(ConfigurationError, match="bidi control"):
        MarkdownToDocxConverter().convert(source, lang="en", offline=True)


def test_directional_span_and_div_allow_nested_inline_code(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text(
        "::: {dir=rtl}\n\n[outer `ABC العربية 123` tail]{dir=ltr}\n\n:::\n",
        encoding="utf-8",
    )

    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="en", offline=True
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    paragraph = parts(report.output_path)["word/document.xml"].find(
        W + "body/" + W + "p"
    )
    assert paragraph.find(W + "pPr/" + W + "bidi").get(W + "val") == "1"
    assert paragraph_text(paragraph) == (
        "\u2066outer \u2066ABC العربية 123\u2069 tail\u2069"
    )
    assert bidi_scopes(paragraph) == [
        [("outer  tail", "0", "0")],
        [("ABC ", "0", "0"), ("العربية", "1", "1"), (" 123", "0", "1")],
    ]


def test_explicit_span_isolate_wraps_spaces_and_soft_breaks(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text("[ABC DEF]{dir=rtl} [GHI\nJKL]{dir=rtl}\n", encoding="utf-8")
    output = MarkdownToDocxConverter().convert(source, lang="en", offline=True)
    paragraph = parts(output)["word/document.xml"].find(W + "body/" + W + "p")

    assert paragraph_text(paragraph) == ("\u2067ABC DEF\u2069 \u2067GHI JKL\u2069")
    assert bidi_scopes(paragraph) == [
        [(" ", "0", "0")],
        [("ABC DEF", "0", "0")],
        [("GHI JKL", "0", "0")],
    ]


def test_inline_code_uses_ltr_isolate_without_overriding_strong_script(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text("العربية `ABC العربية 123` العربية\n", encoding="utf-8")
    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="ar", offline=True
    )
    paragraph = parts(report.output_path)["word/document.xml"].find(
        W + "body/" + W + "p"
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    assert paragraph_text(paragraph) == ("العربية \u2066ABC العربية 123\u2069 العربية")
    assert bidi_scopes(paragraph) == [
        [
            ("العربية", "1", "1"),
            ("  ", "0", "1"),
            ("العربية", "1", "1"),
        ],
        [("ABC ", "0", "0"), ("العربية", "1", "1"), (" 123", "0", "1")],
    ]


def test_annotate_removes_span_dir_but_preserves_div_direction():
    from markdown2docx.multilingual import MultilingualDocument

    ast = {
        "meta": {},
        "blocks": [
            {
                "t": "Para",
                "c": [
                    {
                        "t": "Span",
                        "c": [["", [], [["dir", "rtl"]]], [{"t": "Str", "c": "ABC"}]],
                    }
                ],
            },
            {
                "t": "Div",
                "c": [
                    ["", [], [["dir", "rtl"]]],
                    [
                        {
                            "t": "Para",
                            "c": [
                                {
                                    "t": "Span",
                                    "c": [
                                        ["", [], [["dir", "ltr"]]],
                                        [{"t": "Str", "c": "DEF"}],
                                    ],
                                }
                            ],
                        }
                    ],
                ],
            },
        ],
    }
    document = MultilingualDocument(ast, FontResolver(), lang="en")

    document.annotate()

    span = document.ast["blocks"][0]["c"][0]
    div = document.ast["blocks"][1]
    nested_span = div["c"][1][0]["c"][0]
    assert "dir" not in dict(span["c"][0][2])
    assert "dir" not in dict(nested_span["c"][0][2])
    assert dict(div["c"][0][2])["dir"] == "rtl"


def test_nested_span_and_div_directions_are_inherited_and_restored(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text(
        "[outer [inner]{dir=ltr} tail]{dir=rtl}\n\n"
        "::: {dir=rtl}\n\n[ABC]{dir=ltr}\n\n"
        "::: {dir=ltr}\n\n[DEF]{dir=rtl}\n\n:::\n\n:::\n",
        encoding="utf-8",
    )
    output = MarkdownToDocxConverter().convert(source, lang="en", offline=True)
    paragraphs = parts(output)["word/document.xml"].findall(W + "body/" + W + "p")

    assert [
        paragraph.find(W + "pPr/" + W + "bidi").get(W + "val")
        for paragraph in paragraphs
    ] == ["0", "1", "0"]
    assert [paragraph_text(paragraph) for paragraph in paragraphs] == [
        "\u2067outer \u2066inner\u2069 tail\u2069",
        "\u2066ABC\u2069",
        "\u2067DEF\u2069",
    ]
    assert [bidi_scopes(paragraph) for paragraph in paragraphs] == [
        [[("outer  tail", "0", "0")], [("inner", "0", "0")]],
        [[("ABC", "0", "0")]],
        [[("DEF", "0", "0")]],
    ]


@pytest.mark.parametrize(
    "code_leading", [False, True], ids=["empty-note", "code-leading-note"]
)
def test_directional_empty_or_code_leading_footnote_does_not_leak(
    tmp_path, code_leading
):
    source = tmp_path / "direction.md"
    footnote = "[^n]:\n"
    if code_leading:
        footnote += "    ```text\n    ABC\n    ```\n"
    source.write_text(
        f"[[^n]]{{dir=rtl}} tail\n\n```text\nbody\n```\n\n{footnote}",
        encoding="utf-8",
    )

    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="en", offline=True
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    roots = parts(report.output_path)
    paragraph = roots["word/document.xml"].find(W + "body/" + W + "p")
    assert paragraph_text(paragraph) == "\u2067\u2069 tail"
    if code_leading:
        code = roots["word/footnotes.xml"].xpath(
            "//w:p[w:pPr/w:pStyle[@w:val='SourceCode']]", namespaces=NS
        )
        assert [paragraph_text(item) for item in code] == ["ABC"]
    for root in roots.values():
        assert not root.xpath("//w:pPr/w:bidi[@w:val='1']", namespaces=NS)
        assert not root.xpath("//w:r[w:t]/w:rPr/w:rtl[@w:val='1']", namespaces=NS)


def test_note_boundary_resets_outer_span_direction(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text(
        "[outer[^note]]{dir=rtl}\n\n[^note]: Latin footnote\n", encoding="utf-8"
    )
    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="en", offline=True
    )
    roots = parts(report.output_path)
    paragraph = roots["word/document.xml"].find(W + "body/" + W + "p")
    footnote = next(
        item
        for item in roots["word/footnotes.xml"].iter(W + "p")
        if "Latin footnote" in paragraph_text(item)
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    assert paragraph_text(paragraph) == "\u2067outer\u2069"
    assert bidi_scopes(paragraph) == [[("outer", "0", "0")]]
    assert paragraph_text(footnote).strip() == "Latin footnote"
    assert footnote.find(W + "pPr/" + W + "bidi").get(W + "val") == "0"
    assert bidi_scopes(footnote) == [[(" Latin footnote", "0", "0")]]


def test_table_footnote_and_inline_code_keep_isolated_direction(tmp_path):
    source = tmp_path / "direction.md"
    source.write_text(
        "::: {dir=rtl}\n\n"
        "| [ABC]{dir=rtl} | `العربية 123` |\n"
        "|---|---|\n"
        "| [note[^n]]{dir=rtl} | plain |\n\n"
        ":::\n\n"
        "[^n]: Footnote Latin\n",
        encoding="utf-8",
    )
    report = MarkdownToDocxConverter().convert_with_report(
        source, lang="ar", offline=True
    )
    roots = parts(report.output_path)
    paragraphs = roots["word/document.xml"].xpath("//w:tbl//w:p", namespaces=NS)
    footnote = next(
        item
        for item in roots["word/footnotes.xml"].iter(W + "p")
        if "Footnote Latin" in paragraph_text(item)
    )

    assert report.checks["text_integrity"] == report.checks["font_coverage"] == "passed"
    assert [paragraph_text(paragraph) for paragraph in paragraphs] == [
        "\u2067ABC\u2069",
        "\u2066العربية 123\u2069",
        "\u2067note\u2069",
        "plain",
    ]
    assert [
        paragraph.find(W + "pPr/" + W + "bidi").get(W + "val")
        for paragraph in paragraphs
    ] == ["1", "1", "1", "1"]
    assert [bidi_scopes(paragraph) for paragraph in paragraphs] == [
        [[("ABC", "0", "0")]],
        [[("العربية", "1", "1"), (" 123", "0", "1")]],
        [[("note", "0", "0")]],
        [[("plain", "0", "0")]],
    ]
    assert paragraph_text(footnote).strip() == "Footnote Latin"
    assert footnote.find(W + "pPr/" + W + "bidi").get(W + "val") == "1"
    assert bidi_scopes(footnote) == [
        [(" ", "0", "1"), ("Footnote", "0", "0"), (" ", "0", "1"), ("Latin", "0", "0")]
    ]


def test_verify_output_rejects_removed_direction_isolates(tmp_path, monkeypatch):
    from markdown2docx.multilingual import MultilingualDocument

    source = tmp_path / "direction.md"
    source.write_text("[ABC]{dir=rtl}\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"original")
    verify = MultilingualDocument._verify_output
    remove_controls = {ord(char): None for char in BIDI_CONTROLS}

    def remove_isolates_then_verify(self, candidate):
        def remove(root):
            for node in root.xpath("//w:t", namespaces=NS):
                node.text = (node.text or "").translate(remove_controls)

        rewrite_docx(candidate, {"word/document.xml": remove})
        verify(self, candidate)

    monkeypatch.setattr(
        MultilingualDocument, "_verify_output", remove_isolates_then_verify
    )
    with pytest.raises(ValidationError) as error:
        MarkdownToDocxConverter().convert(source, output, lang="en", offline=True)
    assert output.read_bytes() == b"original"
    assert any(
        "text structure mismatch" in message or "run stream count mismatch" in message
        for message in error.value.validation_errors
    )


@pytest.mark.parametrize(
    "corruption", ["rtl", "bidi"], ids=["run-direction", "paragraph-direction"]
)
def test_verify_output_rejects_corrupted_strong_script_direction(
    tmp_path, monkeypatch, corruption
):
    from xml.sax.saxutils import escape

    from markdown2docx.multilingual import MultilingualDocument

    document = MultilingualDocument(
        {
            "meta": {},
            "blocks": [
                {
                    "t": "Div",
                    "c": [
                        ["", [], [["dir", "rtl"]]],
                        [
                            {
                                "t": "Para",
                                "c": [
                                    {
                                        "t": "Span",
                                        "c": [
                                            ["", [], [["dir", "rtl"]]],
                                            [{"t": "Str", "c": "العربية"}],
                                        ],
                                    }
                                ],
                            }
                        ],
                    ],
                }
            ],
        },
        FontResolver(),
        lang="ar",
    )
    document.annotate()
    paragraph = "".join(
        f'<w:r><w:rPr><w:rStyle w:val="{marker}"/></w:rPr>'
        f"<w:t>{escape(spec.text)}</w:t></w:r>"
        for marker, spec in document.runs.items()
    )
    path = generated_docx(tmp_path, paragraph)
    original = path.read_bytes()
    if corruption == "rtl":
        properties = document._properties

        def corrupt_run_direction(run, spec):
            properties(run, spec)
            run.find(W + "rPr/" + W + "rtl").set(W + "val", "0")

        monkeypatch.setattr(document, "_properties", corrupt_run_direction)
    else:
        paragraph_direction = document._paragraph

        def corrupt_paragraph_direction(paragraph, value):
            paragraph_direction(paragraph, value)
            paragraph.find(W + "pPr/" + W + "bidi").set(W + "val", "0")

        monkeypatch.setattr(document, "_paragraph", corrupt_paragraph_direction)

    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any(
        "rtl mismatch" in message
        if corruption == "rtl"
        else "paragraph direction mismatch" in message
        for message in error.value.validation_errors
    )
    assert path.read_bytes() == original


def test_metadata_precedence_and_ui_independence(tmp_path):
    config = MarkdownToDocxConfig()
    config.international.lang = "ru"
    source = tmp_path / "language.md"
    source.write_text("---\nlang: fr\ndir: rtl\n---\n\nBonjour café\n")
    converter = MarkdownToDocxConverter(config=config)
    report = converter.convert_with_report(source)
    assert report.language == "fr"
    report = converter.convert_with_report(source, lang="es", direction="ltr")
    assert report.language == "es"
    root = parts(Path(report.output_path))["word/document.xml"]
    assert root.xpath("//w:pPr/w:bidi[@w:val='0']", namespaces=NS)
    assert not root.xpath("//w:pPr/w:bidi[@w:val='1']", namespaces=NS)


def test_ambiguity_and_emoji_are_reported(tmp_path):
    source = tmp_path / "ambiguous.md"
    source.write_text("漢字 🚀")
    report = MarkdownToDocxConverter().convert_with_report(source)
    assert {item["code"] for item in report.warnings} >= {
        "CJK_LANGUAGE_AMBIGUOUS",
        "EMOJI_UNVERIFIED",
    }


def test_invalid_language_and_direction(tmp_path):
    source = tmp_path / "bad.md"
    source.write_text("Text")
    for options in ({"lang": "invalid-language-value"}, {"direction": "up"}):
        with pytest.raises(ConfigurationError):
            MarkdownToDocxConverter().convert(source, **options)


def test_lost_text_does_not_replace_existing_document(tmp_path, monkeypatch):
    source = tmp_path / "input.md"
    source.write_text("Important 中文 العربية")
    output = source.with_suffix(".docx")
    output.write_bytes(b"original")

    from markdown2docx.runner import write_docx

    original = write_docx

    def lose_text(*args, outputfile, **kwargs):
        original(*args, outputfile=outputfile, **kwargs)
        with zipfile.ZipFile(outputfile) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        root = etree.fromstring(entries["word/document.xml"])
        root.find(".//" + W + "t").text = "lost"
        entries["word/document.xml"] = etree.tostring(root)
        with zipfile.ZipFile(outputfile, "w") as archive:
            for name, value in entries.items():
                archive.writestr(name, value)

    monkeypatch.setattr("markdown2docx.converter.write_docx", lose_text)
    with pytest.raises(ValidationError) as error:
        MarkdownToDocxConverter().convert(source, output)
    assert error.value.output_file == str(output)
    assert output.read_bytes() == b"original"


def test_json_cli_and_diagnostics(tmp_path):
    source = tmp_path / "input.md"
    source.write_text("中文 café Русский العربية")
    command = [sys.executable, "-m", "markdown2docx.cli"]
    result = subprocess.run(
        [*command, str(source), "--json", "--ui-lang", "zh"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["checks"]["text_integrity"] == "passed"
    result = subprocess.run(
        [*command, "--doctor", "--json"], capture_output=True, text=True
    )
    assert result.returncode == 0 and json.loads(result.stdout)["pandoc"]
    result = subprocess.run(
        [*command, str(source), "--json", "--direction", "up"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.skipif(os.name != "nt", reason="Windows directory handles")
def test_windows_atomic_output(tmp_path):
    from markdown2docx.output import staged_docx_output

    output = tmp_path / "new" / "document.docx"
    with staged_docx_output(output) as stage:
        stage.write_bytes(b"new")
    with pytest.raises(RuntimeError):
        with staged_docx_output(output) as stage:
            stage.write_bytes(b"bad")
            raise RuntimeError("failed")
    assert output.read_bytes() == b"new"
    with pytest.raises(FileExistsError):
        with staged_docx_output(output, overwrite=False):
            pass


@pytest.mark.parametrize("emoji", ["🇨🇳", "👍🏽", "1️⃣", "👩‍💻", "❤️"])
@pytest.mark.parametrize("formatting", ["{}", "`{}`", "```text\n{}\n```"])
def test_emoji_sequences_warn_without_losing_text(tmp_path, emoji, formatting):
    source = tmp_path / "emoji.md"
    source.write_text(formatting.format(emoji), encoding="utf-8")
    report = MarkdownToDocxConverter().convert_with_report(source)
    assert report.checks["font_coverage"] == "unverified"
    assert report.checks["text_integrity"] == "passed"
    assert any(item["code"] == "EMOJI_UNVERIFIED" for item in report.warnings)
    root = parts(report.output_path)["word/document.xml"]
    assert emoji in "".join(root.xpath("//w:t/text()", namespaces=NS))


@pytest.mark.parametrize("line_break", ["", "<w:br/>"])
def test_writer_generated_emoji_runs_are_unverified(tmp_path, line_break):
    from markdown2docx.multilingual import MultilingualDocument

    path = tmp_path / "generated.docx"
    # Cover both simple unmarked text and runs that also contain a break.
    xml = f'<w:document xmlns:w="{NS["w"]}"><w:body><w:p><w:r><w:t>🇺🇳 👍🏽 1️⃣</w:t>{line_break}</w:r></w:p></w:body></w:document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    checks = document.apply(path)
    assert checks["font_coverage"] == "unverified"
    assert any(item["code"] == "EMOJI_UNVERIFIED" for item in document.warnings)
    assert "🇺🇳 👍🏽 1️⃣" == "".join(
        parts(path)["word/document.xml"].xpath("//w:t/text()", namespaces=NS)
    )


def test_mixed_run_with_break_splits_fonts_and_preserves_order(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(
        tmp_path,
        '<w:r w:rsidRPr="00112233" w:rsidR="44556677" w:rsidDel="8899AABB">'
        "<w:rPr><w:b/></w:rPr><w:t>English中文العربية</w:t><w:br/></w:r>",
    )
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    assert document.apply(path)["text_integrity"] == "passed"

    paragraph = parts(path)["word/document.xml"].find(".//" + W + "p")
    events = []
    text_runs = []
    for run in paragraph.findall(W + "r"):
        for child in run:
            if child.tag == W + "t":
                events.append(child.text or "")
                text_runs.append(run)
            elif child.tag == W + "br":
                events.append("br")
    assert events == ["English", "中文", "العربية", "br"]
    assert [
        run.find(W + "rPr/" + W + "rFonts").get(W + "ascii") for run in text_runs
    ] == ["Noto Sans", "Noto Sans CJK SC", "Noto Sans Arabic"]
    assert all(run.find(W + "rPr/" + W + "b") is not None for run in text_runs)
    assert text_runs[-1].find(W + "rPr/" + W + "rtl").get(W + "val") == "1"
    assert all(
        run.attrib
        == {
            W + "rsidRPr": "00112233",
            W + "rsidR": "44556677",
            W + "rsidDel": "8899AABB",
        }
        for run in paragraph.findall(W + "r")
    )


def test_multiple_text_nodes_preserve_mixed_fonts_and_child_order(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(
        tmp_path,
        "<w:r>"
        "<w:t>English中</w:t>"
        '<w:bookmarkStart w:id="7" w:name="mixed"/>'
        "<w:t>文الع</w:t>"
        "<w:tab/>"
        "<w:t>ربية</w:t>"
        '<w:bookmarkEnd w:id="7"/>'
        "</w:r>",
    )
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    document.apply(path)

    paragraph = parts(path)["word/document.xml"].find(".//" + W + "p")
    events = []
    text_runs = []
    for run in paragraph.findall(W + "r"):
        for child in run:
            if child.tag == W + "t":
                events.append(child.text or "")
                text_runs.append(run)
            elif child.tag == W + "bookmarkStart":
                events.append(("bookmarkStart", child.get(W + "name")))
            elif child.tag == W + "bookmarkEnd":
                events.append(("bookmarkEnd", child.get(W + "id")))
            elif child.tag == W + "tab":
                events.append("tab")
    assert events == [
        "English",
        "中",
        ("bookmarkStart", "mixed"),
        "文",
        "الع",
        "tab",
        "ربية",
        ("bookmarkEnd", "7"),
    ]
    assert [
        run.find(W + "rPr/" + W + "rFonts").get(W + "ascii") for run in text_runs
    ] == [
        "Noto Sans",
        "Noto Sans CJK SC",
        "Noto Sans CJK SC",
        "Noto Sans Arabic",
        "Noto Sans Arabic",
    ]


def test_split_run_preserves_edge_whitespace_in_serialized_xml(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, "<w:r><w:t> English中文العربية </w:t></w:r>")
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    document.apply(path)

    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = etree.fromstring(xml)
    text_nodes = root.xpath("//w:t", namespaces=NS)
    assert [node.text for node in text_nodes] == [
        " English",
        "中文",
        "العربية",
        " ",
    ]
    xml_space = "{http://www.w3.org/XML/1998/namespace}space"
    for node in text_nodes:
        value = node.text or ""
        if value.startswith(" ") or value.endswith(" "):
            assert node.get(xml_space) == "preserve"
    assert xml.count(b'xml:space="preserve"') == 2


def test_split_run_rejects_nested_text_it_cannot_safely_split(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(
        tmp_path,
        "<w:r><w:t>English中文</w:t>"
        "<w:smartTag><w:r><w:t>nested</w:t></w:r></w:smartTag></w:r>",
    )
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert error.value.output_file == str(path)
    assert any(
        "cannot safely split run" in message.lower()
        for message in error.value.validation_errors
    )


@pytest.mark.parametrize(
    "corruption",
    ["swap", "delete", "extra-unstyled", "extra-wrong-font"],
)
def test_verify_output_rejects_text_run_stream_corruption(
    tmp_path, monkeypatch, corruption
):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, "<w:r><w:t>English中文</w:t></w:r>")
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    verify = document._verify_output

    def corrupt_then_verify(candidate):
        with zipfile.ZipFile(candidate) as archive:
            xml = archive.read("word/document.xml")
        root = etree.fromstring(xml)
        paragraph = root.find(".//" + W + "p")
        text_runs = root.xpath("//w:r[w:t]", namespaces=NS)
        if corruption == "swap":
            first = text_runs[0].find(W + "t")
            second = text_runs[1].find(W + "t")
            first.text, second.text = second.text, first.text
        elif corruption == "delete":
            paragraph.remove(text_runs[0])
        else:
            extra = etree.SubElement(paragraph, W + "r")
            if corruption == "extra-wrong-font":
                props = etree.SubElement(extra, W + "rPr")
                fonts = etree.SubElement(props, W + "rFonts")
                for slot in ("ascii", "hAnsi", "eastAsia", "cs"):
                    fonts.set(W + slot, "Wrong Font")
            etree.SubElement(extra, W + "t").text = "extra"
        with zipfile.ZipFile(candidate, "w") as archive:
            archive.writestr("word/document.xml", etree.tostring(root))
        verify(candidate)

    monkeypatch.setattr(document, "_verify_output", corrupt_then_verify)
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any(
        "run stream" in message
        or "run text mismatch" in message
        or "font coverage mismatch" in message
        for message in error.value.validation_errors
    )


@pytest.mark.parametrize(
    ("code", "paragraph"),
    [
        pytest.param(
            "one\n",
            '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
            "<w:r><w:t>one</w:t></w:r></w:p>",
            id="trailing-newline",
        ),
        pytest.param(
            "\n",
            '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr></w:p>',
            id="single-empty-line",
        ),
        pytest.param(
            "",
            '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr></w:p>',
            id="empty",
        ),
        pytest.param(
            "one\n\n",
            '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
            "<w:r><w:t>one</w:t></w:r><w:r><w:br/></w:r></w:p>",
            id="trailing-blank-line",
        ),
        pytest.param(
            "one\u2028two",
            '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
            "<w:r><w:t>one\u2028two</w:t></w:r></w:p>",
            id="unicode-line-separator",
        ),
        pytest.param(
            "one\u0085two",
            '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
            "<w:r><w:t>one\u0085two</w:t></w:r></w:p>",
            id="next-line",
        ),
    ],
)
def test_code_block_line_expectations_follow_text_lines(tmp_path, code, paragraph):
    from markdown2docx.multilingual import MultilingualDocument

    document = MultilingualDocument(
        {"meta": {}, "blocks": [{"t": "CodeBlock", "c": [["", [], []], code]}]},
        FontResolver(),
        lang="en",
    )
    document.annotate()
    anchor = next(iter(document.code_languages))
    path = generated_body_docx(
        tmp_path,
        f'<w:bookmarkStart w:id="1" w:name="_{anchor}"/>'
        f"{paragraph}"
        '<w:bookmarkEnd w:id="1"/>',
    )
    assert document.apply(path)["text_integrity"] == "passed"


@pytest.mark.parametrize("code_first", [True, False], ids=["code-first", "div-first"])
def test_duplicate_code_bookmark_on_plain_div_does_not_pollute_code_text(
    tmp_path, code_first
):
    from markdown2docx.multilingual import MultilingualDocument

    code_block = {"t": "CodeBlock", "c": [["shared", ["text"], []], "code"]}
    div_block = {
        "t": "Div",
        "c": [
            ["shared", [], [["custom-style", "SourceCode"]]],
            [{"t": "Para", "c": [{"t": "Str", "c": "ordinary"}]}],
        ],
    }
    document = MultilingualDocument(
        {
            "meta": {},
            "blocks": [code_block, div_block]
            if code_first
            else [div_block, code_block],
        },
        FontResolver(),
        lang="en",
    )
    document.annotate()
    marker = next(iter(document.runs))
    code_paragraph = (
        '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
        "<w:r><w:t>code</w:t></w:r></w:p>"
    )
    ordinary_paragraph = (
        '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
        f'<w:r><w:rPr><w:rStyle w:val="{marker}"/></w:rPr>'
        "<w:t>ordinary</w:t></w:r></w:p>"
    )
    first, second = (
        (code_paragraph, ordinary_paragraph)
        if code_first
        else (ordinary_paragraph, code_paragraph)
    )
    path = generated_body_docx(
        tmp_path,
        '<w:bookmarkStart w:id="1" w:name="_shared"/>'
        f"{first}"
        '<w:bookmarkEnd w:id="1"/>'
        '<w:bookmarkStart w:id="2" w:name="_shared"/>'
        f"{second}"
        '<w:bookmarkEnd w:id="2"/>',
    )
    assert document.apply(path)["text_integrity"] == "passed"
    paragraphs = parts(path)["word/document.xml"].findall(W + "body/" + W + "p")
    assert [
        "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
        for paragraph in paragraphs
    ] == (["code", "ordinary"] if code_first else ["ordinary", "code"])
    assert [
        paragraph.find(W + "r/" + W + "rPr/" + W + "rFonts").get(W + "ascii")
        for paragraph in paragraphs
    ] == (
        ["Noto Sans Mono", "Noto Sans"]
        if code_first
        else ["Noto Sans", "Noto Sans Mono"]
    )


def test_same_text_code_bookmark_collision_uses_real_code_block(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    code_block = {"t": "CodeBlock", "c": [["shared", ["text"], []], "same"]}
    document = MultilingualDocument(
        {
            "meta": {},
            "blocks": [
                {
                    "t": "Div",
                    "c": [
                        ["shared", [], [["custom-style", "SourceCode"]]],
                        [{"t": "Para", "c": [{"t": "Str", "c": "same"}]}],
                    ],
                },
                {
                    "t": "Div",
                    "c": [["", [], [["lang", "ja"]]], [code_block]],
                },
            ],
        },
        FontResolver(),
        lang="en",
    )
    document.annotate()
    marker = next(iter(document.runs))
    path = generated_body_docx(
        tmp_path,
        '<w:bookmarkStart w:id="1" w:name="_shared"/>'
        '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
        f'<w:r><w:rPr><w:rStyle w:val="{marker}"/></w:rPr>'
        "<w:t>same</w:t></w:r></w:p>"
        '<w:bookmarkEnd w:id="1"/>'
        '<w:bookmarkStart w:id="2" w:name="_shared"/>'
        '<w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
        "<w:r><w:t>same</w:t></w:r></w:p>"
        '<w:bookmarkEnd w:id="2"/>',
    )
    assert document.apply(path)["text_integrity"] == "passed"
    paragraphs = parts(path)["word/document.xml"].findall(W + "body/" + W + "p")
    assert [
        paragraph.find(W + "r/" + W + "rPr/" + W + "rFonts").get(W + "ascii")
        for paragraph in paragraphs
    ] == ["Noto Sans", "Noto Sans Mono"]
    assert [
        paragraph.find(W + "r/" + W + "rPr/" + W + "lang").get(W + "val")
        for paragraph in paragraphs
    ] == ["en", "ja"]
    assert [
        paragraph.find(W + "r/" + W + "rPr/" + W + "rtl").get(W + "val")
        for paragraph in paragraphs
    ] == ["0", "0"]
    assert paragraphs[1].find(W + "pPr/" + W + "bidi").get(W + "val") == "0"


def test_source_code_paragraph_style_is_not_a_code_block(tmp_path):
    source = tmp_path / "input.md"
    source.write_text(
        '::: {custom-style="SourceCode"}\nordinary paragraph\n:::\n',
        encoding="utf-8",
    )
    output = tmp_path / "output.docx"
    report = MarkdownToDocxConverter().convert_with_report(source, output)
    assert report.checks["text_integrity"] == "passed"
    root = parts(output)["word/document.xml"]
    paragraph = root.find(W + "body/" + W + "p")
    assert paragraph.find(W + "pPr/" + W + "pStyle").get(W + "val") == "SourceCode"
    assert "".join(paragraph.xpath(".//w:t/text()", namespaces=NS)) == (
        "ordinary paragraph"
    )
    assert {
        run.find(W + "rPr/" + W + "rFonts").get(W + "ascii")
        for run in paragraph.findall(W + "r")
        if run.find(W + "t") is not None
    } == {"Noto Sans"}


def test_section_number_style_is_verified_without_number_sections(tmp_path):
    source = tmp_path / "input.md"
    source.write_text('[real]{custom-style="SectionNumber"}\n', encoding="utf-8")
    output = tmp_path / "output.docx"
    report = MarkdownToDocxConverter().convert_with_report(source, output)
    assert report.checks["text_integrity"] == "passed"
    root = parts(output)["word/document.xml"]
    assert root.xpath("//w:body/w:p/w:r/w:t/text()", namespaces=NS) == ["real"]
    assert root.xpath(
        "//w:body/w:p/w:r/w:rPr/w:rStyle[@w:val='SectionNumber']",
        namespaces=NS,
    )


@pytest.mark.parametrize("text", ["real", "123"])
def test_user_section_number_style_survives_number_sections(tmp_path, text):
    source = tmp_path / "input.md"
    source.write_text(f'[{text}]{{custom-style="SectionNumber"}}\n', encoding="utf-8")
    output = tmp_path / "output.docx"
    report = MarkdownToDocxConverter().convert_with_report(
        source, output, extra_args=["--number-sections"]
    )
    assert report.checks["text_integrity"] == "passed"
    root = parts(output)["word/document.xml"]
    assert root.xpath("//w:body/w:p/w:r/w:t/text()", namespaces=NS) == [text]
    assert root.xpath(
        "//w:body/w:p/w:r/w:rPr/w:rStyle[@w:val='SectionNumber']",
        namespaces=NS,
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "delete-space",
        "delete-soft-break",
        "delete-line-break",
        "delete-line-block-break",
        "delete-code-break",
        "move-code-break",
        "delete-code-anchor",
        "break-code-bookmark-pair",
        "change-code-style",
        "split-definition-term",
        "merge-definition-term",
        "split-toc-title",
        "merge-toc-title",
        "merge-paragraphs",
        "split-paragraph",
        "swap-paragraphs",
        "cross-part-move",
    ],
)
def test_verify_output_rejects_structural_text_corruption(
    tmp_path, monkeypatch, corruption
):
    from markdown2docx.multilingual import MultilingualDocument

    source = tmp_path / "input.md"
    config = MarkdownToDocxConfig()
    toc = False
    if corruption == "cross-part-move":
        source.write_text("Body[^note]\n\n[^note]: Footnote\n", encoding="utf-8")
    elif corruption in {
        "delete-code-break",
        "move-code-break",
        "delete-code-anchor",
        "break-code-bookmark-pair",
        "change-code-style",
    }:
        source.write_text("```text\none\ntwo\n```\n", encoding="utf-8")
    elif corruption == "delete-line-block-break":
        config.pandoc.reader_format = (
            "markdown+footnotes+tex_math_dollars+fenced_divs+bracketed_spans"
            "+yaml_metadata_block+line_blocks"
        )
        source.write_text("| line one\n| line two\n", encoding="utf-8")
    elif corruption in {"split-definition-term", "merge-definition-term"}:
        config.pandoc.reader_format = (
            "markdown+footnotes+tex_math_dollars+fenced_divs+bracketed_spans"
            "+yaml_metadata_block+definition_lists"
        )
        source.write_text("Long term\n: definition\n", encoding="utf-8")
    elif corruption in {"split-toc-title", "merge-toc-title"}:
        toc = True
        source.write_text(
            "---\ntoc-title: Long Contents\n---\n\n# Heading\n\nBody\n",
            encoding="utf-8",
        )
    else:
        source.write_text("alpha beta\\\ngamma\nsoft\n\nsecond\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"original")
    verify = MultilingualDocument._verify_output

    def corrupt_document(root):
        body = root.find(W + "body")
        paragraphs = body.findall(W + "p")
        first = (
            root.xpath("//w:p[w:pPr/w:pStyle[@w:val='TOCHeading']]", namespaces=NS)[0]
            if corruption in {"split-toc-title", "merge-toc-title"}
            else paragraphs[0]
        )
        if corruption in {"delete-space", "delete-soft-break"}:
            spaces = first.xpath("./w:r/w:t[text()=' ']", namespaces=NS)
            spaces[0 if corruption == "delete-space" else 1].text = ""
        elif corruption in {"delete-line-break", "delete-line-block-break"}:
            line_break = first.find(".//" + W + "br")
            line_break.getparent().remove(line_break)
        elif corruption == "delete-code-break":
            line_break = first.find(".//" + W + "br")
            line_break.getparent().remove(line_break)
        elif corruption == "move-code-break":
            line_break = first.find(".//" + W + "br")
            line_break.getparent().remove(line_break)
            last_text_run = first.xpath("./w:r[w:t][last()]", namespaces=NS)[0]
            last_text_run.append(line_break)
        elif corruption == "delete-code-anchor":
            anchor = first.getprevious()
            assert anchor is not None and anchor.tag == W + "bookmarkStart"
            body.remove(anchor)
        elif corruption == "break-code-bookmark-pair":
            anchor_end = first.getnext()
            assert anchor_end is not None and anchor_end.tag == W + "bookmarkEnd"
            anchor_end.set(W + "id", "mismatched")
        elif corruption == "change-code-style":
            first.find(W + "pPr/" + W + "pStyle").set(W + "val", "BodyText")
        elif corruption in {"split-definition-term", "split-toc-title"}:
            wanted = "term" if corruption == "split-definition-term" else "Contents"
            split_at = next(
                index
                for index, child in enumerate(first)
                if child.tag == W + "r"
                and wanted in "".join(child.xpath("./w:t/text()", namespaces=NS))
            )
            second = etree.Element(W + "p")
            props = first.find(W + "pPr")
            if props is not None:
                second.append(copy.deepcopy(props))
            for child in list(first)[split_at:]:
                second.append(child)
            parent = first.getparent()
            parent.insert(parent.index(first) + 1, second)
        elif corruption in {"merge-definition-term", "merge-toc-title"}:
            second = (
                root.xpath(
                    "//w:body/w:p[w:pPr/w:pStyle[@w:val='Heading1']]",
                    namespaces=NS,
                )[0]
                if corruption == "merge-toc-title"
                else paragraphs[1]
            )
            insert_at = 1 if second.find(W + "pPr") is not None else 0
            children = [child for child in first if child.tag != W + "pPr"]
            for offset, child in enumerate(children):
                second.insert(insert_at + offset, child)
            first.getparent().remove(first)
        elif corruption == "merge-paragraphs":
            second = paragraphs[1]
            for child in list(second):
                if child.tag != W + "pPr":
                    first.append(child)
            body.remove(second)
        elif corruption == "split-paragraph":
            split_at = next(
                index
                for index, child in enumerate(first)
                if child.tag == W + "r"
                and "gamma" in "".join(child.xpath("./w:t/text()", namespaces=NS))
            )
            second = etree.Element(W + "p")
            props = first.find(W + "pPr")
            if props is not None:
                second.append(copy.deepcopy(props))
            for child in list(first)[split_at:]:
                second.append(child)
            body.insert(body.index(first) + 1, second)
        elif corruption == "swap-paragraphs":
            second = paragraphs[1]
            body.remove(second)
            body.insert(body.index(first), second)

    def corrupt_footnotes(root):
        stored = root.xpath("//w:r[w:t[contains(., 'Footnote')]]", namespaces=NS)[0]
        stored.getparent().remove(stored)

    def move_note_to_body(root):
        body = root.find(W + "body")
        body.findall(W + "p")[0].append(copy.deepcopy(note))

    note = None

    def corrupt_then_verify(self, candidate):
        nonlocal note
        mutations = {"word/document.xml": corrupt_document}
        if corruption == "cross-part-move":
            with zipfile.ZipFile(candidate) as archive:
                footnote_root = etree.fromstring(archive.read("word/footnotes.xml"))
            note = footnote_root.xpath(
                "//w:r[w:t[contains(., 'Footnote')]]", namespaces=NS
            )[0]
            mutations["word/footnotes.xml"] = corrupt_footnotes
            mutations["word/document.xml"] = move_note_to_body
        rewrite_docx(candidate, mutations)
        verify(self, candidate)

    monkeypatch.setattr(MultilingualDocument, "_verify_output", corrupt_then_verify)
    with pytest.raises(ValidationError):
        MarkdownToDocxConverter(config=config).convert(source, output, toc=toc)
    assert output.read_bytes() == b"original"


@pytest.mark.parametrize("mode", ["metadata", "args"])
@pytest.mark.parametrize("corruption", ["split", "merge"])
def test_effective_toc_title_is_modeled_and_verified(
    tmp_path, monkeypatch, mode, corruption
):
    from markdown2docx.multilingual import MultilingualDocument

    source = tmp_path / "input.md"
    metadata = "toc: true\n" if mode == "metadata" else ""
    source.write_text(
        f"---\n{metadata}toc-title: Long Contents\n---\n\n# Heading\n\nBody\n",
        encoding="utf-8",
    )
    output = tmp_path / "output.docx"
    output.write_bytes(b"original")
    seen_toc = []
    annotate = MultilingualDocument.annotate

    def record_toc(self, *, toc=False):
        seen_toc.append(toc)
        return annotate(self, toc=toc)

    monkeypatch.setattr(MultilingualDocument, "annotate", record_toc)
    verify = MultilingualDocument._verify_output

    def corrupt_then_verify(self, candidate):
        def corrupt(root):
            title = root.xpath(
                "//w:p[w:pPr/w:pStyle[@w:val='TOCHeading']]", namespaces=NS
            )[0]
            heading = root.xpath(
                "//w:body/w:p[w:pPr/w:pStyle[@w:val='Heading1']]", namespaces=NS
            )[0]
            children = [child for child in title if child.tag != W + "pPr"]
            if corruption == "split":
                split_at = max(1, len(children) // 2)
                second = etree.Element(W + "p")
                props = title.find(W + "pPr")
                if props is not None:
                    second.append(copy.deepcopy(props))
                for child in children[split_at:]:
                    second.append(child)
                parent = title.getparent()
                parent.insert(parent.index(title) + 1, second)
            else:
                insert_at = 1 if heading.find(W + "pPr") is not None else 0
                for offset, child in enumerate(children):
                    heading.insert(insert_at + offset, child)
                title.getparent().remove(title)

        rewrite_docx(candidate, {"word/document.xml": corrupt})
        verify(self, candidate)

    monkeypatch.setattr(MultilingualDocument, "_verify_output", corrupt_then_verify)
    with pytest.raises(ValidationError):
        MarkdownToDocxConverter().convert(
            source,
            output,
            toc=False,
            extra_args=["--toc"] if mode == "args" else None,
        )
    assert output.read_bytes() == b"original"
    assert seen_toc == [True]


def test_structural_errors_report_paragraph_and_events(tmp_path, monkeypatch):
    from markdown2docx.multilingual import MultilingualDocument

    source = tmp_path / "input.md"
    source.write_text("alpha beta\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"original")
    verify = MultilingualDocument._verify_output

    def delete_space_then_verify(self, candidate):
        def delete_space(root):
            node = root.xpath("//w:body/w:p/w:r/w:t[text()=' ']", namespaces=NS)[0]
            node.text = ""

        rewrite_docx(candidate, {"word/document.xml": delete_space})
        verify(self, candidate)

    monkeypatch.setattr(
        MultilingualDocument, "_verify_output", delete_space_then_verify
    )
    with pytest.raises(ValidationError) as error:
        MarkdownToDocxConverter().convert(source, output)
    assert output.read_bytes() == b"original"
    assert any(
        "paragraph 0" in message and "expected" in message and "actual" in message
        for message in error.value.validation_errors
    )


def test_structural_error_event_repr_is_truncated(tmp_path, monkeypatch):
    from markdown2docx.multilingual import MultilingualDocument

    source = tmp_path / "input.md"
    source.write_text("a" * 600 + " " + "b" * 600 + "\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"original")
    verify = MultilingualDocument._verify_output

    def delete_space_then_verify(self, candidate):
        def delete_space(root):
            node = root.xpath("//w:body/w:p/w:r/w:t[text()=' ']", namespaces=NS)[0]
            node.text = ""

        rewrite_docx(candidate, {"word/document.xml": delete_space})
        verify(self, candidate)

    monkeypatch.setattr(
        MultilingualDocument, "_verify_output", delete_space_then_verify
    )
    with pytest.raises(ValidationError) as error:
        MarkdownToDocxConverter().convert(source, output)
    assert output.read_bytes() == b"original"
    structural = [
        message
        for message in error.value.validation_errors
        if "paragraph 0" in message and "expected" in message and "actual" in message
    ]
    assert structural
    assert all("..." in message and len(message) < 1200 for message in structural)


@pytest.mark.parametrize("corrupt_second", [False, True], ids=["intact", "corrupt"])
def test_raw_inline_degrades_only_its_paragraph(tmp_path, monkeypatch, corrupt_second):
    from markdown2docx.multilingual import MultilingualDocument

    config = MarkdownToDocxConfig()
    config.pandoc.reader_format += "+raw_html"
    source = tmp_path / "input.md"
    source.write_text("A <span>raw</span> B\n\nNormal 中文\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"original")
    if corrupt_second:
        verify = MultilingualDocument._verify_output

        def split_second_then_verify(self, candidate):
            def split_second(root):
                body = root.find(W + "body")
                paragraph = body.findall(W + "p")[1]
                split_at = next(
                    index
                    for index, child in enumerate(paragraph)
                    if child.tag == W + "r"
                    and "".join(child.xpath("./w:t/text()", namespaces=NS)) == "中文"
                )
                second = etree.Element(W + "p")
                props = paragraph.find(W + "pPr")
                if props is not None:
                    second.append(copy.deepcopy(props))
                for child in list(paragraph)[split_at:]:
                    second.append(child)
                body.insert(body.index(paragraph) + 1, second)

            rewrite_docx(candidate, {"word/document.xml": split_second})
            verify(self, candidate)

        monkeypatch.setattr(
            MultilingualDocument, "_verify_output", split_second_then_verify
        )
        with pytest.raises(ValidationError) as error:
            MarkdownToDocxConverter(config=config).convert(source, output)
        assert output.read_bytes() == b"original"
        assert any(
            "paragraph group 1" in message
            and "expected" in message
            and "actual" in message
            for message in error.value.validation_errors
        )
    else:
        report = MarkdownToDocxConverter(config=config).convert_with_report(
            source, output
        )
        assert report.checks["text_integrity"] == "partial"
        assert any(item["code"] == "RAW_CONTENT_UNVERIFIED" for item in report.warnings)


def test_conversion_rejects_swapped_marker_runs(tmp_path, monkeypatch):
    source = tmp_path / "input.md"
    source.write_text("[骨]{lang=zh-Hans} [骨]{lang=zh-Hant}\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"original")

    from markdown2docx import converter as converter_module

    write_docx = converter_module.write_docx

    def swap_marker_runs(*args, **kwargs):
        write_docx(*args, **kwargs)

        def swap(root):
            runs = root.xpath(
                "//w:r[w:rPr/w:rStyle[starts-with(@w:val, 'MD2D')]]",
                namespaces=NS,
            )
            assert len(runs) == 2
            assert [
                "".join(run.xpath("./w:t/text()", namespaces=NS)) for run in runs
            ] == ["骨", "骨"]
            markers = {
                run.find(W + "rPr/" + W + "rStyle").get(W + "val") for run in runs
            }
            assert len(markers) == 2
            parent = runs[0].getparent()
            first, second = sorted((parent.index(runs[0]), parent.index(runs[1])))
            parent.remove(runs[0])
            parent.remove(runs[1])
            parent.insert(first, runs[1])
            parent.insert(second, runs[0])

        rewrite_docx(Path(kwargs["outputfile"]), {"word/document.xml": swap})

    monkeypatch.setattr(converter_module, "write_docx", swap_marker_runs)
    with pytest.raises(ValidationError):
        MarkdownToDocxConverter().convert(source, output)
    assert output.read_bytes() == b"original"


def test_verify_output_independently_checks_actual_run_font(tmp_path, monkeypatch):
    from dataclasses import replace

    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, "<w:r><w:t>English中文</w:t></w:r>")
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    original = document._properties

    def corrupt_cjk_font(run, spec):
        if "中文" in "".join(run.xpath("./w:t/text()", namespaces=NS)):
            spec = replace(spec, font="sans", script="Latin")
        original(run, spec)

    monkeypatch.setattr(document, "_properties", corrupt_cjk_font)
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any(
        "font coverage mismatch" in message for message in error.value.validation_errors
    )


@pytest.mark.parametrize(
    ("lang", "paragraph"),
    [
        pytest.param("zh-Hant", "<w:r><w:t>中文</w:t></w:r>", id="zh-hant"),
        pytest.param("ja", "<w:r><w:t>中文</w:t></w:r>", id="japanese"),
        pytest.param(
            "en",
            "<w:r><w:t>ひらがな</w:t></w:r><w:r><w:t>中文</w:t></w:r>",
            id="shared-han-paragraph-context",
        ),
    ],
)
def test_verify_output_rejects_regional_cjk_font_corruption(
    tmp_path, monkeypatch, lang, paragraph
):
    from dataclasses import replace

    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, paragraph)
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang=lang
    )
    original = document._properties

    def corrupt_han_font(run, spec):
        if "中文" in "".join(run.xpath("./w:t/text()", namespaces=NS)):
            spec = replace(spec, font="cjk-sc", script="Han")
        original(run, spec)

    monkeypatch.setattr(document, "_properties", corrupt_han_font)
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any(
        "font coverage mismatch" in message for message in error.value.validation_errors
    )


def test_custom_heading_font_is_verified_independently(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    resolver = FontResolver()
    resolver.aliases["heading"] = "mono"
    assert resolver.resolve("heading").family != resolver.resolve("sans").family
    document = MultilingualDocument({"meta": {}, "blocks": []}, resolver, lang="en")
    document._role = "heading"
    document._mark("Heading", "en", "Heading", "ltr")
    marker = next(iter(document.runs))
    document._role = "body"
    path = generated_docx(
        tmp_path,
        f'<w:r><w:rPr><w:rStyle w:val="{marker}"/></w:rPr>'
        "<w:t>Heading</w:t></w:r><w:r><w:t>Body</w:t></w:r>",
    )
    document.apply(path)
    runs = parts(path)["word/document.xml"].xpath("//w:r[w:t]", namespaces=NS)
    families = [run.find(W + "rPr/" + W + "rFonts").get(W + "ascii") for run in runs]
    assert families == [resolver.resolve("heading").family, "Noto Sans"]


@pytest.mark.parametrize(
    ("text", "wrong_font"),
    [("123", "arabic"), ("→", "sans"), ("。", "sans")],
)
def test_verify_output_rejects_neutral_text_font_corruption(
    tmp_path, monkeypatch, text, wrong_font
):
    from dataclasses import replace

    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, f"<w:r><w:t>{text}</w:t></w:r>")
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    original = document._properties

    def corrupt_font(run, spec):
        if "".join(run.xpath("./w:t/text()", namespaces=NS)) == text:
            spec = replace(spec, font=wrong_font)
        original(run, spec)

    monkeypatch.setattr(document, "_properties", corrupt_font)
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any(
        "font coverage mismatch" in message for message in error.value.validation_errors
    )


def test_mark_uses_regional_cjk_font_for_shared_han(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    document._mark("中文", "en", "ひらがな中文", "ltr")
    marker = next(iter(document.runs))
    path = generated_docx(
        tmp_path,
        f'<w:r><w:rPr><w:rStyle w:val="{marker}"/></w:rPr><w:t>中文</w:t></w:r>',
    )
    document.apply(path)
    run = parts(path)["word/document.xml"].xpath("//w:r[w:t]", namespaces=NS)[0]
    assert run.find(W + "rPr/" + W + "rFonts").get(W + "eastAsia") == (
        "Noto Sans CJK JP"
    )


def test_split_run_uses_paragraph_context_for_shared_han(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(
        tmp_path,
        "<w:r><w:t>ひらがな</w:t></w:r><w:r><w:t>中文</w:t></w:r>",
    )
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    document.apply(path)
    run = next(
        run
        for run in parts(path)["word/document.xml"].iter(W + "r")
        if "中文" in "".join(run.xpath("./w:t/text()", namespaces=NS))
    )
    assert run.find(W + "rPr/" + W + "rFonts").get(W + "eastAsia") == (
        "Noto Sans CJK JP"
    )


def test_verify_output_rejects_text_nested_in_run_properties(tmp_path, monkeypatch):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, "<w:r><w:t>English</w:t></w:r>")
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    verify = document._verify_output

    def nest_text_then_verify(candidate):
        with zipfile.ZipFile(candidate) as archive:
            xml = archive.read("word/document.xml")
        root = etree.fromstring(xml)
        run = root.xpath("//w:r[w:t]", namespaces=NS)[0]
        etree.SubElement(run.find(W + "rPr"), W + "t").text = "nested"
        with zipfile.ZipFile(candidate, "w") as archive:
            archive.writestr("word/document.xml", etree.tostring(root))
        verify(candidate)

    monkeypatch.setattr(document, "_verify_output", nest_text_then_verify)
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any("shape" in message.lower() for message in error.value.validation_errors)


def test_legal_drawing_textbox_run_is_accepted(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(
        tmp_path,
        "<w:r><w:drawing><w:txbxContent><w:p><w:r>"
        "<w:t>Textbox English</w:t></w:r></w:p></w:txbxContent>"
        "</w:drawing></w:r>",
    )
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    assert document.apply(path)["text_integrity"] == "passed"
    root = parts(path)["word/document.xml"]
    assert root.xpath(
        "//w:drawing/w:txbxContent/w:p/w:r/w:t/text()", namespaces=NS
    ) == ["Textbox English"]


@pytest.mark.parametrize("corrupt_outer", [False, True], ids=["intact", "corrupt"])
def test_marked_paragraph_scopes_textbox_events(tmp_path, monkeypatch, corrupt_outer):
    from markdown2docx.multilingual import MultilingualDocument

    document = MultilingualDocument(
        {"meta": {}, "blocks": [{"t": "Para", "c": [{"t": "Str", "c": "Outer"}]}]},
        FontResolver(),
        lang="en",
    )
    document.annotate()
    marker = next(iter(document.runs))
    path = generated_docx(
        tmp_path,
        f'<w:r><w:rPr><w:rStyle w:val="{marker}"/></w:rPr><w:t>Outer</w:t></w:r>'
        "<w:r><w:drawing><w:txbxContent><w:p><w:r>"
        "<w:t>Textbox English</w:t></w:r></w:p></w:txbxContent>"
        "</w:drawing></w:r>",
    )
    original = path.read_bytes()
    if corrupt_outer:
        verify = document._verify_output

        def remove_outer_then_verify(candidate):
            def remove_outer(root):
                paragraph = root.find(W + "body/" + W + "p")
                paragraph.remove(paragraph.find(W + "r"))

            rewrite_docx(candidate, {"word/document.xml": remove_outer})
            verify(candidate)

        monkeypatch.setattr(document, "_verify_output", remove_outer_then_verify)
        with pytest.raises(ValidationError):
            document.apply(path)
        assert path.read_bytes() == original
    else:
        assert document.apply(path)["text_integrity"] == "passed"
        root = parts(path)["word/document.xml"]
        assert root.xpath("//w:body/w:p/w:r/w:t/text()", namespaces=NS) == ["Outer"]
        assert root.xpath(
            "//w:drawing/w:txbxContent/w:p/w:r/w:t/text()", namespaces=NS
        ) == ["Textbox English"]


@pytest.mark.parametrize(
    "paragraph",
    [
        pytest.param("<w:r><w:t/><w:t>English中文</w:t><w:t/></w:r>", id="mixed"),
        pytest.param("<w:r><w:t/></w:r>", id="empty-only"),
    ],
)
def test_empty_text_nodes_are_ignored_safely(tmp_path, paragraph):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, paragraph)
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    assert document.apply(path)["text_integrity"] == "passed"
    text_runs = [
        run
        for run in parts(path)["word/document.xml"].iter(W + "r")
        if any((node.text or "") for node in run.findall(W + "t"))
    ]
    assert ["".join(run.xpath("./w:t/text()", namespaces=NS)) for run in text_runs] == (
        ["English", "中文"] if "English" in paragraph else []
    )


def test_verify_output_rejects_missing_xml_space(tmp_path, monkeypatch):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, "<w:r><w:t> English</w:t></w:r>")
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    verify = document._verify_output
    xml_space = "{http://www.w3.org/XML/1998/namespace}space"

    def remove_space_then_verify(candidate):
        with zipfile.ZipFile(candidate) as archive:
            xml = archive.read("word/document.xml")
        root = etree.fromstring(xml)
        for node in root.xpath("//w:r[w:t]/w:t", namespaces=NS):
            node.attrib.pop(xml_space, None)
        with zipfile.ZipFile(candidate, "w") as archive:
            archive.writestr("word/document.xml", etree.tostring(root))
        verify(candidate)

    monkeypatch.setattr(document, "_verify_output", remove_space_then_verify)
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any("xml:space" in message for message in error.value.validation_errors)


@pytest.mark.parametrize(
    ("paragraph", "text"),
    [
        (
            "<w:r><w:rPr><w:rStyle"
            ' w:val="MD2Dunsafe"/></w:rPr><w:t>English中文</w:t></w:r>',
            "English中文",
        ),
        (
            "<w:r><w:rPr><w:rStyle"
            ' w:val="MD2Dunsafe"/></w:rPr><w:rPr><w:b/></w:rPr>'
            "<w:t>English</w:t></w:r>",
            "English",
        ),
        (
            "<w:r><w:rPr><w:rStyle"
            ' w:val="MD2Dunsafe"/></w:rPr><w:t>English</w:t><w:br/></w:r>',
            "English",
        ),
        (
            "<w:r><w:rPr><w:rStyle"
            ' w:val="MD2Dunsafe"/></w:rPr><w:t>English</w:t></w:r>raw',
            "English",
        ),
    ],
)
def test_marker_runs_reject_unsafe_writer_output(tmp_path, paragraph, text):
    from markdown2docx.multilingual import MultilingualDocument, RunContext

    path = generated_docx(tmp_path, paragraph)
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    document.runs["MD2Dunsafe"] = RunContext(
        text=text,
        font="sans",
        lang="en",
        rtl=False,
        paragraph_direction="ltr",
        script="Latin",
    )
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert error.value.output_file == str(path)
    assert any(
        "marker run" in message.lower() for message in error.value.validation_errors
    )


@pytest.mark.parametrize(
    "nested",
    [
        pytest.param("<w:t>nested</w:t>", id="text"),
        pytest.param("<w:r><w:t>nested</w:t></w:r>", id="run"),
    ],
)
def test_unmarked_run_rejects_text_nested_in_properties(tmp_path, nested):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(
        tmp_path, f"<w:r><w:rPr>{nested}</w:rPr><w:t>English</w:t></w:r>"
    )
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any(
        "cannot safely split run" in message.lower()
        for message in error.value.validation_errors
    )


@pytest.mark.parametrize(
    "nested",
    [
        pytest.param("<w:t>nested</w:t>", id="text"),
        pytest.param("<w:r><w:t>nested</w:t></w:r>", id="run"),
    ],
)
def test_marker_run_rejects_text_nested_in_properties(tmp_path, nested):
    from markdown2docx.multilingual import MultilingualDocument, RunContext

    path = generated_docx(
        tmp_path,
        "<w:r><w:rPr><w:rStyle"
        f' w:val="MD2Dunsafe"/>{nested}</w:rPr><w:t>English</w:t></w:r>',
    )
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    document.runs["MD2Dunsafe"] = RunContext(
        text="English",
        font="sans",
        lang="en",
        rtl=False,
        paragraph_direction="ltr",
        script="Latin",
    )
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any(
        "marker run" in message.lower() for message in error.value.validation_errors
    )


def test_split_run_rejects_unmanaged_run_tail(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, "<w:r><w:t>English中文</w:t></w:r>raw")
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    with pytest.raises(ValidationError) as error:
        document.apply(path)
    assert any(
        "cannot safely split run" in message.lower()
        for message in error.value.validation_errors
    )


def test_split_run_preserves_safe_whitespace_run_tail(tmp_path):
    from markdown2docx.multilingual import MultilingualDocument

    path = generated_docx(tmp_path, "<w:r><w:t>English中文</w:t></w:r> ")
    document = MultilingualDocument(
        {"meta": {}, "blocks": []}, FontResolver(), lang="en"
    )
    document.apply(path)
    paragraph = parts(path)["word/document.xml"].find(".//" + W + "p")
    assert paragraph[-1].tail == " "


def test_multilingual_hyperlink_keeps_character_style(tmp_path):
    source = tmp_path / "link.md"
    source.write_text(
        "[**English 中文 العربية**](https://example.com) outside", encoding="utf-8"
    )
    root = parts(MarkdownToDocxConverter().convert(source))["word/document.xml"]
    linked = root.xpath("//w:hyperlink//w:r[w:t]", namespaces=NS)
    assert len(linked) >= 3
    assert all(
        run.find(W + "rPr/" + W + "rStyle").get(W + "val") == "Hyperlink"
        for run in linked
    )
    assert all(run.find(W + "rPr/" + W + "b") is not None for run in linked)
    assert not root.xpath("//w:rStyle[starts-with(@w:val, 'MD2D')]", namespaces=NS)
    assert not root.xpath("//w:p/w:r/w:rPr/w:rStyle", namespaces=NS)


def test_text_symbols_and_plain_digits_are_not_emoji(tmp_path):
    source = tmp_path / "symbols.md"
    source.write_text("▪ © 123", encoding="utf-8")
    report = MarkdownToDocxConverter().convert_with_report(source)
    assert report.checks["font_coverage"] == "passed"
    assert not any(item["code"] == "EMOJI_UNVERIFIED" for item in report.warnings)


def test_character_style_survives_nested_font_markers(tmp_path):
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE

    from markdown2docx.templates import DocxTemplateManager

    reference = DocxTemplateManager.create_reference(
        tmp_path / "reference.docx", MarkdownToDocxConfig().template
    )
    template = Document(reference)
    emphasis = template.styles.add_style("Emphasis", WD_STYLE_TYPE.CHARACTER)
    emphasis.font.italic = True
    brand = template.styles.add_style("Brand Accent", WD_STYLE_TYPE.CHARACTER)
    brand.font.bold = True
    template.save(reference)
    source = tmp_path / "styles.md"
    source.write_text(
        '[outer [inside]{custom-style="Emphasis"} 中文]{custom-style="Brand Accent"} '
        '[[linked](https://example.com)]{custom-style="Emphasis"} outside\n',
        encoding="utf-8",
    )
    result = MarkdownToDocxConverter(reference_doc=reference).convert(source)
    roots = parts(result)
    document = roots["word/document.xml"]
    styles = roots["word/styles.xml"]
    style_ids = {
        style.find(W + "name").get(W + "val"): style.get(W + "styleId")
        for style in styles.findall(W + "style")
    }
    for text, name in [
        ("outer", "Brand Accent"),
        ("中文", "Brand Accent"),
        ("inside", "Emphasis"),
        ("linked", "Emphasis"),
    ]:
        run = next(
            run
            for run in document.iter(W + "r")
            if text in "".join(run.xpath("./w:t/text()", namespaces=NS))
        )
        assert run.find(W + "rPr/" + W + "rStyle").get(W + "val") == style_ids[name]
    outside = next(
        run
        for run in document.iter(W + "r")
        if "outside" in "".join(run.xpath("./w:t/text()", namespaces=NS))
    )
    assert outside.find(W + "rPr/" + W + "rStyle") is None
    assert styles.xpath("//w:style[@w:styleId='Emphasis']/w:rPr/w:i", namespaces=NS)
    assert styles.xpath(
        "//w:style[w:name[@w:val='Brand Accent']]/w:rPr/w:b", namespaces=NS
    )


@pytest.mark.parametrize("identifier", ["example", "_example", "foo-bar"])
def test_code_block_keeps_link_target_and_local_language(tmp_path, identifier):
    source = tmp_path / "anchor.md"
    source.write_text(
        f"[Go](#{identifier})\n\n::: {{lang=ja}}\n\n```{{#{identifier} .text}}\n漢字\n```\n\n:::\n",
        encoding="utf-8",
    )
    config = MarkdownToDocxConfig()
    config.pandoc.reader_format = "markdown"
    root = parts(MarkdownToDocxConverter(config=config).convert(source))[
        "word/document.xml"
    ]
    target = root.xpath("//w:hyperlink/@w:anchor", namespaces=NS)
    bookmarks = root.xpath("//w:bookmarkStart/@w:name", namespaces=NS)
    assert target and target[0] in bookmarks
    code_run = next(
        run
        for run in root.iter(W + "r")
        if "漢字" in "".join(run.xpath("./w:t/text()", namespaces=NS))
    )
    assert code_run.find(W + "rPr/" + W + "lang").get(W + "val") == "ja"
    assert (
        code_run.find(W + "rPr/" + W + "rFonts").get(W + "eastAsia")
        == "Noto Sans CJK JP"
    )


def test_no_toc_needs_no_localized_title_font_offline(tmp_path, monkeypatch):
    import shutil

    from markdown2docx.fonts import FontError

    cache = tmp_path / "fonts"
    cache.mkdir()
    prepared = FontResolver(directories=[])
    for key in ["sans", "symbols"]:
        font = prepared.resolve(key)
        entry = prepared.manifest["fonts"][key]
        shutil.copyfile(font.path, cache / entry["filename"])
        shutil.copyfile(
            prepared.cache / entry["license_filename"],
            cache / entry["license_filename"],
        )
    resolver = FontResolver(cache=cache, offline=True, directories=[])
    monkeypatch.setattr(
        "markdown2docx.converter.FontResolver", lambda **kwargs: resolver
    )
    source = tmp_path / "english.md"
    source.write_text("English only", encoding="utf-8")
    converter = MarkdownToDocxConverter()
    report = converter.convert_with_report(
        source, lang="zh-Hans", toc=False, offline=True
    )
    assert report.checks["font_coverage"] == "passed"
    assert not any(font["key"].startswith("cjk") for font in report.fonts)
    with pytest.raises(FontError) as error:
        converter.convert(source, lang="zh-Hans", toc=True, offline=True)
    assert error.value.code == "FONT_UNAVAILABLE"
