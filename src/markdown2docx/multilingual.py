"""Preserve Pandoc structure while assigning fonts/languages to text fragments.

Temporary character styles carry AST context through Pandoc's DOCX writer.
They are removed after their properties have been written directly to runs.
"""

from __future__ import annotations

import copy
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import langcodes
import regex  # type: ignore[import-untyped]
from lxml import etree

from .exceptions import ConfigurationError, ValidationError
from .fonts import FontResolver

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
NS = {"w": W[1:-1], "m": M[1:-1]}
TOC_TITLES = {
    "en": "Contents",
    "zh-Hans": "目录",
    "zh-Hant": "目錄",
    "ja": "目次",
    "ko": "목차",
    "fr": "Table des matières",
    "es": "Índice",
    "ru": "Содержание",
    "ar": "المحتويات",
}


def language(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not langcodes.tag_is_valid(value):
        raise ConfigurationError("lang", f"Invalid BCP 47 language: {value}")
    return langcodes.standardize_tag(value)


def direction(text: str) -> str:
    for char in text:
        bidi = unicodedata.bidirectional(char)
        if bidi in {"R", "AL"}:
            return "rtl"
        if bidi == "L":
            return "ltr"
    return "ltr"


def script(cluster: str) -> str:
    for name in (
        "Arabic",
        "Han",
        "Hiragana",
        "Katakana",
        "Hangul",
        "Cyrillic",
        "Latin",
    ):
        if regex.search(rf"\p{{Script={name}}}", cluster):
            return name
    return "Common"


def cjk_key(lang: str | None, text: str) -> tuple[str, bool]:
    if lang:
        tag = langcodes.Language.get(lang)
        if tag.language == "ja":
            return "cjk-jp", False
        if tag.language == "ko":
            return "cjk-kr", False
        if tag.language == "zh":
            return ("cjk-tc" if tag.maximize().script == "Hant" else "cjk-sc"), False
    if regex.search(r"[\p{Hiragana}\p{Katakana}]", text):
        return "cjk-jp", False
    if regex.search(r"\p{Hangul}", text):
        return "cjk-kr", False
    return "cjk-sc", True


def fragments(
    text: str, lang: str | None, context: str, *, code: bool = False
) -> list[tuple[str, str, bool, str]]:
    """Split at grapheme boundaries; attach neutral punctuation to adjacent text."""
    clusters = regex.findall(r"\X", text)
    scripts = [script(c) for c in clusters]
    for index, name in enumerate(scripts):
        if name == "Common":
            before = next((s for s in reversed(scripts[:index]) if s != "Common"), None)
            after = next((s for s in scripts[index + 1 :] if s != "Common"), None)
            scripts[index] = (
                before
                or after
                or ("Arabic" if lang and lang.startswith("ar") else "Latin")
            )
    result: list[tuple[str, str, bool, str]] = []
    cjk, _ = cjk_key(lang, context)
    for cluster, name in zip(clusters, scripts):
        if name == "Arabic" and not all(ord(c) < 128 for c in cluster):
            key = "arabic"
        elif name in {"Han", "Hiragana", "Katakana", "Hangul"}:
            key = (
                "cjk-kr"
                if name == "Hangul"
                else ("cjk-jp" if name in {"Hiragana", "Katakana"} else cjk)
            )
        else:
            key = "mono" if code else "sans"
        if 0x3000 <= ord(cluster[0]) <= 0x303F or 0xFF01 <= ord(cluster[0]) <= 0xFF60:
            key = cjk
        if (
            unicodedata.category(cluster[0]) in {"Sm", "So"}
            and ord(cluster[0]) >= 0x2000
            and not regex.search(r"\p{Extended_Pictographic}", cluster)
        ):
            key = (
                "math"
                if unicodedata.category(cluster[0]) == "Sm"
                or 0x2190 <= ord(cluster[0]) <= 0x21FF
                else "symbols"
            )
        # Numbers and Latin sequences inside Arabic must remain LTR.
        rtl = name == "Arabic" and direction(cluster) == "rtl"
        if result and result[-1][0] == key and result[-1][2:] == (rtl, name):
            previous = result[-1]
            result[-1] = (key, previous[1] + cluster, rtl, name)
        else:
            result.append((key, cluster, rtl, name))
    return result


def text_of(node: Any) -> str:
    """Visible prose for paragraph context, excluding notes and code."""
    if isinstance(node, list):
        return "".join(text_of(item) for item in node)
    if not isinstance(node, dict):
        return ""
    kind = node.get("t")
    content: Any = node.get("c")
    if kind in {"Code", "CodeBlock", "Note", "Math", "RawInline", "RawBlock"}:
        return ""
    if kind == "Str":
        return str(content)
    if kind in {"Space", "SoftBreak", "LineBreak"}:
        return " "
    if kind in {"Span", "Link", "Image"}:
        return text_of(content[1])
    if kind == "Header":
        return text_of(content[2])
    return text_of(content)


@dataclass
class RunContext:
    text: str
    font: str
    lang: str | None
    rtl: bool
    paragraph_direction: str
    script: str
    code: bool = False


class MultilingualDocument:
    def __init__(
        self,
        ast: dict[str, Any],
        resolver: FontResolver,
        *,
        lang: str | None,
        base_direction: str = "auto",
    ) -> None:
        if base_direction not in {"auto", "ltr", "rtl"}:
            raise ConfigurationError("direction", "Direction must be auto, ltr or rtl")
        self.ast = copy.deepcopy(ast)
        self.resolver = resolver
        self.lang = language(lang)
        self.base_direction = base_direction
        self.runs: dict[str, RunContext] = {}
        self.warnings: list[dict[str, str]] = []
        self.scripts: set[str] = set()
        self.languages: set[str] = {self.lang} if self.lang else set()
        self.code_blocks: list[str] = []
        self.code_languages: dict[str, str | None] = {}
        self.math = False
        self.code_size_pt = 9
        self._role = "body"
        self._warned: set[str] = set()

    def warn(self, code: str, message: str) -> None:
        if code not in self._warned:
            self.warnings.append({"code": code, "message": message})
            self._warned.add(code)

    def annotate(self) -> dict[str, Any]:
        self.ast["blocks"] = self._walk(
            self.ast["blocks"], self.lang, self.base_direction, "", "ltr"
        )
        # Titles, subtitles and authors can contain multilingual inline content too.
        for key in ("title", "subtitle", "author"):
            if key in self.ast["meta"]:
                self.ast["meta"][key] = self._walk(
                    self.ast["meta"][key], self.lang, self.base_direction, "", "ltr"
                )
        if self.lang:
            self.ast["meta"]["lang"] = {"t": "MetaString", "c": self.lang}
        else:
            self.ast["meta"].pop("lang", None)
        if self.base_direction in {"rtl", "ltr"}:
            self.ast["meta"]["dir"] = {"t": "MetaString", "c": self.base_direction}
        else:
            self.ast["meta"].pop("dir", None)
        title_key = self.lang or "en"
        if title_key.startswith("zh"):
            title_key = (
                "zh-Hant"
                if langcodes.Language.get(title_key).maximize().script == "Hant"
                else "zh-Hans"
            )
        else:
            title_key = title_key.split("-")[0]
        if title_key not in TOC_TITLES:
            self.warn(
                "LABEL_LANGUAGE_FALLBACK",
                "Generated labels use English for this language",
            )
        title = TOC_TITLES.get(title_key, TOC_TITLES["en"])
        self.ast["meta"].setdefault("toc-title", {"t": "MetaString", "c": title})
        self.resolver.resolve(
            "sans",
            title if title_key not in {"ar", "zh-Hans", "zh-Hant", "ja", "ko"} else "",
        )
        if title_key in {"ar", "zh-Hans", "zh-Hant", "ja", "ko"}:
            key = "arabic" if title_key == "ar" else cjk_key(title_key, title)[0]
            self.resolver.resolve(key, title)
        return self.ast

    def _mark(
        self,
        text: str,
        lang: str | None,
        context: str,
        pdir: str,
        *,
        code: bool = False,
        local_dir: str | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        for key, part, rtl, name in fragments(text, lang, context, code=code):
            if key == "sans" and self._role == "heading":
                key = "heading"
            if regex.search(r"\p{Extended_Pictographic}", part):
                self.warn(
                    "EMOJI_UNVERIFIED",
                    "Color emoji rendering is not supported; verify the preview",
                )
                # Warn rather than require unsupported color glyphs from text fonts.
                checked = regex.sub(r"\p{Extended_Pictographic}", "", part)
            else:
                checked = part
            self.resolver.resolve(key, checked)
            self.scripts.add(name)
            if name == "Han" and cjk_key(lang, context)[1]:
                self.warn(
                    "CJK_LANGUAGE_AMBIGUOUS",
                    "Unmarked shared Han characters use Simplified Chinese glyphs; add lang spans for regional forms",
                )
            marker = f"MD2D{len(self.runs):06d}"
            self.runs[marker] = RunContext(
                part, key, lang, rtl and local_dir != "ltr", pdir, name, code
            )
            # VerbatimChar overrides custom-style in Pandoc. Carry inline code as
            # text in our own style, then apply its size/font explicitly.
            child = {"t": "Str", "c": part}
            result.append(
                {"t": "Span", "c": [["", [], [["custom-style", marker]]], [child]]}
            )
        return result

    def _walk(
        self,
        node: Any,
        lang: str | None,
        inherited_dir: str,
        context: str,
        pdir: str,
        local_dir: str | None = None,
    ) -> Any:
        if isinstance(node, list):
            result = []
            for item in node:
                transformed = self._walk(
                    item, lang, inherited_dir, context, pdir, local_dir
                )
                result.extend(
                    transformed
                    if isinstance(transformed, list) and isinstance(item, dict)
                    else [transformed]
                )
            return result
        if not isinstance(node, dict):
            return node
        kind = node.get("t")
        content: Any = node.get("c")
        if kind in {"Span", "Div"}:
            attrs = dict(content[0][2])
            lang = language(attrs.get("lang", lang))
            if lang:
                self.languages.add(lang)
            if "dir" in attrs:
                if attrs["dir"] not in {"ltr", "rtl"}:
                    raise ConfigurationError(
                        "dir", "Local direction must be ltr or rtl"
                    )
                if kind == "Div":
                    inherited_dir = attrs["dir"]
                else:
                    local_dir = attrs["dir"]
            node["c"][1] = self._walk(
                content[1], lang, inherited_dir, context, pdir, local_dir
            )
            return node
        if kind in {"Para", "Plain", "Header", "MetaInlines"}:
            context = text_of(node)
            pdir = inherited_dir if inherited_dir != "auto" else direction(context)
            if kind == "Header":
                previous_role = self._role
                self._role = "heading"
                node["c"][2] = self._walk(
                    content[2], lang, inherited_dir, context, pdir, local_dir
                )
                self._role = previous_role
            else:
                node["c"] = self._walk(
                    content, lang, inherited_dir, context, pdir, local_dir
                )
            return node
        if kind == "Str":
            return self._mark(
                content, lang, context or content, pdir, local_dir=local_dir
            )
        if kind == "Code":
            return self._mark(
                content[1],
                lang,
                context or content[1],
                pdir,
                code=True,
                local_dir="ltr",
            )
        if kind == "CodeBlock":
            self.code_blocks.append(content[1])
            for key, part, _, name in fragments(
                content[1], lang, content[1], code=True
            ):
                self.resolver.resolve(key, part)
                self.scripts.add(name)
            # A code block's own attributes survive syntax highlighting via its ID.
            content[0][0] = f"MD2DCODE{len(self.code_blocks)-1}"
            self.code_languages[content[0][0]] = lang
            return node
        if kind == "Math":
            self.math = True
            self.resolver.resolve("math")
            return node
        if kind in {"RawBlock", "RawInline"}:
            self.warn(
                "RAW_CONTENT_UNVERIFIED",
                "Raw content is outside text-integrity validation",
            )
            return node
        if kind == "Image":
            # Alt text is not visible body text in DOCX.
            return node
        if content is not None:
            node["c"] = self._walk(
                content, lang, inherited_dir, context, pdir, local_dir
            )
        return node

    def apply(self, path: Path) -> dict[str, str]:
        """Apply run properties across body, footnotes and other document parts."""
        observed: dict[str, str] = {}
        before: list[str] = []
        after: list[str] = []
        code_text: list[str] = []
        with zipfile.ZipFile(path) as archive:
            entries = [
                (info, archive.read(info.filename)) for info in archive.infolist()
            ]
        updated = []
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        for info, data in entries:
            if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                root = etree.fromstring(data, parser)
                if self.math:
                    for value in root.xpath("//m:t/text()", namespaces=NS):
                        self.resolver.resolve("math", value)
                before.extend(root.xpath("//w:t/text()", namespaces=NS))
                for paragraph in root.iter(W + "p"):
                    style = paragraph.find(W + "pPr/" + W + "pStyle")
                    code = style is not None and style.get(W + "val") in {
                        "SourceCode",
                        "CodeBlock",
                    }
                    if code:
                        code_text.append(
                            "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
                        )
                    paragraph_text = "".join(
                        paragraph.xpath(".//w:t/text()", namespaces=NS)
                    )
                    code_lang = self.lang
                    previous = paragraph.getprevious()
                    if (
                        code
                        and previous is not None
                        and previous.tag == W + "bookmarkStart"
                    ):
                        code_lang = self.code_languages.get(
                            previous.get(W + "name", "").lstrip("_"), self.lang
                        )
                    marked_paragraph = False
                    for run in list(paragraph.iter(W + "r")):
                        run_style = run.find(W + "rPr/" + W + "rStyle")
                        marker = (
                            run_style.get(W + "val") if run_style is not None else None
                        )
                        if marker in self.runs:
                            spec = self.runs[marker]
                            observed[marker] = observed.get(marker, "") + "".join(
                                run.xpath("./w:t/text()", namespaces=NS)
                            )
                            run_style.getparent().remove(run_style)
                            self._properties(run, spec)
                            self._paragraph(paragraph, spec.paragraph_direction)
                            marked_paragraph = True
                        elif run.find(W + "t") is not None:
                            value = "".join(run.xpath("./w:t/text()", namespaces=NS))
                            # Writer-generated labels, code highlighting and unmarked text.
                            self._split_run(
                                run,
                                value,
                                code=code,
                                lang=code_lang,
                                context=paragraph_text,
                            )
                    if code:
                        self._paragraph(paragraph, "ltr")
                    elif not marked_paragraph and paragraph_text:
                        self._paragraph(
                            paragraph,
                            (
                                self.base_direction
                                if self.base_direction != "auto"
                                else direction(paragraph_text)
                            ),
                        )
                if info.filename == "word/styles.xml":
                    for element in list(root):
                        if element.tag == W + "style" and element.get(
                            W + "styleId", ""
                        ).startswith("MD2D"):
                            root.remove(element)
                    for props in root.iter(W + "rPr"):
                        for source, target in (
                            ("b", "bCs"),
                            ("i", "iCs"),
                            ("sz", "szCs"),
                        ):
                            original = props.find(W + source)
                            if original is not None and props.find(W + target) is None:
                                copied = copy.deepcopy(original)
                                copied.tag = W + target
                                props.append(copied)
                if info.filename == "word/numbering.xml":
                    # Legacy reference bullets use private-use Symbol/Wingdings
                    # glyphs. Replace both glyph and font, not just the family.
                    for level in root.iter(W + "lvl"):
                        fmt = level.find(W + "numFmt")
                        label = level.find(W + "lvlText")
                        if (
                            fmt is None
                            or label is None
                            or fmt.get(W + "val") != "bullet"
                        ):
                            continue
                        value = label.get(W + "val", "")
                        value = {"\uf0b7": "•", "\uf0a7": "▪", "o": "○"}.get(
                            value, value
                        )
                        label.set(W + "val", value)
                        key = "sans" if value in {"•", " "} else "symbols"
                        family = self.resolver.resolve(key, value).family
                        props = level.find(W + "rPr")
                        if props is None:
                            props = etree.SubElement(level, W + "rPr")
                        fonts = props.find(W + "rFonts")
                        if fonts is None:
                            fonts = etree.SubElement(props, W + "rFonts")
                        fonts.attrib.clear()
                        for slot in ("ascii", "hAnsi", "eastAsia", "cs"):
                            fonts.set(W + slot, family)
                if self.math and info.filename == "word/settings.xml":
                    math_pr = root.find(M + "mathPr")
                    if math_pr is None:
                        math_pr = etree.SubElement(root, M + "mathPr")
                    font = math_pr.find(M + "mathFont")
                    if font is None:
                        font = etree.SubElement(math_pr, M + "mathFont")
                    font.set(M + "val", self.resolver.resolve("math").family)
                after.extend(root.xpath("//w:t/text()", namespaces=NS))
                data = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True
                )
            updated.append((info, data))
        failures = [
            name for name, spec in self.runs.items() if observed.get(name) != spec.text
        ]
        # Code paragraphs use line breaks instead of newline characters in w:t.
        expected_code = "".join(self.code_blocks).replace("\n", "").replace("\r", "")
        if "".join(code_text) != expected_code:
            failures.append("code block text")
        if "".join(before) != "".join(after):
            failures.append("DOCX text changed during font assignment")
        if failures:
            raise ValidationError(
                str(path), [f"Text integrity failed: {', '.join(failures[:10])}"]
            )
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for info, data in updated:
                archive.writestr(info, data)
        return {
            "text_integrity": (
                "partial" if "RAW_CONTENT_UNVERIFIED" in self._warned else "passed"
            ),
            "font_coverage": (
                "unverified" if "EMOJI_UNVERIFIED" in self._warned else "passed"
            ),
            "language_direction": "passed",
        }

    def _split_run(
        self, run: Any, text: str, *, code: bool, lang: str | None, context: str
    ) -> None:
        # Preserve non-text run children (breaks, references) by replacing only
        # simple text-only runs. Other runs keep their structure and receive fonts.
        parts = fragments(text, lang, context, code=code)
        if not parts:
            return
        parent = run.getparent()
        text_children = run.findall(W + "t")
        if len(text_children) != 1 or any(
            child.tag not in {W + "rPr", W + "t"} for child in run
        ):
            key, _, rtl, name = parts[0]
            self._properties(
                run,
                RunContext(
                    text, key, lang, rtl, "ltr" if code else direction(text), name, code
                ),
            )
            return
        index = parent.index(run)
        for offset, (key, part, rtl, name) in enumerate(parts):
            self.resolver.resolve(key, part)
            clone = copy.deepcopy(run)
            clone.find(W + "t").text = part
            self._properties(
                clone,
                RunContext(
                    part, key, lang, rtl, "ltr" if code else direction(text), name, code
                ),
            )
            parent.insert(index + offset, clone)
        parent.remove(run)

    def _properties(self, run: Any, spec: RunContext) -> None:
        props = run.find(W + "rPr")
        if props is None:
            props = etree.Element(W + "rPr")
            run.insert(0, props)
        family = self.resolver.resolve(spec.font).family
        if spec.code:
            size = props.find(W + "sz")
            if size is None:
                size = etree.SubElement(props, W + "sz")
            size.set(W + "val", str(self.code_size_pt * 2))
        fonts = props.find(W + "rFonts")
        if fonts is None:
            fonts = etree.Element(W + "rFonts")
            props.insert(0, fonts)
        for attr in list(fonts.attrib):
            if attr.endswith("Theme"):
                del fonts.attrib[attr]
        for slot in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(W + slot, family)
        fonts.set(
            W + "hint",
            (
                "cs"
                if spec.script == "Arabic"
                else ("eastAsia" if spec.font.startswith("cjk") else "default")
            ),
        )
        for tag, enabled in (("rtl", spec.rtl), ("cs", spec.script == "Arabic")):
            element = props.find(W + tag)
            if element is None:
                element = etree.SubElement(props, W + tag)
            element.set(W + "val", "1" if enabled else "0")
        # Arabic bold/italic and size have separate complex-script counterparts.
        for source, target in (("b", "bCs"), ("i", "iCs"), ("sz", "szCs")):
            original = props.find(W + source)
            if original is not None and props.find(W + target) is None:
                copied = copy.deepcopy(original)
                copied.tag = W + target
                props.append(copied)
        if spec.lang:
            element = props.find(W + "lang")
            if element is None:
                element = etree.SubElement(props, W + "lang")
            for attr in ("val", "eastAsia", "bidi"):
                element.set(W + attr, spec.lang)

    @staticmethod
    def _paragraph(paragraph: Any, value: str) -> None:
        props = paragraph.find(W + "pPr")
        if props is None:
            props = etree.Element(W + "pPr")
            paragraph.insert(0, props)
        bidi = props.find(W + "bidi")
        if bidi is None:
            bidi = etree.SubElement(props, W + "bidi")
        bidi.set(W + "val", "1" if value == "rtl" else "0")
