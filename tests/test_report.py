"""Preview generations are ordered, isolated and preserved on failure."""

import errno
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import markdown2docx.report as report_module
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX symbolic link semantics")
def test_preview_rejects_symlinked_ancestor(tmp_path, renderer):
    protected = tmp_path / "protected"
    protected.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(protected, target_is_directory=True)

    report = render_preview(tmp_path / "input.docx", alias / "preview", resolver())

    assert report["status"] == "failed"
    assert not (protected / "preview").exists()
    assert not list(protected.glob("generation-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor publication")
def test_preview_publication_uses_pinned_directory_when_output_is_replaced(
    tmp_path, renderer, monkeypatch
):
    output = tmp_path / "preview"
    output.mkdir()
    moved = tmp_path / "original-preview"
    protected = tmp_path / "protected"
    protected.mkdir()
    original_run = report_module.subprocess.run

    def replace_output(command, **kwargs):
        result = original_run(command, **kwargs)
        if command[0] == "soffice":
            render_root = Path(command[command.index("--outdir") + 1]).absolute()
            output.rename(moved)
            (protected / render_root.name).symlink_to(
                moved / render_root.name, target_is_directory=True
            )
            output.symlink_to(protected, target_is_directory=True)
        return result

    monkeypatch.setattr("markdown2docx.report.subprocess.run", replace_output)

    report = render_preview(tmp_path / "input.docx", output, resolver())

    assert report["status"] == "rendered"
    pdf = Path(report["pdf"])
    assert pdf.read_bytes() == b"current PDF"
    assert pdf.parent.parent == moved
    assert not list(protected.glob("generation-*"))
    assert not list(moved.glob(".render-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow file opens")
def test_preview_pdf_symlink_is_not_read_and_preserves_previous_generation(
    tmp_path, renderer, monkeypatch
):
    output = tmp_path / "preview"
    previous = output / "generation-old"
    previous.mkdir(parents=True)
    (previous / "preview.pdf").write_bytes(b"old PDF")
    canary = tmp_path / "canary.pdf"
    canary.write_bytes(b"protected PDF")
    original_run = report_module.subprocess.run
    copied = []

    def plant_pdf_link(command, **kwargs):
        result = original_run(command, **kwargs)
        if command[0] == "soffice":
            root = Path(command[command.index("--outdir") + 1])
            pdf = root / "input.pdf"
            pdf.unlink()
            pdf.symlink_to(canary)
        return result

    original_copy = report_module.shutil.copyfile

    def record_copy(source, destination, **kwargs):
        copied.append(Path(source))
        return original_copy(source, destination, **kwargs)

    monkeypatch.setattr("markdown2docx.report.subprocess.run", plant_pdf_link)
    monkeypatch.setattr("markdown2docx.report.shutil.copyfile", record_copy)

    report = render_preview(tmp_path / "input.docx", output, resolver())

    assert report["status"] == "failed"
    assert canary not in copied
    assert canary.read_bytes() == b"protected PDF"
    assert (previous / "preview.pdf").read_bytes() == b"old PDF"
    assert list(output.glob("generation-*")) == [previous]


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor contract")
def test_preview_refuses_reparse_error_while_pinning_output(
    tmp_path, renderer, monkeypatch
):
    output = tmp_path / "preview"
    original_open = os.open

    def reject_output(path, flags, *args, **kwargs):
        if os.fspath(path) == output.name and kwargs.get("dir_fd") is not None:
            raise OSError(errno.ELOOP, "Refusing resource reparse point", path)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("markdown2docx.report.os.open", reject_output)

    report = render_preview(tmp_path / "input.docx", output, resolver())

    assert report["status"] == "failed"
    assert not list(output.glob("generation-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows junction semantics")
def test_windows_preview_rejects_junction_ancestor(tmp_path, renderer):
    protected = tmp_path / "protected"
    protected.mkdir()
    junction = tmp_path / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(protected)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        report = render_preview(
            tmp_path / "input.docx", junction / "preview", resolver()
        )
        assert report["status"] == "failed"
        assert not (protected / "preview").exists()
    finally:
        junction.rmdir()
