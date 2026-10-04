"""Preview generations are ordered, isolated and preserved on failure."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from markdown2docx.report import render_preview


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setattr("markdown2docx.report.shutil.which", lambda binary: binary)
    state = {"raster_status": 0, "pages": 12}

    def run(command, **kwargs):
        if command[0] == "soffice":
            root = Path(command[command.index("--outdir") + 1])
            (root / "input.pdf").write_bytes(b"current PDF")
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        assert command[0] == "pdftoppm"
        directory = Path(command[-1]).parent
        if state["raster_status"] == 0:
            for number in range(1, state["pages"] + 1):
                (directory / f"page-{number}.png").write_bytes(b"current page")
        return SimpleNamespace(returncode=state["raster_status"])

    monkeypatch.setattr("markdown2docx.report.subprocess.run", run)
    return state


def resolver():
    return SimpleNamespace(selected={"sans": SimpleNamespace(source="system")})


@pytest.mark.parametrize("raster_status", [0, 1])
def test_preview_preserves_previous_artifacts(tmp_path, renderer, raster_status):
    renderer["raster_status"] = raster_status
    output = tmp_path / "preview"
    output.mkdir()
    for name in ["preview.pdf", "page-1.png", "page-3.png", "keep.png"]:
        (output / name).write_bytes(b"old")
    report = render_preview(tmp_path / "input.docx", output, resolver())
    assert report["status"] == ("rendered" if raster_status == 0 else "failed")
    assert (output / "preview.pdf").read_bytes() == b"old"
    assert (output / "page-3.png").read_bytes() == b"old"
    assert (output / "keep.png").read_bytes() == b"old"
    if raster_status == 0:
        assert [Path(p).stem for p in report["pages"]] == [
            f"page-{n}" for n in range(1, 13)
        ]
    else:
        assert not list(output.glob("generation-*"))
    assert not list(output.glob(".render-*"))


def test_concurrent_previews_publish_separate_generations(tmp_path, renderer):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: render_preview(
                    tmp_path / "input.docx", tmp_path / "preview", resolver()
                ),
                range(2),
            )
        )
    assert all(report["status"] == "rendered" for report in results)
    assert results[0]["pdf"] != results[1]["pdf"]
    assert all(Path(report["pdf"]).read_bytes() == b"current PDF" for report in results)


def test_preview_page_budget_preserves_previous_generation(tmp_path, renderer):
    report = render_preview(
        tmp_path / "input.docx", tmp_path / "preview", resolver(), max_pages=5
    )
    assert report["status"] == "failed"
    assert not list((tmp_path / "preview").glob("generation-*"))
