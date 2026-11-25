"""Preserve Pandoc structure while assigning fonts/languages to text fragments.

Temporary character styles carry AST context through Pandoc's DOCX writer.
They are removed after their properties have been written directly to runs.
"""

from __future__ import annotations

import copy
import hashlib
import os
import shutil
import tempfile
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import langcodes
import regex  # type: ignore[import-untyped]
from lxml import etree

from .config import LimitsConfig
from .exceptions import ConfigurationError, ValidationError
from .fonts import FontResolver

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NS = {"w": W[1:-1], "m": M[1:-1]}
LTR_ISOLATE = "\u2066"
RTL_ISOLATE = "\u2067"
POP_DIRECTIONAL_ISOLATE = "\u2069"
BIDI_CONTROL_PATTERN = regex.compile(r"\p{Bidi_Control}")
DIRECTIONAL_CONTROL_PATTERN = regex.compile(r"[\u202a-\u202e\u2066-\u2069]")

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


# Detect emoji components without classifying ordinary digits as emoji. Strip
# whole graphemes to include keycap bases, variation selectors and ZWJ sequences.
EMOJI_PATTERN = regex.compile(
    r"\p{Emoji_Presentation}|\p{Extended_Pictographic}\uFE0F|"
    r"\p{Regional_Indicator}|\p{Emoji_Modifier}|\u20e3"
)


def strip_emoji(text: str) -> str:
    return "".join(
        cluster
        for cluster in regex.findall(r"\X", text)
        if not EMOJI_PATTERN.search(cluster)
    )


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
    text: str,
    lang: str | None,
    context: str,
    *,
    code: bool = False,
    cjk: str | None = None,
) -> list[tuple[str, str, bool, str]]:
    """Split at grapheme boundaries; attach neutral punctuation to adjacent text."""
    clusters = regex.findall(r"\X", text)
    controls = [
        BIDI_CONTROL_PATTERN.fullmatch(cluster) is not None for cluster in clusters
    ]
    scripts = [
        "Common" if control else script(cluster)
        for cluster, control in zip(clusters, controls, strict=True)
    ]
    following: list[str | None] = [None] * len(scripts)
    next_script = None
    for index in range(len(scripts) - 1, -1, -1):
        following[index] = next_script
        if scripts[index] != "Common":
            next_script = scripts[index]
    previous_script = None
    for index, name in enumerate(scripts):
        if controls[index]:
            previous_script = None
            continue
        if name == "Common":
            scripts[index] = (
                previous_script
                or following[index]
                or ("Arabic" if lang and lang.startswith("ar") else "Latin")
            )
        previous_script = scripts[index]
    result: list[tuple[str, str, bool, str]] = []
    buffered: list[str] = []
    current: tuple[str, bool, str] | None = None
    if cjk is None:
        cjk, _ = cjk_key(lang, context)
    for cluster, name, control in zip(clusters, scripts, controls, strict=True):
        if control:
            if current is not None:
                result.append((current[0], "".join(buffered), current[1], current[2]))
                buffered = []
                current = None
            result.append(("mono" if code else "sans", cluster, False, "Common"))
            continue
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
            and not EMOJI_PATTERN.search(cluster)
        ):
            key = (
                "math"
                if unicodedata.category(cluster[0]) == "Sm"
                or 0x2190 <= ord(cluster[0]) <= 0x21FF
                else "symbols"
            )
        # Numbers and Latin sequences inside Arabic must remain LTR.
        rtl = name == "Arabic" and direction(cluster) == "rtl"
        identity = (key, rtl, name)
        if identity != current:
            if current is not None:
                result.append((current[0], "".join(buffered), current[1], current[2]))
            buffered = []
            current = identity
        buffered.append(cluster)
    if current is not None:
        result.append((current[0], "".join(buffered), current[1], current[2]))
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


def _contains_direction_control(node: Any) -> bool:
    if isinstance(node, list):
        return any(_contains_direction_control(item) for item in node)
    if not isinstance(node, dict):
        return False
    kind = node.get("t")
    if kind == "Note":
        return False
    if kind == "Str":
        return DIRECTIONAL_CONTROL_PATTERN.search(str(node.get("c", ""))) is not None
    if kind == "Code":
        return DIRECTIONAL_CONTROL_PATTERN.search(str(node["c"][1])) is not None
    return _contains_direction_control(node.get("c"))


def _append_text(events: list[str | None], text: str) -> None:
    if text:
        events.append(text)


def _text_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def _events_repr(events: Any, limit: int = 500) -> str:
    value = repr(events)
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _coalesce_events(events: list[str | None]) -> list[str | None]:
    result: list[str | None] = []
    text: list[str] = []
    for event in events:
        if event is None:
            if text:
                result.append("".join(text))
                text = []
            result.append(None)
        else:
            text.append(event)
    if text:
        result.append("".join(text))
    return result


@dataclass
class TextStructure:
    """Visible paragraph events, where None denotes a hard line break."""

    story: str
    events: list[str | None] = field(default_factory=list)
    code: bool = False
    anchor: str | None = None
    bookmark_id: str | None = None
    raw: bool = False

    def add_text(self, text: str) -> None:
        _append_text(self.events, text)

    def add_space(self) -> None:
        self.add_text(" ")

    def add_break(self) -> None:
        self.events.append(None)


def _story_for_part(name: str) -> str:
    if name == "word/document.xml":
        return "document"
    if name.startswith("word/footnotes"):
        return "footnotes"
    if name.startswith("word/endnotes"):
        return "endnotes"
    if name.startswith("word/comments"):
        return "comments"
    return name


def _nearest_paragraph(run: Any) -> Any:
    return next(
        (parent for parent in run.iterancestors() if parent.tag == W + "p"), None
    )


def _paragraph_bookmark(paragraph: Any) -> tuple[str, str] | None:
    previous = paragraph.getprevious()
    following = paragraph.getnext()
    bookmark_id = previous.get(W + "id") if previous is not None else None
    if (
        previous is None
        or previous.tag != W + "bookmarkStart"
        or following is None
        or following.tag != W + "bookmarkEnd"
        or not bookmark_id
        or bookmark_id != following.get(W + "id")
    ):
        return None
    return previous.get(W + "name", "").removeprefix("_"), bookmark_id


def _generated_section_number(paragraph: Any, marker_prefix: str) -> str | None:
    for element in paragraph.iter():
        if _nearest_paragraph(element) is not paragraph or element.tag != W + "t":
            continue
        value = element.text or ""
        if not value:
            continue
        run = next(
            (parent for parent in element.iterancestors() if parent.tag == W + "r"),
            None,
        )
        style = run.find(W + "rPr/" + W + "rStyle") if run is not None else None
        if style is None:
            return None
        name = style.get(W + "val", "")
        if name.startswith(marker_prefix):
            return None
        if name == "SectionNumber" and regex.fullmatch(r"\d+(?:\.\d+)*", value):
            return value
        return None
    return None


def _paragraph_events(
    paragraph: Any, *, generated_section_number: str | None = None
) -> list[str | None]:
    events: list[str | None] = []
    first_text = True
    for element in paragraph.iter():
        if _nearest_paragraph(element) is not paragraph:
            continue
        if element.tag == W + "t":
            value = element.text or ""
            run = next(
                (parent for parent in element.iterancestors() if parent.tag == W + "r"),
                None,
            )
            style = run.find(W + "rPr/" + W + "rStyle") if run is not None else None
            if (
                first_text
                and generated_section_number is not None
                and value == generated_section_number
                and style is not None
                and style.get(W + "val") == "SectionNumber"
            ):
                continue
            if value:
                first_text = False
            _append_text(events, value)
        elif element.tag in {W + "br", W + "cr"} and element.get(W + "type") in {
            None,
            "textWrapping",
        }:
            events.append(None)
    return _coalesce_events(events)


def _code_candidates(
    root: Any,
    code_bookmarks: dict[str, str],
    marker_prefix: str | None = None,
) -> list[tuple[str, str, Any]]:
    candidates = []
    for paragraph in root.iter(W + "p"):
        bookmark = _paragraph_bookmark(paragraph)
        if bookmark is None:
            continue
        if marker_prefix is not None and any(
            run_style.get(W + "val", "").startswith(marker_prefix)
            for run in paragraph.iter(W + "r")
            if _nearest_paragraph(run) is paragraph
            for run_style in run.findall(W + "rPr/" + W + "rStyle")
        ):
            continue
        name, bookmark_id = bookmark
        anchor = code_bookmarks.get(name)
        style = paragraph.find(W + "pPr/" + W + "pStyle")
        if (
            anchor is not None
            and style is not None
            and style.get(W + "val") in {"SourceCode", "CodeBlock"}
        ):
            candidates.append((anchor, bookmark_id, paragraph))
    return candidates


def _match_code_structures(
    expected: list[TextStructure], candidates: list[tuple[str, str, Any]]
) -> list[tuple[TextStructure, Any | None, str | None]]:
    by_anchor: dict[str, list[tuple[str, str, Any]]] = {}
    for candidate in candidates:
        by_anchor.setdefault(candidate[0], []).append(candidate)
    offsets: dict[str, int] = {}
    matches = []
    for structure in expected:
        choices = by_anchor.get(structure.anchor or "", [])
        if structure.bookmark_id is not None:
            choices = [
                choice for choice in choices if choice[1] == structure.bookmark_id
            ]
        offset = offsets.get(structure.anchor or "", 0)
        selected = next(
            (
                index
                for index in range(offset, len(choices))
                if _paragraph_events(choices[index][2]) == structure.events
            ),
            offset,
        )
        if selected < len(choices):
            _, bookmark_id, paragraph = choices[selected]
            offsets[structure.anchor or ""] = selected + 1
            matches.append((structure, paragraph, bookmark_id))
        else:
            matches.append((structure, None, None))
    return matches


@dataclass
class RunContext:
    text: str
    font: str
    lang: str | None
    rtl: bool
    paragraph_direction: str
    script: str
    code: bool = False
    character_style: str | None = None
    role: str = "body"
    cjk: str = "cjk-sc"
    structure: TextStructure | None = None


class MultilingualDocument:
    def __init__(
        self,
        ast: dict[str, Any],
        resolver: FontResolver,
        *,
        lang: str | None,
        base_direction: str = "auto",
        number_sections: bool = False,
    ) -> None:
        if base_direction not in {"auto", "ltr", "rtl"}:
            raise ConfigurationError("direction", "Direction must be auto, ltr or rtl")
        self.ast = copy.deepcopy(ast)
        self.resolver = resolver
        self.lang = language(lang)
        self.base_direction = base_direction
        self.number_sections = number_sections
        self.runs: dict[str, RunContext] = {}
        self._marker_prefix = "MD2D" + uuid.uuid4().hex[:12]
        self.warnings: list[dict[str, str]] = []
        self.scripts: set[str] = set()
        self.languages: set[str] = {self.lang} if self.lang else set()
        self.code_blocks: list[str] = []
        self.code_languages: dict[str, str | None] = {}
        self.math = False
        self.limits = LimitsConfig()
        self.code_size_pt = 9
        self._role = "body"
        self._character_style: str | None = None
        self._warned: set[str] = set()
        self._styled_runs: dict[Any, RunContext] = {}
        self._paragraph_directions: dict[Any, str] = {}
        self._structures: list[TextStructure] = []
        self._expected_parts: dict[str, Any] = {}
        self._cjk_contexts: dict[tuple[str | None, str], tuple[str, bool]] = {}

    def _code_bookmarks(self) -> dict[str, str]:
        bookmarks: dict[str, str] = {}
        for identifier in self.code_languages:
            hashed = hashlib.sha1(
                identifier.encode("utf-8"), usedforsecurity=False
            ).hexdigest()[1:]
            bookmarks[identifier] = identifier
            bookmarks[hashed] = identifier
        return bookmarks

    def _context_key(self, lang: str | None, context: str) -> tuple[str, bool]:
        identity = (lang, context)
        if identity not in self._cjk_contexts:
            self._cjk_contexts[identity] = cjk_key(lang, context)
        return self._cjk_contexts[identity]

    def _fragments(
        self, text: str, lang: str | None, context: str, *, code: bool = False
    ) -> list[tuple[str, str, bool, str]]:
        return fragments(
            text, lang, context, code=code, cjk=self._context_key(lang, context)[0]
        )

    def warn(self, code: str, message: str) -> None:
        if code not in self._warned:
            self.warnings.append({"code": code, "message": message})
            self._warned.add(code)

    def _checked_text(self, text: str) -> str:
        if EMOJI_PATTERN.search(text):
            self.warn(
                "EMOJI_UNVERIFIED",
                "Color emoji rendering is not supported; verify the preview",
            )
        return strip_emoji(text)

    def annotate(self, *, toc: bool = False) -> dict[str, Any]:
        toc_title = None
        if toc:
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
            existing = self.ast["meta"].get("toc-title")
            if existing is None:
                toc_title = {"t": "MetaInlines", "c": [{"t": "Str", "c": title}]}
            elif existing.get("t") == "MetaString":
                toc_title = {
                    "t": "MetaInlines",
                    "c": [{"t": "Str", "c": str(existing.get("c", ""))}],
                }
            else:
                toc_title = existing
            self.ast["meta"]["toc-title"] = toc_title
        # Pandoc writes metadata and the TOC title before the body.
        metadata_keys = ("title", "subtitle", "author")
        if toc:
            metadata_keys += ("toc-title",)
        for key in metadata_keys:
            if key in self.ast["meta"]:
                self.ast["meta"][key] = self._walk(
                    self.ast["meta"][key], self.lang, self.base_direction, "", "ltr"
                )
        self.ast["blocks"] = self._walk(
            self.ast["blocks"], self.lang, self.base_direction, "", "ltr"
        )
        if self.lang:
            self.ast["meta"]["lang"] = {"t": "MetaString", "c": self.lang}
        else:
            self.ast["meta"].pop("lang", None)
        if self.base_direction in {"rtl", "ltr"}:
            self.ast["meta"]["dir"] = {"t": "MetaString", "c": self.base_direction}
        else:
            self.ast["meta"].pop("dir", None)
        if toc:
            visible_title = text_of(toc_title) or title
            self.resolver.resolve(
                "sans",
                (
                    self._checked_text(visible_title)
                    if title_key not in {"ar", "zh-Hans", "zh-Hant", "ja", "ko"}
                    else ""
                ),
            )
            if title_key in {"ar", "zh-Hans", "zh-Hant", "ja", "ko"}:
                key = (
                    "arabic"
                    if title_key == "ar"
                    else cjk_key(title_key, visible_title)[0]
                )
                self.resolver.resolve(key, self._checked_text(visible_title))
        for structure in self._structures:
            structure.events[:] = _coalesce_events(structure.events)
        return self.ast

    def _mark(
        self,
        text: str,
        lang: str | None,
        context: str,
        pdir: str,
        *,
        code: bool = False,
        structure: TextStructure | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        cjk, ambiguous = self._context_key(lang, context)
        for key, part, rtl, name in fragments(text, lang, context, code=code, cjk=cjk):
            if key == "sans" and name != "Common" and self._role == "heading":
                key = "heading"
            self.resolver.resolve(key, self._checked_text(part))
            self.scripts.add(name)
            if name == "Han" and ambiguous:
                self.warn(
                    "CJK_LANGUAGE_AMBIGUOUS",
                    "Unmarked shared Han characters use Simplified Chinese glyphs; add lang spans for regional forms",
                )
            marker = f"{self._marker_prefix}{len(self.runs):06d}"
            # Unicode isolates carry explicit direction; w:rtl mirrors strong script.
            self.runs[marker] = RunContext(
                part,
                key,
                lang,
                rtl,
                pdir,
                name,
                code,
                self._character_style,
                role=self._role,
                cjk=cjk,
                structure=structure,
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
        structure: TextStructure | None = None,
        story: str = "document",
    ) -> Any:
        if isinstance(node, list):
            result = []
            for item in node:
                transformed = self._walk(
                    item,
                    lang,
                    inherited_dir,
                    context,
                    pdir,
                    local_dir,
                    structure,
                    story,
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
                    if _contains_direction_control(content[1]):
                        raise ConfigurationError(
                            "dir",
                            "Explicit direction spans cannot contain bidi controls",
                        )
                    local_dir = attrs["dir"]
                    content[1] = [
                        {
                            "t": "Str",
                            "c": RTL_ISOLATE if local_dir == "rtl" else LTR_ISOLATE,
                        },
                        *content[1],
                        {"t": "Str", "c": POP_DIRECTIONAL_ISOLATE},
                    ]
                    content[0][2] = [
                        attribute
                        for attribute in content[0][2]
                        if attribute[0] != "dir"
                    ]
            previous_style = self._character_style
            if kind == "Span" and "custom-style" in attrs:
                self._character_style = attrs["custom-style"]
            try:
                node["c"][1] = self._walk(
                    content[1],
                    lang,
                    inherited_dir,
                    context,
                    pdir,
                    local_dir,
                    structure,
                    story,
                )
            finally:
                self._character_style = previous_style
            return node
        if kind in {"Para", "Plain", "Header", "MetaInlines"}:
            context = text_of(node)
            pdir = inherited_dir if inherited_dir != "auto" else direction(context)
            structure = TextStructure(story)
            self._structures.append(structure)
            if kind == "Header":
                previous_role = self._role
                self._role = "heading"
                node["c"][2] = self._walk(
                    content[2],
                    lang,
                    inherited_dir,
                    context,
                    pdir,
                    local_dir,
                    structure,
                    story,
                )
                self._role = previous_role
            else:
                node["c"] = self._walk(
                    content,
                    lang,
                    inherited_dir,
                    context,
                    pdir,
                    local_dir,
                    structure,
                    story,
                )
            return node
        if kind == "LineBlock":
            context = text_of(node)
            pdir = inherited_dir if inherited_dir != "auto" else direction(context)
            structure = TextStructure(story)
            self._structures.append(structure)
            lines = []
            for index, line in enumerate(content):
                if index:
                    structure.add_break()
                lines.append(
                    self._walk(
                        line,
                        lang,
                        inherited_dir,
                        context,
                        pdir,
                        local_dir,
                        structure,
                        story,
                    )
                )
            node["c"] = lines
            return node
        if kind == "DefinitionList":
            entries = []
            for term, definitions in content:
                context = text_of(term)
                pdir = inherited_dir if inherited_dir != "auto" else direction(context)
                structure = TextStructure(story)
                self._structures.append(structure)
                term = self._walk(
                    term,
                    lang,
                    inherited_dir,
                    context,
                    pdir,
                    local_dir,
                    structure,
                    story,
                )
                definitions = self._walk(
                    definitions,
                    lang,
                    inherited_dir,
                    "",
                    pdir,
                    local_dir,
                    None,
                    story,
                )
                entries.append([term, definitions])
            node["c"] = entries
            return node
        if kind == "Str":
            if structure is not None:
                structure.add_text(content)
            return self._mark(
                content,
                lang,
                context or content,
                pdir,
                structure=structure,
            )
        if kind == "Code":
            text = f"{LTR_ISOLATE}{content[1]}{POP_DIRECTIONAL_ISOLATE}"
            if structure is not None:
                structure.add_text(text)
            return self._mark(
                text,
                lang,
                context or content[1],
                pdir,
                code=True,
                structure=structure,
            )
        if kind in {"Space", "SoftBreak"}:
            if structure is not None:
                structure.add_space()
            return node
        if kind == "LineBreak":
            if structure is not None:
                structure.add_break()
            return node
        if kind == "CodeBlock":
            self.code_blocks.append(content[1])
            # A code block's own attributes survive syntax highlighting via its ID.
            if not content[0][0]:
                content[0][0] = f"{self._marker_prefix}CODE{len(self.code_blocks) - 1}"
            structure = TextStructure(story, code=True, anchor=content[0][0])
            for index, line in enumerate(_text_lines(content[1])):
                if index:
                    structure.add_break()
                structure.add_text(line)
            self._structures.append(structure)
            for key, part, _, name in self._fragments(
                content[1], lang, content[1], code=True
            ):
                self.resolver.resolve(key, self._checked_text(part))
                self.scripts.add(name)
            self.code_languages[content[0][0]] = lang
            return node
        if kind == "Note":
            node["c"] = self._walk(
                content,
                lang,
                inherited_dir,
                "",
                pdir,
                None,
                None,
                "footnotes",
            )
            return node
        if kind == "Math":
            self.math = True
            self.resolver.resolve("math")
            return node
        if kind in {"RawBlock", "RawInline"}:
            if structure is not None:
                structure.raw = True
            else:
                self._structures.append(TextStructure(story, raw=True))
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
                content,
                lang,
                inherited_dir,
                context,
                pdir,
                local_dir,
                structure,
                story,
            )
        return node

    def apply(self, path: Path) -> dict[str, str]:
        """Apply run properties across body, footnotes and other document parts."""
        with zipfile.ZipFile(path) as source:
            entries = source.infolist()
            if (
                len(entries) > self.limits.archive_entries
                or sum(info.file_size for info in entries) > self.limits.archive_bytes
            ):
                raise ValidationError(
                    str(path), ["DOCX exceeds archive resource limits"]
                )
            with tempfile.NamedTemporaryFile(
                dir=path.parent, suffix=".docx", delete=False
            ) as stream:
                temporary = Path(stream.name)
            try:
                with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
                    checks = self._apply_parts(path, source, target)
                source.close()  # Windows cannot replace an open source archive.
                self._verify_output(temporary)
                os.replace(temporary, path)
                return checks
            finally:
                temporary.unlink(missing_ok=True)

    def _apply_parts(
        self,
        path: Path,
        source_archive: zipfile.ZipFile,
        destination_archive: zipfile.ZipFile,
    ) -> dict[str, str]:
        observed: dict[str, str] = {}
        observed_order: dict[str, list[str]] = {}
        expected_order: dict[str, list[str]] = {}
        for marker, spec in self.runs.items():
            story = spec.structure.story if spec.structure is not None else "document"
            expected_order.setdefault(story, []).append(marker)
        before: list[str] = []
        after: list[str] = []
        code_text: list[str] = []
        entries = source_archive.infolist()
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        character_styles = {}
        for info in entries:
            if info.filename == "word/styles.xml":
                if info.file_size > self.limits.xml_bytes:
                    raise ValidationError(
                        str(path), ["styles.xml exceeds XML resource limit"]
                    )
                styles = etree.fromstring(source_archive.read(info), parser)
                for style in styles.findall(W + "style"):
                    name = style.find(W + "name")
                    if style.get(W + "type") == "character" and name is not None:
                        character_styles[name.get(W + "val")] = style.get(W + "styleId")
        # Pandoc prefixes bookmark names with '_' and hashes names that Word
        # cannot use directly. These aliases preserve language for user IDs too.
        code_bookmarks = self._code_bookmarks()
        for info in entries:
            if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                if info.file_size > self.limits.xml_bytes:
                    raise ValidationError(
                        str(path), [f"{info.filename} exceeds XML resource limit"]
                    )
                root = etree.fromstring(source_archive.read(info), parser)
                if self.math:
                    for value in root.xpath("//m:t/text()", namespaces=NS):
                        self.resolver.resolve("math", self._checked_text(value))
                before.extend(root.xpath("//w:t/text()", namespaces=NS))
                story = _story_for_part(info.filename)
                expected_code = [
                    item
                    for item in self._structures
                    if item.story == story and item.code
                ]
                code_matches = _match_code_structures(
                    expected_code,
                    _code_candidates(root, code_bookmarks, self._marker_prefix),
                )
                for structure, paragraph, bookmark_id in code_matches:
                    if paragraph is not None:
                        structure.bookmark_id = bookmark_id
                code_paragraphs = {
                    id(paragraph): (structure, bookmark_id)
                    for structure, paragraph, bookmark_id in code_matches
                    if paragraph is not None
                }
                paragraph_structures: dict[Any, TextStructure] = {}
                for candidate in root.iter(W + "p"):
                    found: dict[int, TextStructure] = {}
                    for run in candidate.iter(W + "r"):
                        if _nearest_paragraph(run) is not candidate:
                            continue
                        run_style = run.find(W + "rPr/" + W + "rStyle")
                        marker = (
                            run_style.get(W + "val") if run_style is not None else None
                        )
                        spec = self.runs.get(marker)
                        if spec is not None and spec.structure is not None:
                            found[id(spec.structure)] = spec.structure
                    if len(found) == 1:
                        paragraph_structures[candidate] = next(iter(found.values()))
                expected_section_numbers: dict[int, str] = {}
                for paragraph_index, paragraph in enumerate(root.iter(W + "p")):
                    generated_section_number = (
                        _generated_section_number(paragraph, self._marker_prefix)
                        if self.number_sections
                        else None
                    )
                    if generated_section_number is not None:
                        expected_section_numbers[paragraph_index] = (
                            generated_section_number
                        )
                    code_match = code_paragraphs.get(id(paragraph))
                    code = code_match is not None
                    paragraph_events = _paragraph_events(
                        paragraph,
                        generated_section_number=generated_section_number,
                    )
                    paragraph_text = "".join(
                        event for event in paragraph_events if event is not None
                    )
                    if code:
                        code_text.append(paragraph_text)
                    code_lang = (
                        self.code_languages[code_match[0].anchor]
                        if code_match is not None and code_match[0].anchor is not None
                        else self.lang
                    )
                    marked_paragraph = False
                    for run in list(paragraph.iter(W + "r")):
                        run_paragraph = _nearest_paragraph(run)
                        run_style = run.find(W + "rPr/" + W + "rStyle")
                        marker = (
                            run_style.get(W + "val") if run_style is not None else None
                        )
                        if marker in self.runs:
                            order = observed_order.setdefault(story, [])
                            if not order or order[-1] != marker:
                                order.append(marker)
                            spec = self.runs[marker]
                            run_spec = spec
                            value = "".join(run.xpath("./w:t/text()", namespaces=NS))
                            unsafe = self._validate_run_shape(run, value)
                            if unsafe is None and any(
                                child.tag not in {W + "rPr", W + "t"} for child in run
                            ):
                                unsafe = "marker run contains non-text children"
                            if unsafe is None:
                                parts = fragments(
                                    value,
                                    spec.lang,
                                    "",
                                    code=spec.code,
                                    cjk=spec.cjk,
                                )
                                if len(parts) != 1:
                                    unsafe = "marker run contains mixed text fragments"
                                else:
                                    expected_key = self._font_key_for_text(value, spec)
                                    if expected_key is None:
                                        unsafe = (
                                            "marker run font does not cover its text"
                                        )
                                    else:
                                        run_spec = replace(spec, font=expected_key)
                            if unsafe:
                                raise ValidationError(
                                    str(path),
                                    [f"Cannot safely process marker run: {unsafe}"],
                                )
                            observed[marker] = observed.get(marker, "") + value
                            if spec.character_style:
                                style_id = character_styles.get(spec.character_style)
                                if not style_id:
                                    raise ValidationError(
                                        str(path),
                                        [
                                            f"Character style missing: {spec.character_style}"
                                        ],
                                    )
                                run_style.set(W + "val", style_id)
                            elif any(
                                parent.tag == W + "hyperlink"
                                for parent in run.iterancestors()
                            ):
                                run_style.set(W + "val", "Hyperlink")
                            else:
                                run_style.getparent().remove(run_style)
                            self._properties(run, run_spec)
                            self._paragraph(paragraph, spec.paragraph_direction)
                            marked_paragraph = True
                        elif run.find(W + "t") is not None:
                            value = "".join(run.xpath("./w:t/text()", namespaces=NS))
                            # Writer-generated labels, code highlighting and unmarked text.
                            self._split_run(
                                run,
                                value,
                                path=path,
                                code=code,
                                lang=code_lang,
                                context=paragraph_text,
                                structure=paragraph_structures.get(
                                    run_paragraph
                                    if run_paragraph is not None
                                    else paragraph
                                ),
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
                        if (
                            element.tag == W + "style"
                            and element.get(W + "styleId", "") in self.runs
                        ):
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
                        family = self.resolver.resolve(
                            key, self._checked_text(value)
                        ).family
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
                expected_runs = []
                for run in root.iter(W + "r"):
                    if not any((child.text or "") for child in run.findall(W + "t")):
                        continue
                    spec = self._styled_runs.get(run)
                    if spec is None:
                        raise ValidationError(
                            str(path), ["Text run was not styled safely"]
                        )
                    expected_runs.append(spec)
                self._expected_parts[info.filename] = (
                    expected_runs,
                    [
                        (index, self._paragraph_directions[paragraph])
                        for index, paragraph in enumerate(root.iter(W + "p"))
                        if paragraph in self._paragraph_directions
                    ],
                    [item for item in self._structures if item.story == story],
                    expected_section_numbers,
                )
                data = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True
                )
                destination_archive.writestr(info, data)
                self._styled_runs.clear()
                self._paragraph_directions.clear()
            else:
                with (
                    source_archive.open(info) as original,
                    destination_archive.open(info, "w") as destination,
                ):
                    shutil.copyfileobj(original, destination)
        failures = [
            name for name, spec in self.runs.items() if observed.get(name) != spec.text
        ]
        for story in sorted(set(expected_order) | set(observed_order)):
            if observed_order.get(story, []) != expected_order.get(story, []):
                failures.append(f"{story} marker run order mismatch")
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
        return {
            "text_integrity": (
                "partial" if "RAW_CONTENT_UNVERIFIED" in self._warned else "passed"
            ),
            "font_coverage": (
                "unverified" if "EMOJI_UNVERIFIED" in self._warned else "passed"
            ),
            "language_direction": "passed",
        }

    def _verify_output(self, path: Path) -> None:
        """Check serialized output against run/paragraph expectations independently."""
        failures = []
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        with zipfile.ZipFile(path) as archive:
            for name, (
                expected_runs,
                expected_paragraphs,
                expected_structures,
                expected_section_numbers,
            ) in self._expected_parts.items():
                root = etree.fromstring(archive.read(name), parser)
                all_runs = list(root.iter(W + "r"))
                actual_runs = [
                    run
                    for run in all_runs
                    if any((child.text or "") for child in run.findall(W + "t"))
                ]
                for run_index, run in enumerate(all_runs):
                    if self._run_properties_contain_text(run):
                        failures.append(
                            f"{name}: invalid text run shape at run index "
                            f"{run_index}: run properties contain nested text"
                        )
                paragraphs = list(root.iter(W + "p"))
                if len(actual_runs) != len(expected_runs):
                    failures.append(f"{name}: text run stream count mismatch")
                for index, run in enumerate(actual_runs):
                    actual_text = "".join(run.xpath("./w:t/text()", namespaces=NS))
                    for text_node in run.findall(W + "t"):
                        value = text_node.text or ""
                        if (
                            value[:1].isspace() or value[-1:].isspace()
                        ) and text_node.get(XML_SPACE) != "preserve":
                            failures.append(
                                f"{name}: xml:space mismatch at stream index {index}"
                            )
                    unsafe = self._validate_run_shape(run, actual_text)
                    if unsafe:
                        if not self._run_properties_contain_text(run):
                            failures.append(
                                f"{name}: invalid text run shape at stream index "
                                f"{index}: {unsafe}"
                            )
                        continue
                    if index >= len(expected_runs):
                        failures.append(
                            f"{name}: unexpected text run in stream at index {index}"
                        )
                        continue
                    spec = expected_runs[index]
                    if actual_text != spec.text:
                        failures.append(
                            f"{name}: run text mismatch at stream index {index}"
                        )
                    expected_key = self._font_key_for_text(actual_text, spec)
                    props = run.find(W + "rPr")
                    fonts = props.find(W + "rFonts") if props is not None else None
                    if expected_key is None:
                        failures.append(
                            f"{name}: font coverage mismatch at stream index {index}"
                        )
                        continue
                    family = self.resolver.resolve(expected_key).family
                    if (
                        family != self.resolver.resolve(spec.font).family
                        or fonts is None
                        or any(
                            fonts.get(W + slot) != family
                            for slot in ("ascii", "hAnsi", "eastAsia", "cs")
                        )
                    ):
                        failures.append(
                            f"{name}: font coverage mismatch at stream index {index}"
                        )
                    for tag, expected in (
                        ("rtl", spec.rtl),
                        ("cs", spec.script == "Arabic"),
                    ):
                        element = props.find(W + tag) if props is not None else None
                        if element is None or element.get(W + "val") != (
                            "1" if expected else "0"
                        ):
                            failures.append(f"{name}: {tag} mismatch")
                    if spec.lang:
                        element = props.find(W + "lang") if props is not None else None
                        if element is None or any(
                            element.get(W + slot) != spec.lang
                            for slot in ("val", "eastAsia", "bidi")
                        ):
                            failures.append(f"{name}: language mismatch")
                self._verify_structures(
                    name,
                    root,
                    actual_runs,
                    expected_runs,
                    expected_structures,
                    expected_section_numbers,
                    failures,
                )
                for index, value in expected_paragraphs:
                    if index >= len(paragraphs):
                        failures.append(f"{name}: paragraph direction count mismatch")
                        continue
                    element = paragraphs[index].find(W + "pPr/" + W + "bidi")
                    if element is None or element.get(W + "val") != (
                        "1" if value == "rtl" else "0"
                    ):
                        failures.append(f"{name}: paragraph direction mismatch")
        if failures:
            raise ValidationError(str(path), failures[:10])

    def _verify_structures(
        self,
        name: str,
        root: Any,
        actual_runs: list[Any],
        expected_runs: list[RunContext],
        expected_structures: list[TextStructure],
        expected_section_numbers: dict[int, str],
        failures: list[str],
    ) -> None:
        paragraphs = list(root.iter(W + "p"))
        paragraph_indices = {
            paragraph: index for index, paragraph in enumerate(paragraphs)
        }
        expected_groups: list[tuple[TextStructure, set[int]]] = []
        for index, spec in enumerate(expected_runs):
            if spec.structure is None:
                continue
            if not expected_groups or expected_groups[-1][0] is not spec.structure:
                expected_groups.append((spec.structure, set()))
            expected_groups[-1][1].add(index)
        actual_groups: list[tuple[int | None, set[int]]] = []
        for index, run in enumerate(actual_runs[: len(expected_runs)]):
            if expected_runs[index].structure is None:
                continue
            paragraph_index = paragraph_indices.get(_nearest_paragraph(run))
            if not actual_groups or actual_groups[-1][0] != paragraph_index:
                actual_groups.append((paragraph_index, set()))
            actual_groups[-1][1].add(index)
        actual_group_for_run = {
            run_index: group_index
            for group_index, (_, indices) in enumerate(actual_groups)
            for run_index in indices
        }
        expected_group_for_run = {
            run_index: group_index
            for group_index, (_, indices) in enumerate(expected_groups)
            for run_index in indices
        }
        for group_index, (expected, expected_indices) in enumerate(expected_groups):
            overlaps = sorted(
                {
                    actual_group_for_run[index]
                    for index in expected_indices
                    if index in actual_group_for_run
                }
            )
            actual_paragraphs = [actual_groups[index][0] for index in overlaps]
            actual_events = [
                _paragraph_events(
                    paragraphs[paragraph_index],
                    generated_section_number=expected_section_numbers.get(
                        paragraph_index
                    ),
                )
                if paragraph_index is not None
                else None
                for paragraph_index in actual_paragraphs
            ]
            if len(overlaps) != 1:
                failures.append(
                    f"{name}: paragraph group {group_index} paragraphs "
                    f"{actual_paragraphs} structure count mismatch: "
                    f"expected {_events_repr(expected.events)}, actual {_events_repr(actual_events)}"
                )
                continue
            actual_group_index = overlaps[0]
            paragraph_index, actual_indices = actual_groups[actual_group_index]
            merged = len(
                {
                    expected_group_for_run[index]
                    for index in actual_indices
                    if index in expected_group_for_run
                }
            )
            if merged != 1:
                failures.append(
                    f"{name}: paragraph group {group_index} paragraph "
                    f"{paragraph_index} structure count mismatch: "
                    f"expected {_events_repr(expected.events)}, actual {_events_repr(actual_events)}"
                )
                continue
            if paragraph_index is None:
                failures.append(
                    f"{name}: paragraph group {group_index} parent mismatch: "
                    f"expected events {_events_repr(expected.events)}, actual no paragraph"
                )
                continue
            if expected.raw:
                continue
            actual_events = _paragraph_events(
                paragraphs[paragraph_index],
                generated_section_number=expected_section_numbers.get(paragraph_index),
            )
            # Pandoc separates footnote references from note text with a space.
            if (
                expected.story == "footnotes"
                and actual_events
                and isinstance(actual_events[0], str)
                and actual_events[0].startswith(" ")
                and not (
                    expected.events
                    and isinstance(expected.events[0], str)
                    and expected.events[0].startswith(" ")
                )
            ):
                actual_events[0] = actual_events[0][1:]
                if not actual_events[0]:
                    actual_events.pop(0)
            if actual_events != expected.events:
                failures.append(
                    f"{name}: paragraph {paragraph_index} text structure mismatch: "
                    f"expected {_events_repr(expected.events)}, actual {_events_repr(actual_events)}"
                )
        expected_code = [item for item in expected_structures if item.code]
        code_matches = _match_code_structures(
            expected_code, _code_candidates(root, self._code_bookmarks())
        )
        previous_paragraph = -1
        for code_index, (expected, paragraph, _) in enumerate(code_matches):
            if paragraph is None:
                failures.append(
                    f"{name}: code block {code_index} missing paired SourceCode/CodeBlock "
                    f"paragraph for expected anchor {expected.anchor!r}: "
                    f"expected {_events_repr(expected.events)}, actual []"
                )
                continue
            paragraph_index = paragraph_indices[paragraph]
            actual_events = _paragraph_events(
                paragraph,
                generated_section_number=expected_section_numbers.get(paragraph_index),
            )
            if paragraph_index < previous_paragraph:
                failures.append(
                    f"{name}: code block {code_index} paragraph {paragraph_index} "
                    f"anchor order mismatch: expected {expected.anchor!r} "
                    f"events {_events_repr(expected.events)}, actual {_events_repr(actual_events)}"
                )
            previous_paragraph = paragraph_index
            if actual_events != expected.events:
                failures.append(
                    f"{name}: code block {code_index} paragraph {paragraph_index} "
                    f"line structure mismatch: expected {_events_repr(expected.events)}, "
                    f"actual {_events_repr(actual_events)}"
                )

    def _run_properties_contain_text(self, run: Any) -> bool:
        return any(
            next(props.iter(tag), None) is not None
            for props in run.findall(W + "rPr")
            for tag in (W + "r", W + "t")
        )

    def _validate_run_shape(self, run: Any, text: str) -> str | None:
        text_children = run.findall(W + "t")
        if run.getparent() is None:
            return "run has no parent"
        if not text_children:
            return "run has no text nodes"
        if len(run.findall(W + "rPr")) > 1:
            return "run has multiple property nodes"
        if self._run_properties_contain_text(run):
            return "run properties contain nested text"
        if any(len(child) for child in text_children):
            return "text node contains nested markup"
        if any(
            child.tag not in {W + "rPr", W + "t"}
            and any(
                next(child.iter(tag), None) is not None for tag in (W + "r", W + "t")
            )
            for child in run
        ):
            return "run contains nested text runs"
        if any(
            (run.text and run.text.strip())
            or (run.tail and run.tail.strip())
            or (child.tail and child.tail.strip())
            for child in run
        ):
            return "run contains unmanaged text"
        if "".join(child.text or "" for child in text_children) != text:
            return "run text does not match its text nodes"
        return None

    def _font_key_for_text(self, text: str, spec: RunContext) -> str | None:
        parts = fragments(text, spec.lang, "", code=spec.code, cjk=spec.cjk)
        if len(parts) != 1:
            return None
        key = parts[0][0]
        return "heading" if key == "sans" and spec.role == "heading" else key

    def _split_run(
        self,
        run: Any,
        text: str,
        *,
        path: Path,
        code: bool,
        lang: str | None,
        context: str,
        structure: TextStructure | None = None,
    ) -> None:
        cjk = self._context_key(lang, context)[0]
        parts = fragments(text, lang, context, code=code, cjk=cjk)
        unsafe = self._validate_run_shape(run, text)
        if unsafe is None and (
            "".join(part for _, part, _, _ in parts) != text
            or any(not part for _, part, _, _ in parts)
        ):
            unsafe = "text fragments do not match the run"
        if unsafe:
            raise ValidationError(str(path), [f"Cannot safely split run: {unsafe}"])
        if not parts:
            return
        parent = run.getparent()
        for key, part, _, _ in parts:
            self.resolver.resolve(key, self._checked_text(part))
        if len(parts) == 1:
            key, _, rtl, name = parts[0]
            self._properties(
                run,
                RunContext(
                    text,
                    key,
                    lang,
                    rtl,
                    "ltr" if code else direction(text),
                    name,
                    code,
                    role=self._role,
                    cjk=cjk,
                    structure=structure,
                ),
            )
            return

        def make_run(*children: Any) -> Any:
            clone = etree.Element(W + "r")
            clone.attrib.update(run.attrib)
            props = run.find(W + "rPr")
            if props is not None:
                clone.append(copy.deepcopy(props))
            for child in children:
                clone.append(child)
            return clone

        replacements: list[Any] = []
        part_index = 0
        part_offset = 0
        for child in list(run):
            if child.tag == W + "rPr":
                continue
            if child.tag != W + "t":
                replacements.append(make_run(child))
                continue
            source = child.text or ""
            if not source:
                continue
            offset = 0
            while offset < len(source):
                key, part, rtl, name = parts[part_index]
                take = min(len(part) - part_offset, len(source) - offset)
                piece = source[offset : offset + take]
                text_node = copy.deepcopy(child)
                text_node.text = piece
                clone = make_run(text_node)
                self._properties(
                    clone,
                    RunContext(
                        piece,
                        key,
                        lang,
                        rtl,
                        "ltr" if code else direction(text),
                        name,
                        code,
                        role=self._role,
                        cjk=cjk,
                        structure=structure,
                    ),
                )
                replacements.append(clone)
                offset += take
                part_offset += take
                if part_offset == len(part):
                    part_index += 1
                    part_offset = 0
        if part_index != len(parts) or part_offset:
            raise ValidationError(
                str(path), ["Cannot safely split run: text fragments were not consumed"]
            )
        index = parent.index(run)
        for offset, replacement in enumerate(replacements):
            parent.insert(index + offset, replacement)
        if replacements:
            replacements[-1].tail = run.tail
        parent.remove(run)

    def _properties(self, run: Any, spec: RunContext) -> None:
        # Marker contexts can span multiple physical runs; track each run's text.
        actual_text = "".join(run.xpath("./w:t/text()", namespaces=NS))
        self._styled_runs[run] = replace(spec, text=actual_text)
        for text_node in run.findall(W + "t"):
            value = text_node.text or ""
            if value[:1].isspace() or value[-1:].isspace():
                text_node.set(XML_SPACE, "preserve")
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
            if attr.lower().endswith("theme"):
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

    def _paragraph(self, paragraph: Any, value: str) -> None:
        self._paragraph_directions[paragraph] = value
        props = paragraph.find(W + "pPr")
        if props is None:
            props = etree.Element(W + "pPr")
            paragraph.insert(0, props)
        bidi = props.find(W + "bidi")
        if bidi is None:
            bidi = etree.SubElement(props, W + "bidi")
        bidi.set(W + "val", "1" if value == "rtl" else "0")
