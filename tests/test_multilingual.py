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


def generated_docx(tmp_path, paragraph, name="generated.docx"):
    path = tmp_path / name
    xml = (
        f'<w:document xmlns:w="{NS["w"]}"><w:body><w:p>'
        f"{paragraph}</w:p></w:body></w:document>"
    )
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
    "corruption",
    [
        "delete-space",
        "delete-soft-break",
        "delete-line-break",
        "delete-code-break",
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
    if corruption == "cross-part-move":
        source.write_text("Body[^note]\n\n[^note]: Footnote\n", encoding="utf-8")
    elif corruption == "delete-code-break":
        source.write_text("```text\none\ntwo\n```\n", encoding="utf-8")
    else:
        source.write_text("alpha beta\\\ngamma\nsoft\n\nsecond\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"original")
    verify = MultilingualDocument._verify_output

    def corrupt_document(root):
        body = root.find(W + "body")
        paragraphs = body.findall(W + "p")
        first = paragraphs[0]
        if corruption in {"delete-space", "delete-soft-break"}:
            spaces = first.xpath("./w:r/w:t[text()=' ']", namespaces=NS)
            spaces[0 if corruption == "delete-space" else 1].text = ""
        elif corruption == "delete-line-break":
            line_break = first.find(".//" + W + "br")
            line_break.getparent().remove(line_break)
        elif corruption == "delete-code-break":
            line_break = first.find(".//" + W + "br")
            line_break.getparent().remove(line_break)
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
        MarkdownToDocxConverter().convert(source, output)
    assert output.read_bytes() == b"original"


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
