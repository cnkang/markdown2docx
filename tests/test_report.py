"""Regression checks for repeated page-preview generation."""

from types import SimpleNamespace

import pytest

from markdown2docx.report import render_preview


@pytest.mark.parametrize("raster_status", [0, 1])
def test_preview_excludes_stale_pages(tmp_path, monkeypatch, raster_status):
    source = tmp_path / "input.docx"
    output = tmp_path / "preview"
    output.mkdir()
    for name in ["page-1.png", "page-3.png", "keep.png"]:
        (output / name).write_bytes(b"old")
    monkeypatch.setattr("markdown2docx.report.shutil.which", lambda binary: binary)

    def run(command, **kwargs):
        if command[0] == "soffice":
            from pathlib import Path

            directory = Path(command[command.index("--outdir") + 1])
            (directory / "input.pdf").write_bytes(b"current PDF")
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        assert command[0] == "pdftoppm"
        assert not list(output.glob("page-*.png"))
        if raster_status == 0:
            (output / "page-1.png").write_bytes(b"current page")
        return SimpleNamespace(returncode=raster_status)

    monkeypatch.setattr("markdown2docx.report.subprocess.run", run)
    resolver = SimpleNamespace(selected={"sans": SimpleNamespace(source="system")})
    report = render_preview(source, output, resolver)
    assert report["status"] == "rendered"
    assert report["pages"] == (
        [str((output / "page-1.png").absolute())] if raster_status == 0 else []
    )
    assert not (output / "page-3.png").exists()
    assert (output / "keep.png").read_bytes() == b"old"
