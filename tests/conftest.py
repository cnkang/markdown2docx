"""Tests use prepared verified fonts; network requests must be mocked explicitly."""

import urllib.request

import pytest


@pytest.fixture(autouse=True)
def prohibit_unmocked_downloads(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError(
            "Tests cannot download resources; run scripts/prepare_fonts.py before integration tests"
        )

    monkeypatch.setattr(urllib.request, "urlopen", unavailable)
