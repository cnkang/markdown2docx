"""Preview generations are ordered, isolated and preserved on failure."""

import errno
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import markdown2docx.output as output_module
import markdown2docx.report as report_module
from markdown2docx.output import PinnedDirectory
from markdown2docx.report import (
    _copy_generation,
    _copy_regular,
    _publish_generation,
    render_preview,
)

posix_skip = pytest.mark.skipif(
    os.name == "nt", reason="posix_only: POSIX workspace lifecycle semantics"
)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setattr("markdown2docx.report.shutil.which", lambda binary: binary)
    state = {"raster_status": 0, "pages": 12, "real_run": subprocess.run}

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
    assert all(report["status"] == "rendered" for report in results), results
    assert results[0]["pdf"] != results[1]["pdf"]
    assert all(Path(report["pdf"]).read_bytes() == b"current PDF" for report in results)


def test_preview_page_budget_preserves_previous_generation(tmp_path, renderer):
    report = render_preview(
        tmp_path / "input.docx", tmp_path / "preview", resolver(), max_pages=5
    )
    assert report["status"] == "failed"
    assert not list((tmp_path / "preview").glob("generation-*"))


@pytest.mark.skipif(os.name == "nt", reason="posix_only: symbolic link semantics")
def test_preview_rejects_symlinked_ancestor(tmp_path, renderer):
    protected = tmp_path / "protected"
    protected.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(protected, target_is_directory=True)

    report = render_preview(tmp_path / "input.docx", alias / "preview", resolver())

    assert report["status"] == "failed"
    assert not (protected / "preview").exists()
    assert not list(protected.glob("generation-*"))


@pytest.mark.skipif(
    os.name == "nt", reason="posix_only: directory descriptor publication"
)
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

    assert report["status"] == "rendered", report
    pdf = Path(report["pdf"])
    assert pdf.read_bytes() == b"current PDF"
    assert pdf.parent.parent == moved
    assert not list(protected.glob("generation-*"))
    assert not list(moved.glob(".render-*"))


@pytest.mark.skipif(os.name == "nt", reason="posix_only: no-follow file opens")
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
    original_open_file = PinnedDirectory.open_file
    open_errors = []

    def plant_pdf_link(command, **kwargs):
        result = original_run(command, **kwargs)
        if command[0] == "soffice":
            root = Path(command[command.index("--outdir") + 1])
            pdf = root / "input.pdf"
            pdf.unlink()
            pdf.symlink_to(canary)
        return result

    def record_open(self, name, flags, *args, **kwargs):
        try:
            return original_open_file(self, name, flags, *args, **kwargs)
        except OSError as exc:
            if name == "input.pdf":
                open_errors.append(exc)
            raise

    monkeypatch.setattr("markdown2docx.report.subprocess.run", plant_pdf_link)
    monkeypatch.setattr(PinnedDirectory, "open_file", record_open)

    report = render_preview(tmp_path / "input.docx", output, resolver())

    assert report["status"] == "failed"
    assert open_errors and open_errors[0].errno == errno.ELOOP
    assert canary.read_bytes() == b"protected PDF"
    assert (previous / "preview.pdf").read_bytes() == b"old PDF"
    assert list(output.glob("generation-*")) == [previous]


@pytest.mark.skipif(os.name == "nt", reason="posix_only: directory descriptor contract")
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
    renderer["real_run"](
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


@contextmanager
def pinned(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield PinnedDirectory(path, descriptor)
    finally:
        os.close(descriptor)


@posix_skip
def test_preview_rejects_shared_writable_target(tmp_path, renderer):
    output = tmp_path / "preview"
    output.mkdir()
    output.chmod(0o777)

    report = render_preview(tmp_path / "input.docx", output, resolver())

    assert report["status"] == "failed"
    assert "writable" in report["reason"] or "owner" in report["reason"]
    assert not list(output.glob("generation-*"))


@posix_skip
def test_preview_staging_identity_is_checked_before_rename(tmp_path, monkeypatch):
    source_path = tmp_path / "source"
    target_path = tmp_path / "target"
    protected = tmp_path / "protected"
    source_path.mkdir()
    target_path.mkdir()
    protected.mkdir()
    previous = target_path / "generation-old"
    previous.mkdir()
    (previous / "preview.pdf").write_bytes(b"old PDF")
    moved = tmp_path / "moved-staging"
    original_copy = report_module._copy_generation

    def replace_staging(source, target):
        original_copy(source, target)
        target.path.rename(moved)
        target.path.symlink_to(protected, target_is_directory=True)

    monkeypatch.setattr(report_module, "_copy_generation", replace_staging)
    with pinned(source_path) as source, pinned(target_path) as target:
        source.write_bytes("preview.pdf", b"new PDF")
        with pytest.raises(OSError, match="replaced"):
            _publish_generation(source, target)

    assert list(target_path.glob("generation-*")) == [previous]
    assert not list(target_path.glob(".preview-publish-*"))
    assert not list(protected.iterdir())
    assert (previous / "preview.pdf").read_bytes() == b"old PDF"


@posix_skip
def test_preview_staging_open_failure_removes_directory_entry(tmp_path, monkeypatch):
    source_path = tmp_path / "source"
    target_path = tmp_path / "target"
    source_path.mkdir()
    target_path.mkdir()

    def fail_open(_name):
        raise OSError("staging open failed")

    with pinned(source_path) as source, pinned(target_path) as target:
        monkeypatch.setattr(target, "open_directory", fail_open)
        with pytest.raises(OSError, match="staging open failed"):
            _publish_generation(source, target)

    assert not list(target_path.glob(".preview-publish-*"))


@posix_skip
def test_copy_regular_fstat_failure_closes_both_descriptors(tmp_path, monkeypatch):
    source_path = tmp_path / "source"
    target_path = tmp_path / "target"
    source_path.write_bytes(b"source")
    target_path.write_bytes(b"target")
    source_descriptor = os.open(source_path, os.O_RDONLY)
    target_descriptor = os.open(target_path, os.O_WRONLY)

    def fail_fstat(_descriptor):
        raise OSError("fstat failed")

    with monkeypatch.context() as patch:
        patch.setattr(report_module.os, "fstat", fail_fstat)
        with pytest.raises(OSError, match="fstat failed"):
            _copy_regular(source_descriptor, target_descriptor)

    for descriptor in (source_descriptor, target_descriptor):
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@posix_skip
@pytest.mark.parametrize("operation", ["source", "target"])
def test_copy_regular_fdopen_failure_closes_both_descriptors(
    tmp_path, monkeypatch, operation
):
    source_path = tmp_path / "source"
    target_path = tmp_path / "target"
    source_path.write_bytes(b"source")
    target_path.write_bytes(b"target")
    source_descriptor = os.open(source_path, os.O_RDONLY)
    target_descriptor = os.open(target_path, os.O_WRONLY)
    original_fdopen = os.fdopen

    def fail_fdopen(descriptor, mode, *args, **kwargs):
        if (operation == "source" and mode == "rb") or (
            operation == "target" and mode == "wb"
        ):
            raise OSError("fdopen failed")
        return original_fdopen(descriptor, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(report_module.os, "fdopen", fail_fdopen)
        with pytest.raises(OSError, match="fdopen failed"):
            _copy_regular(source_descriptor, target_descriptor)

    for descriptor in (source_descriptor, target_descriptor):
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@posix_skip
@pytest.mark.parametrize("operation", ["make", "open"])
def test_preview_pdf_descriptor_closes_when_generation_setup_fails(
    tmp_path, renderer, monkeypatch, operation
):
    output = tmp_path / "preview"
    output.mkdir()
    pdf_descriptors = []
    original_open_regular = PinnedDirectory.open_regular

    def track_pdf(self, name):
        descriptor = original_open_regular(self, name)
        if name == "input.pdf":
            pdf_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(PinnedDirectory, "open_regular", track_pdf)
    if operation == "make":

        def fail_make(self, name):
            if name == "generation":
                raise OSError("generation mkdir failed")

        monkeypatch.setattr(PinnedDirectory, "make_directory", fail_make)
    else:
        original_open_directory = PinnedDirectory.open_directory

        def fail_open(self, name):
            if name == "generation":
                raise OSError("generation open failed")
            return original_open_directory(self, name)

        monkeypatch.setattr(PinnedDirectory, "open_directory", fail_open)

    report = render_preview(tmp_path / "input.docx", output, resolver())

    assert report["status"] == "failed"
    assert pdf_descriptors
    for descriptor in pdf_descriptors:
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@posix_skip
@pytest.mark.parametrize("operation", ["make", "open"])
def test_copy_generation_failure_closes_source_child_descriptor(
    tmp_path, monkeypatch, operation
):
    source_path = tmp_path / "source"
    target_path = tmp_path / "target"
    (source_path / "nested").mkdir(parents=True)
    target_path.mkdir()
    child_descriptors = []
    original_open_directory = PinnedDirectory.open_directory

    def track_open(self, name):
        descriptor = original_open_directory(self, name)
        if self.path == source_path and name == "nested":
            child_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(PinnedDirectory, "open_directory", track_open)
    if operation == "make":

        def fail_make(self, name):
            if self.path == target_path and name == "nested":
                raise OSError("target mkdir failed")

        monkeypatch.setattr(PinnedDirectory, "make_directory", fail_make)
    else:

        def fail_target_open(self, name):
            if self.path == target_path and name == "nested":
                raise OSError("target open failed")
            return track_open(self, name)

        monkeypatch.setattr(PinnedDirectory, "open_directory", fail_target_open)

    with pinned(source_path) as source, pinned(target_path) as target:
        with pytest.raises(OSError, match="target .* failed"):
            _copy_generation(source, target)

    assert child_descriptors
    for descriptor in child_descriptors:
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@posix_skip
def test_windows_preview_rename_closes_staging_descriptor_first(tmp_path, monkeypatch):
    source_path = tmp_path / "source"
    target_path = tmp_path / "target"
    source_path.mkdir()
    target_path.mkdir()
    staging_descriptors = []
    original_open_directory = PinnedDirectory.open_directory
    original_replace = os.replace

    def track_open(self, name):
        descriptor = original_open_directory(self, name)
        if name.startswith(".preview-publish-"):
            staging_descriptors.append(descriptor)
        return descriptor

    def checked_replace(source, destination):
        assert staging_descriptors
        with pytest.raises(OSError) as error:
            os.fstat(staging_descriptors[-1])
        assert error.value.errno == errno.EBADF
        return original_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(report_module.os, "name", "nt")
        patch.setattr(
            output_module,
            "open_windows_resource",
            lambda path, **_: os.open(
                path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            ),
        )
        patch.setattr(PinnedDirectory, "open_directory", track_open)
        patch.setattr(report_module.os, "replace", checked_replace)
        with pinned(source_path) as source, pinned(target_path) as target:
            published = _publish_generation(source, target)

    assert published.is_dir()


@posix_skip
def test_preview_render_root_replacement_fails_and_preserves_previous_generation(
    tmp_path, renderer, monkeypatch
):
    output = tmp_path / "preview"
    previous = output / "generation-old"
    previous.mkdir(parents=True)
    (previous / "preview.pdf").write_bytes(b"old PDF")
    original_run = report_module.subprocess.run
    replaced = {}

    def replace_render_root(command, **kwargs):
        result = original_run(command, **kwargs)
        if command[0] == "soffice":
            root = Path(command[command.index("--outdir") + 1])
            moved = root.with_name(f"{root.name}-moved")
            attack = root.with_name(f"{root.name}-attack")
            attack.mkdir()
            root.rename(moved)
            root.symlink_to(attack, target_is_directory=True)
            replaced.update(root=root, moved=moved, attack=attack)
        return result

    monkeypatch.setattr("markdown2docx.report.subprocess.run", replace_render_root)
    try:
        report = render_preview(tmp_path / "input.docx", output, resolver())

        assert report["status"] == "failed"
        assert (previous / "preview.pdf").read_bytes() == b"old PDF"
        assert list(output.glob("generation-*")) == [previous]
        assert not list(replaced["attack"].iterdir())
        assert not os.path.lexists(replaced["root"])
    finally:
        if replaced:
            replaced["attack"].rmdir()
            if replaced["moved"].exists():
                shutil.rmtree(replaced["moved"])
