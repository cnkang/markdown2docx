"""Verify font trust, failed downloads and concurrent cache publication."""

import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from markdown2docx.fonts import FontError, FontResolver


@pytest.fixture
def resolver(tmp_path, monkeypatch):
    instance = FontResolver(cache=tmp_path / "cache", directories=[])
    font, license_text = b"verified test font", b"OFL license fixture"
    instance.manifest = {
        "fonts": {
            "sans": {
                "family": "Test Sans",
                "filename": "test.ttf",
                "url": "https://example.test/font",
                "sha256": hashlib.sha256(font).hexdigest(),
                "license_filename": "OFL.txt",
                "license_url": "https://example.test/license",
                "license_sha256": hashlib.sha256(license_text).hexdigest(),
            }
        }
    }
    monkeypatch.setattr(
        "markdown2docx.fonts.font_info",
        lambda path: ("Test Sans", {ord(c) for c in "abc"}),
    )
    monkeypatch.setattr(
        "markdown2docx.fonts.urllib.request.urlopen",
        lambda request, **kwargs: io.BytesIO(
            license_text if request.full_url.endswith("license") else font
        ),
    )
    return instance


def test_verified_cache_and_offline_reuse(resolver):
    selection = resolver.resolve("sans", "abc")
    assert selection.source == "cache" and selection.verified
    assert (resolver.cache / "OFL.txt").read_bytes() == b"OFL license fixture"
    resolver.selected.clear()
    resolver.offline = True
    assert resolver.resolve("sans", "abc").sha256 == selection.sha256


def test_exact_system_build_precedes_download(resolver):
    resolver.cache.mkdir()
    installed = resolver.cache / "installed.ttf"
    installed.write_bytes(b"verified test font")
    resolver.installed = {"Test Sans": [installed]}
    resolver.offline = True
    assert resolver.resolve("sans").source == "system"


def test_same_name_different_bytes_are_not_trusted(resolver):
    resolver.cache.mkdir()
    installed = resolver.cache / "different.ttf"
    installed.write_bytes(b"modified font")
    resolver.installed = {"Test Sans": [installed]}
    resolver.offline = True
    with pytest.raises(FontError) as error:
        resolver.resolve("sans")
    assert error.value.code == "FONT_UNAVAILABLE"


def test_offline_missing_and_corrupt_cache(resolver):
    resolver.offline = True
    with pytest.raises(FontError, match="offline"):
        resolver.resolve("sans")
    (resolver.cache / "OFL.txt").write_bytes(b"wrong")
    with pytest.raises(FontError) as error:
        resolver.resolve("sans")
    assert error.value.code == "FONT_CHECKSUM_FAILED"


def test_corrupt_download_never_published(resolver, monkeypatch):
    monkeypatch.setattr(
        "markdown2docx.fonts.urllib.request.urlopen",
        lambda *args, **kwargs: io.BytesIO(b"tampered"),
    )
    with pytest.raises(FontError) as error:
        resolver.resolve("sans")
    assert error.value.code == "FONT_CHECKSUM_FAILED"
    assert not (resolver.cache / "test.ttf").exists()
    assert all(p.name.endswith(".lock") for p in resolver.cache.iterdir())


def test_network_failure_is_actionable(resolver, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr("markdown2docx.fonts.urllib.request.urlopen", fail)
    with pytest.raises(FontError) as error:
        resolver.resolve("sans")
    assert error.value.code == "FONT_DOWNLOAD_FAILED"


def test_missing_glyphs_and_unknown_license(resolver):
    with pytest.raises(FontError) as error:
        resolver.resolve("sans", "漢")
    assert error.value.code == "FONT_GLYPH_MISSING"
    with pytest.raises(FontError) as error:
        resolver.audit_family("Unknown font")
    assert error.value.code == "FONT_LICENSE_UNVERIFIED"


def test_unverified_font_requires_explicit_exception(resolver):
    resolver.cache.mkdir()
    path = resolver.cache / "unknown.ttf"
    path.write_bytes(b"unknown font")
    resolver.installed = {"Unknown font": [path]}
    key = resolver.audit_family("Unknown font", allow_unverified=True)
    assert not resolver.selected[key].verified
    assert resolver.selected[key].license == "unverified"


def test_concurrent_downloads_publish_identical_bytes(resolver):
    def acquire(_):
        other = FontResolver(cache=resolver.cache, directories=[])
        other.manifest = resolver.manifest
        return other.resolve("sans", "abc").sha256

    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = list(pool.map(acquire, range(4)))
    assert len(set(hashes)) == 1
    assert (resolver.cache / "test.ttf").read_bytes() == b"verified test font"
