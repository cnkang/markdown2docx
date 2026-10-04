"""Verified open fonts, platform discovery and an on-demand private cache.

Only exact bytes recorded in the distributed manifest are trusted automatically.
Font family names and font metadata are not evidence of a license.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import tempfile
import urllib.request
from dataclasses import asdict, dataclass
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any

from filelock import FileLock
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

from .exceptions import MarkdownToDocxError


class FontError(MarkdownToDocxError):
    """A font could not be acquired, verified or used for the requested text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def cache_directory() -> Path:
    """Return a per-user cache without modifying system font directories."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return base / "markdown2docx/fonts"


def system_font_directories() -> list[Path]:
    """Discover the standard user and system font locations on each platform."""
    home = Path.home()
    if platform.system() == "Windows":
        return [
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
            Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")))
            / "Microsoft/Windows/Fonts",
        ]
    if platform.system() == "Darwin":
        return [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            home / "Library/Fonts",
        ]
    return [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        home / ".fonts",
        home / ".local/share/fonts",
    ]


def font_info(path: Path) -> tuple[str, set[int]]:
    """Invalidate metadata when an installed font at the same path changes."""
    stat = path.stat()
    family, coverage = _font_info(
        path, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino
    )
    return family, set(coverage)


@lru_cache(maxsize=256)
def _font_info(
    path: Path, mtime: int, ctime: int, size: int, inode: int
) -> tuple[str, set[int]]:
    """Read a static font's preferred family name and Unicode cmap."""
    with TTFont(path, lazy=True) as font:
        name = font["name"].getDebugName(16) or font["name"].getDebugName(1)
        return name or path.stem, set(font.getBestCmap() or {})


@lru_cache(maxsize=16)
def _discover(directories: tuple[Path, ...]) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for directory in directories:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() not in {".ttf", ".otf"} or not path.is_file():
                continue
            try:
                with TTFont(path, lazy=True) as font:
                    family = font["name"].getDebugName(16) or font["name"].getDebugName(
                        1
                    )
                if family:
                    result.setdefault(family, []).append(path)
            except Exception:
                logging.getLogger(__name__).debug(
                    "Skipping unreadable font: %s", path, exc_info=True
                )
                continue
    return result


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass
class FontSelection:
    key: str
    family: str
    path: str
    source: str
    sha256: str
    license: str = "OFL-1.1"
    verified: bool = True
    version: str | None = None
    license_url: str | None = None

    @cached_property
    def coverage(self) -> set[int]:
        return font_info(Path(self.path))[1]

    def report(self) -> dict[str, Any]:
        with TTFont(self.path, lazy=True) as font:
            weight = font["OS/2"].usWeightClass if "OS/2" in font else None
            style = font["name"].getDebugName(17) or font["name"].getDebugName(2)
        return {**asdict(self), "weight": weight, "style": style}


class FontResolver:
    """Resolve exact approved builds; never silently trust an installed name."""

    def __init__(
        self,
        *,
        offline: bool = False,
        cache: Path | None = None,
        directories: list[Path] | None = None,
    ) -> None:
        self.offline = offline
        self.cache = cache or cache_directory()
        self.directories = (
            system_font_directories() if directories is None else directories
        )
        self.manifest = json.loads(
            Path(__file__).with_name("font_manifest.json").read_text(encoding="utf-8")
        )
        self.selected: dict[str, FontSelection] = {}
        self.aliases: dict[str, str] = {"heading": "sans"}

    def refresh(self) -> None:
        """Refresh discovery and metadata after font installation or replacement."""
        self.__dict__.pop("installed", None)
        _discover.cache_clear()
        _font_info.cache_clear()
        self.selected.clear()
        for role, key in list(self.aliases.items()):
            if key.startswith("custom:"):
                self.aliases[role] = self.audit_family(
                    key.removeprefix("custom:"), allow_unverified=True
                )

    @cached_property
    def installed(self) -> dict[str, list[Path]]:
        return _discover(tuple(self.directories))

    def _download(self, url: str, expected: str, destination: Path) -> None:
        """Verify bytes before atomic publication; a failed fetch leaves no entry."""
        temporary: Path | None = None
        try:
            if not url.startswith("https://"):
                raise FontError("FONT_DOWNLOAD_FAILED", "Font sources must use HTTPS")
            request = urllib.request.Request(
                url, headers={"User-Agent": "markdown2docx/0.2"}
            )
            # HTTPS manifest source; checksum verified
            with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
                with tempfile.NamedTemporaryFile(
                    dir=self.cache, delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > 40 * 1024 * 1024:
                            raise FontError(
                                "FONT_DOWNLOAD_FAILED", "Font download exceeds 40 MiB"
                            )
                        stream.write(chunk)
            if digest(temporary) != expected:
                raise FontError("FONT_CHECKSUM_FAILED", f"Checksum mismatch: {url}")
            os.replace(temporary, destination)
        except FontError:
            raise
        except Exception as exc:
            raise FontError(
                "FONT_DOWNLOAD_FAILED", f"Unable to download {url}: {exc}"
            ) from exc
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def resolve(self, key: str, text: str = "") -> FontSelection:
        key = self.aliases.get(key, key)
        if key not in self.selected:
            entry = self.manifest["fonts"][key]
            selected = None
            for path in self.installed.get(entry["family"], []):
                if digest(path) == entry["sha256"]:
                    selected = FontSelection(
                        key, entry["family"], str(path), "system", entry["sha256"]
                    )
                    break
            if selected is None:
                self.cache.mkdir(parents=True, exist_ok=True)
                path = self.cache / entry["filename"]
                license_path = self.cache / entry["license_filename"]
                with FileLock(str(path) + ".lock", timeout=120):
                    for target, url, checksum in [
                        (license_path, entry["license_url"], entry["license_sha256"]),
                        (path, entry["url"], entry["sha256"]),
                    ]:
                        if target.exists() and digest(target) == checksum:
                            continue
                        if self.offline:
                            code = (
                                "FONT_CHECKSUM_FAILED"
                                if target.exists()
                                else "FONT_UNAVAILABLE"
                            )
                            raise FontError(
                                code,
                                f"Verified {key} missing in offline cache: {target}",
                            )
                        self._download(url, checksum, target)
                selected = FontSelection(
                    key, entry["family"], str(path), "cache", entry["sha256"]
                )
            self.selected[key] = selected
            selected.version = entry.get("version")
            selected.license_url = entry.get("license_url")
        selection = self.selected[key]
        # Formatting controls, joiners and variation selectors do not need cmap glyphs.
        missing = {
            ord(c) for c in text if not c.isspace() and not _format_control(c)
        } - selection.coverage
        if missing:
            codes = ", ".join(f"U+{c:04X}" for c in sorted(missing)[:20])
            raise FontError(
                "FONT_GLYPH_MISSING", f"{selection.family} does not cover {codes}"
            )
        return selection

    def audit_family(self, family: str, *, allow_unverified: bool = False) -> str:
        """Audit explicit template/config fonts, including their availability."""
        for key, entry in self.manifest["fonts"].items():
            if entry["family"] == family:
                self.resolve(key)
                return str(key)
        if not allow_unverified:
            raise FontError(
                "FONT_LICENSE_UNVERIFIED",
                f"No approved license record for font: {family}",
            )
        paths = self.installed.get(family, [])
        if not paths:
            raise FontError(
                "FONT_UNAVAILABLE", f"Requested font is not installed: {family}"
            )
        path = paths[0]
        self.selected[f"custom:{family}"] = FontSelection(
            f"custom:{family}",
            family,
            str(path),
            "system",
            digest(path),
            "unverified",
            False,
        )
        return f"custom:{family}"


def _format_control(char: str) -> bool:
    import unicodedata

    return unicodedata.category(char) == "Cf" or 0xFE00 <= ord(char) <= 0xFE0F
