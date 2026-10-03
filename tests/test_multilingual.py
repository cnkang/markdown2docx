"""Round-trip acceptance for CJK + UN languages in the same document."""

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
    import pypandoc

    original = pypandoc.convert_file

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

    monkeypatch.setattr("markdown2docx.converter.pypandoc.convert_file", lose_text)
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
