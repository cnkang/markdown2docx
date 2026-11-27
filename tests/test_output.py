"""Regression coverage for output namespace attacks and atomic publication."""

import ctypes
import ntpath
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from docx import Document
from docx.document import Document as DocumentType

import markdown2docx.converter as converter_module
import markdown2docx.output as output_module
from markdown2docx.config import MarkdownToDocxConfig
from markdown2docx.converter import MarkdownToDocxConverter
from markdown2docx.exceptions import ConversionError, TemplateError, ValidationError
from markdown2docx.output import (
    PinnedDirectory,
    secure_temporary_directory,
    staged_docx_output,
)
from markdown2docx.templates import DocxTemplateManager

posix_only = pytest.mark.skipif(
    os.name == "nt",
    reason="posix_only: POSIX directory descriptor, rename, and symlink semantics",
)
windows_only = pytest.mark.skipif(
    os.name != "nt", reason="Windows directory handles and namespace semantics"
)


def test_mkdir_if_missing_tolerates_concurrent_creation(tmp_path, monkeypatch):
    target = tmp_path / "racing-preview"
    original_mkdir = Path.mkdir

    def racing_mkdir(self, *args, **kwargs):
        original_mkdir(self, *args, **kwargs)
        raise FileExistsError(str(self))

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)
    output_module._mkdir_if_missing(target)
    assert target.is_dir()
    output_module._mkdir_if_missing(target)


def test_mkdir_if_missing_does_not_mkdir_existing_directory(tmp_path, monkeypatch):
    existing = tmp_path / "existing"

    def unexpected_mkdir(self, *args, **kwargs):
        raise AssertionError(f"unexpected mkdir for {self}")

    existing.mkdir()
    monkeypatch.setattr(Path, "mkdir", unexpected_mkdir)
    output_module._mkdir_if_missing(existing)
    assert existing.is_dir()


class WindowsOSProxy:
    """Exercise Windows branches without changing pathlib's host platform."""

    name = "nt"

    def __getattr__(self, name):
        return getattr(os, name)


@pytest.fixture(name="render", params=["conversion", "template"])
def render_docx_fixture(request, monkeypatch, tmp_path):
    """Exercise both real entry points with a controlled document writer."""
    source = tmp_path / "input.md"
    source.write_text("# Document")

    def run(destination, before_write=lambda: None, validate=False):
        if request.param == "conversion":
            monkeypatch.setattr(
                MarkdownToDocxConverter, "_validate_pandoc", lambda _: None
            )

            from markdown2docx.runner import write_docx

            original_convert = write_docx

            def convert(*args, outputfile, **kwargs):
                before_write()
                return original_convert(*args, outputfile=outputfile, **kwargs)

            monkeypatch.setattr("markdown2docx.converter.write_docx", convert)
            return MarkdownToDocxConverter().convert(
                source, destination, validate_output=validate
            )
        original_save = DocumentType.save

        def save(document, path):
            before_write()
            original_save(document, path)

        monkeypatch.setattr(DocumentType, "save", save)
        return DocxTemplateManager.create_modern_template(destination)

    return run


@posix_only
@pytest.mark.parametrize("existing", [False, True])
def test_leaf_symlink_never_changes_target(render, tmp_path, existing):
    """Reject live and dangling leaf links without modifying their targets."""
    target = tmp_path / "protected.txt"
    if existing:
        target.write_text("protected")
    output = tmp_path / "report.docx"
    output.symlink_to(target)
    with pytest.raises((ConversionError, TemplateError), match="symlink"):
        render(output)
    assert output.is_symlink()
    assert target.read_text() == "protected" if existing else not target.exists()


@posix_only
@pytest.mark.parametrize("existing", [False, True])
def test_parent_symlink_is_rejected(render, tmp_path, existing):
    """Reject linked ancestors before creating output directories."""
    protected = tmp_path / "protected"
    if existing:
        protected.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(protected, target_is_directory=True)
    with pytest.raises((ConversionError, TemplateError)):
        render(alias / "nested" / "report.docx")
    assert not (protected / "nested").exists()


@posix_only
def test_leaf_swap_during_generation_preserves_target(render, tmp_path):
    """A link planted during generation must not redirect the write."""
    protected = tmp_path / "protected.txt"
    protected.write_text("protected")
    output = tmp_path / "report.docx"

    def swap():
        output.symlink_to(protected)

    with pytest.raises((ConversionError, TemplateError), match="symlink"):
        render(output, swap)
    assert protected.read_text() == "protected"
    assert not list(tmp_path.glob(".markdown2docx-*"))


@posix_only
def test_parent_swap_during_generation_cannot_redirect_write(render, tmp_path):
    """A replaced parent cannot change the pinned publication directory."""
    parent = tmp_path / "output"
    parent.mkdir()
    moved = tmp_path / "original-output"
    protected = tmp_path / "protected"
    protected.mkdir()
    victim = protected / "report.docx"
    victim.write_text("protected")
    output = parent / "report.docx"

    def swap():
        parent.rename(moved)
        parent.symlink_to(protected, target_is_directory=True)

    assert render(output, swap) == output
    assert victim.read_text() == "protected"
    assert Document(moved / "report.docx") is not None
    assert not list(moved.glob(".markdown2docx-*"))


def test_nested_directory_creation_and_regular_overwrite(render, tmp_path):
    """Keep regular-file overwrite and validation working."""
    output = tmp_path / "nested" / "directory" / "report.docx"
    output.parent.mkdir(parents=True)
    output.write_text("old")
    assert render(output, validate=True) == output
    assert Document(output) is not None
    assert not list(output.parent.glob(".markdown2docx-*"))


def test_missing_directories_are_created(render, tmp_path):
    """Preserve recursive output directory creation."""
    output = tmp_path / "new" / "nested" / "report.docx"
    assert render(output) == output
    assert Document(output) is not None


@posix_only
def test_symlink_swap_at_atomic_replace_never_follows_target(monkeypatch, tmp_path):
    """A last-instant link is replaced as an entry, not followed."""
    output = tmp_path / "report.docx"
    victim = tmp_path / "protected.txt"
    victim.write_text("protected")
    original_rename = os.rename

    def swap_then_rename(source, destination, **kwargs):
        output.symlink_to(victim)
        original_rename(source, destination, **kwargs)

    with staged_docx_output(output) as stage:
        stage.write_bytes(b"document")
        monkeypatch.setattr(os, "rename", swap_then_rename)
    assert victim.read_text() == "protected"
    assert not output.is_symlink()
    assert output.read_bytes() == b"document"


def test_no_overwrite_is_atomic_at_publication(monkeypatch, tmp_path):
    """Preserve a destination created just before exclusive publication."""
    output = tmp_path / "report.docx"
    original_link = os.link

    def create_then_link(source, destination, **kwargs):
        output.write_bytes(b"concurrent writer")
        original_link(source, destination, **kwargs)

    with pytest.raises(FileExistsError):
        with staged_docx_output(output, overwrite=False) as stage:
            stage.write_bytes(b"document")
            monkeypatch.setattr(os, "link", create_then_link)
    assert output.read_bytes() == b"concurrent writer"
    assert not list(tmp_path.glob(".markdown2docx-*"))


def test_converter_no_overwrite_preserves_existing_file(monkeypatch, tmp_path):
    """Expose no-overwrite errors through the converter API."""
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    source = tmp_path / "input.md"
    source.write_text("# Document")
    output = source.with_suffix(".docx")
    output.write_bytes(b"original")
    config = MarkdownToDocxConfig()
    config.conversion.overwrite_existing = False
    with pytest.raises(ConversionError, match="already exists"):
        MarkdownToDocxConverter(config=config).convert(source)
    assert output.read_bytes() == b"original"


def test_failed_generation_preserves_existing_output(render, tmp_path):
    """Writer failures must leave the previous document unchanged."""
    output = tmp_path / "report.docx"
    output.write_bytes(b"original")

    def fail():
        raise RuntimeError("writer failed")

    with pytest.raises((ConversionError, TemplateError), match="writer failed"):
        render(output, fail)
    assert output.read_bytes() == b"original"
    assert not list(tmp_path.glob(".markdown2docx-*"))


def test_validation_failure_preserves_existing_output(monkeypatch, tmp_path):
    """Do not publish an invalid staged document."""
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    source = tmp_path / "input.md"
    source.write_text("# Document")
    output = source.with_suffix(".docx")
    output.write_bytes(b"original")

    def invalid(*_args, outputfile, **_kwargs):
        Path(outputfile).write_bytes(b"invalid")

    monkeypatch.setattr("markdown2docx.converter.write_docx", invalid)
    with pytest.raises(ValidationError) as error:
        MarkdownToDocxConverter().convert(source, validate_output=True)
    assert error.value.output_file == str(output)
    assert output.read_bytes() == b"original"


def test_relative_output_path(monkeypatch, tmp_path):
    """Preserve caller-relative output path semantics."""
    monkeypatch.chdir(tmp_path)
    output = Path("nested/report.docx")
    with staged_docx_output(output, overwrite=False) as stage:
        stage.write_bytes(b"document")
    assert output.read_bytes() == b"document"


@posix_only
def test_unsupported_platform_fails_closed(monkeypatch, tmp_path):
    """Never fall back to race-prone pathname writes."""
    monkeypatch.setattr(os, "supports_dir_fd", set())
    with pytest.raises(OSError, match="not supported"):
        with staged_docx_output(tmp_path / "report.docx"):
            pytest.fail("Writer must not run without secure directory operations")
    assert not (tmp_path / "report.docx").exists()


def test_writer_ignores_untrusted_tmpdir(monkeypatch, tmp_path):
    """An attacker-writable TMPDIR must not hold the writer's private path."""
    temporary = tmp_path / "untrusted-temp"
    temporary.mkdir(mode=0o777)
    monkeypatch.setenv("TMPDIR", str(temporary))
    monkeypatch.setattr("tempfile.tempdir", str(temporary))
    output = tmp_path / "report.docx"
    with staged_docx_output(output) as stage:
        assert temporary not in stage.parents
        stage.write_bytes(b"document")
    assert output.read_bytes() == b"document"


@posix_only
def test_conversion_workspace_ignores_hostile_temporary_configuration(
    monkeypatch, tmp_path
):
    """AST, reference and resources must share a root outside attacker TMPDIR."""
    hostile = tmp_path / "hostile-temp"
    hostile.mkdir(mode=0o777)
    monkeypatch.setenv("TMPDIR", str(hostile))
    monkeypatch.setattr("tempfile.tempdir", str(hostile))
    source = tmp_path / "input.md"
    source.write_text("# Document", encoding="utf-8")
    output = tmp_path / "report.docx"
    observed = {}
    original_stage = converter_module.stage_local_resources
    original_reference = converter_module.DocxTemplateManager.create_reference
    original_writer = converter_module.write_docx

    def stage(ast, root, destination, **kwargs):
        observed["resources"] = Path(destination)
        return original_stage(ast, root, destination, **kwargs)

    def reference(path, *args, **kwargs):
        observed["reference"] = Path(path).parent
        return original_reference(path, *args, **kwargs)

    def write(*args, outputfile, **kwargs):
        observed["ast_file"] = Path(args[0])
        observed["ast"] = observed["ast_file"].parent
        return original_writer(*args, outputfile=outputfile, **kwargs)

    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    monkeypatch.setattr(converter_module, "stage_local_resources", stage)
    monkeypatch.setattr(
        converter_module.DocxTemplateManager, "create_reference", reference
    )
    monkeypatch.setattr(converter_module, "write_docx", write)

    MarkdownToDocxConverter().convert_untrusted(source, output)

    workspace = observed["resources"]
    assert workspace == observed["reference"] == observed["ast"]
    assert observed["ast_file"].parent == workspace
    assert hostile not in workspace.parents
    assert not list(hostile.iterdir())


@posix_only
def test_conversion_workspace_replacement_cannot_capture_ast_resources_or_reference(
    monkeypatch, tmp_path
):
    """A workspace renamed immediately after creation cannot redirect later writes."""
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temporary))
    source = tmp_path / "input.md"
    source.write_text("# Document\n\n![pixel](image.png)", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"image")
    output = tmp_path / "report.docx"
    attack = {"directory": None, "moved": None}
    original_mkdir = os.mkdir

    def descriptor_path(descriptor):
        if sys.platform == "darwin":
            import fcntl

            path = fcntl.fcntl(descriptor, fcntl.F_GETPATH, bytearray(1024))
            return Path(os.fsdecode(path).rstrip("\0"))
        return Path(os.readlink(f"/proc/self/fd/{descriptor}"))

    def rename_after_create(path, mode=0o777, *, dir_fd=None):
        result = original_mkdir(path, mode, dir_fd=dir_fd)
        name = Path(os.fspath(path)).name
        if name.startswith("md2docx-convert-") and attack["directory"] is None:
            parent = (
                descriptor_path(dir_fd) if dir_fd is not None else Path(path).parent
            )
            root = parent / name
            moved = parent / f"{name}-moved"
            redirected = parent / f"{name}-attack"
            attack.update(directory=redirected, moved=moved)
            redirected.mkdir()
            root.rename(moved)
            root.symlink_to(redirected, target_is_directory=True)
        return result

    def stop_writer(*_args, **_kwargs):
        raise RuntimeError("stop after workspace preparation")

    supported = set(os.supports_dir_fd)
    supported.add(rename_after_create)
    monkeypatch.setattr(os, "supports_dir_fd", supported)
    monkeypatch.setattr("markdown2docx.output.os.mkdir", rename_after_create)
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    monkeypatch.setattr(converter_module, "write_docx", stop_writer)

    try:
        with pytest.raises(ConversionError):
            MarkdownToDocxConverter().convert_untrusted(source, output)

        assert attack["directory"] is not None
        assert not list(attack["directory"].iterdir())
        assert not output.exists()
    finally:
        for path in attack.values():
            if path is not None and path.exists():
                shutil.rmtree(path)


@posix_only
def test_secure_temporary_directory_removes_its_root_entry():
    """Successful workspaces must not leave an empty directory in /tmp."""
    with secure_temporary_directory(prefix="md2docx-lifecycle-") as workspace:
        root = workspace.path
        assert root.is_dir()

    assert not os.path.lexists(root)


@pytest.mark.parametrize("stage", ["create", "ast", "reference", "assert", "cleanup"])
def test_conversion_workspace_oserrors_are_conversion_errors(
    monkeypatch, tmp_path, stage
):
    source = tmp_path / "input.md"
    source.write_text("# Document", encoding="utf-8")
    output = tmp_path / "report.docx"
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)

    if stage == "create":

        @contextmanager
        def fail_create(*_args, **_kwargs):
            raise OSError("workspace create failed")
            yield

        monkeypatch.setattr(converter_module, "secure_temporary_directory", fail_create)
    elif stage == "ast":
        original_write = PinnedDirectory.write_bytes

        def fail_write(self, name, *args, **kwargs):
            if name == "input.json":
                raise OSError("AST write failed")
            return original_write(self, name, *args, **kwargs)

        monkeypatch.setattr(PinnedDirectory, "write_bytes", fail_write)
    elif stage == "reference":

        def fail_reference(*_args, **_kwargs):
            raise OSError("reference write failed")

        monkeypatch.setattr(
            converter_module.DocxTemplateManager,
            "create_reference",
            fail_reference,
        )
    elif stage == "assert":

        def fail_assert(self):
            raise OSError("workspace identity failed")

        monkeypatch.setattr(PinnedDirectory, "assert_pinned", fail_assert)
    else:
        original_workspace = converter_module.secure_temporary_directory

        @contextmanager
        def fail_cleanup(*args, **kwargs):
            with original_workspace(*args, **kwargs) as workspace:
                try:
                    yield workspace
                finally:
                    raise OSError("workspace cleanup failed")

        monkeypatch.setattr(
            converter_module, "secure_temporary_directory", fail_cleanup
        )

    with pytest.raises(ConversionError) as error:
        MarkdownToDocxConverter().convert_untrusted(source, output)

    assert isinstance(error.value.original_error, OSError)


@posix_only
def test_windows_workspace_creation_is_atomic_and_pinned(monkeypatch, tmp_path):
    """The Windows workspace must come from the atomic create-and-open helper."""
    parent = tmp_path / "parent"
    parent.mkdir()
    temporary = parent / "md2docx-convert-fixed"
    created = []
    cleaned = []

    def create_directory(_parent_descriptor, directory, prefix):
        workspace_path = directory / temporary.name
        workspace_path.mkdir()
        created.append((directory, prefix))
        return workspace_path, os.open(workspace_path, os.O_RDONLY | os.O_DIRECTORY)

    def open_resource(path, *, directory=True, **_kwargs):
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if directory:
            flags |= os.O_DIRECTORY
        return os.open(path, flags)

    @contextmanager
    def windows_pin(_path):
        yield

    original_remove_contents = output_module._remove_windows_directory_contents

    def remove_contents(path):
        cleaned.append(path)
        original_remove_contents(path)

    kernel = SimpleNamespace(CloseHandle=os.close)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(output_module, "os", WindowsOSProxy())
    monkeypatch.setattr(output_module, "_windows_api", lambda: (None, kernel, None))
    monkeypatch.setattr(output_module, "_windows_directory_pin", windows_pin)
    monkeypatch.setattr(output_module, "_create_windows_directory", create_directory)
    monkeypatch.setattr(output_module, "open_windows_resource", open_resource)
    monkeypatch.setattr(
        output_module, "_remove_windows_directory_contents", remove_contents
    )

    with secure_temporary_directory(
        prefix="md2docx-convert-", directory=Path("parent")
    ) as workspace:
        assert workspace.path == temporary
        assert workspace.path.is_dir()
        (workspace.path / "payload.txt").write_text("payload")

    assert created == [(parent, "md2docx-convert-")]
    assert cleaned == [temporary]
    assert not temporary.exists()


@posix_only
def test_windows_workspace_uses_atomic_ntcreatefile(monkeypatch, tmp_path):
    """The workspace handle must come from the same NtCreateFile that creates it."""
    parent = tmp_path / "parent"
    parent.mkdir()
    parent_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    calls = []

    def create_file(
        handle_out,
        access,
        attributes,
        _status,
        _allocation,
        _file_attributes,
        share,
        disposition,
        options,
        _ea,
        _ea_length,
    ):
        calls.append(
            {
                "access": access,
                "length": attributes.contents.Length,
                "root": attributes.contents.RootDirectory,
                "name_length": attributes.contents.ObjectName.contents.Length,
                "attributes": attributes.contents.Attributes,
                "share": share,
                "disposition": disposition,
                "options": options,
            }
        )
        ctypes.cast(handle_out, ctypes.POINTER(ctypes.c_void_p))[0] = 0x1234
        return 0

    ntdll = SimpleNamespace(
        NtCreateFile=Mock(side_effect=create_file),
        RtlNtStatusToDosError=Mock(return_value=5),
    )
    fake_msvcrt = SimpleNamespace(
        get_osfhandle=lambda _descriptor: 0x5678,
        open_osfhandle=lambda _handle, _flags: 999,
    )
    monkeypatch.setattr(output_module, "_windows_api", lambda: (None, Mock(), None))
    monkeypatch.setattr(output_module, "_ntdll_api", lambda: ntdll)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    try:
        path, descriptor = output_module._create_windows_directory(
            parent_descriptor, parent, "md2docx-"
        )
    finally:
        os.close(parent_descriptor)

    assert path.parent == parent
    assert path.name.startswith("md2docx-")
    assert descriptor == 999
    call = calls[0]
    assert call["access"] & output_module.FILE_TRAVERSE
    assert call["share"] == (
        output_module.FILE_SHARE_READ | output_module.FILE_SHARE_WRITE
    )
    assert call["disposition"] == output_module.FILE_CREATE
    assert call["options"] == (
        output_module.FILE_DIRECTORY_FILE | output_module.FILE_SYNCHRONOUS_IO_NONALERT
    )
    assert call["root"] == 0x5678
    assert call["attributes"] == output_module.OBJ_CASE_INSENSITIVE
    assert call["length"] == ctypes.sizeof(output_module.WindowsObjectAttributes)
    assert call["name_length"] == (len(path.name)) * 2


@pytest.mark.parametrize("replace", [False, True])
def test_windows_workspace_write_uses_reparse_safe_helper(
    monkeypatch, tmp_path, replace
):
    """Windows AST/reference writes must not use pathname O_TRUNC."""
    canary = tmp_path / "canary.docx"
    canary.write_bytes(b"protected")
    reference = tmp_path / "reference.docx"
    actual = tmp_path / "actual.docx"
    calls = []

    def writable(path, *, replace):
        calls.append((path, replace))
        if replace:
            raise OSError("Refusing resource reparse point")
        return os.open(actual, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)

    monkeypatch.setattr(output_module, "os", WindowsOSProxy())
    monkeypatch.setattr(output_module, "open_windows_writable", writable, raising=False)
    workspace = PinnedDirectory(tmp_path, descriptor=0)

    if replace:
        with pytest.raises(OSError, match="reparse point"):
            workspace.write_bytes("reference.docx", b"replacement", replace=True)
    else:
        workspace.write_bytes("reference.docx", b"replacement", replace=False)

    assert calls == [(reference, replace)]
    if replace:
        assert not actual.exists()
    else:
        assert actual.read_bytes() == b"replacement"
    assert canary.read_bytes() == b"protected"


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("reparse", [False, True])
def test_windows_writable_resource_rejects_reparse_and_uses_create_semantics(
    monkeypatch, tmp_path, replace, reparse
):
    """GENERIC_WRITE handles validate reparse tags before CRT conversion."""
    calls = []
    current = []

    def create_file(path, access, share, security, creation, flags, template):
        calls.append((path, access, share, creation, flags))
        current[:] = [path]
        return 200

    def information(_handle, _kind, buffer, _size):
        if not calls[-1][1] & output_module.FILE_READ_ATTRIBUTES:
            raise OSError(13, "access denied")
        details = output_module.WindowsFileAttributes.from_address(
            ctypes.cast(buffer, ctypes.c_void_p).value
        )
        if current[0].endswith("reference.docx"):
            details.attributes = 0x80 | (
                output_module.FILE_ATTRIBUTE_REPARSE_POINT if reparse else 0
            )
        else:
            details.attributes = output_module.FILE_ATTRIBUTE_DIRECTORY
        details.tag = 0
        return True

    kernel = SimpleNamespace(
        CreateFileW=Mock(side_effect=create_file),
        CloseHandle=Mock(),
        GetFileInformationByHandleEx=Mock(side_effect=information),
        GetFileType=Mock(return_value=output_module.FILE_TYPE_DISK),
    )
    osfhandle = Mock(return_value=700)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=osfhandle)
    )

    if reparse:
        with pytest.raises(OSError, match="reparse point"):
            output_module.open_windows_writable(
                tmp_path / "reference.docx", replace=replace
            )
        osfhandle.assert_not_called()
    else:
        assert (
            output_module.open_windows_writable(
                tmp_path / "reference.docx", replace=replace
            )
            == 700
        )
        osfhandle.assert_called_once()

    assert (
        calls[-1][1] == output_module.GENERIC_WRITE | output_module.FILE_READ_ATTRIBUTES
    )
    assert (
        calls[-1][2] == output_module.FILE_SHARE_READ | output_module.FILE_SHARE_WRITE
    )
    assert calls[-1][3] == (output_module.OPEN_EXISTING if replace else 1)
    assert calls[-1][4] & output_module.FILE_FLAG_OPEN_REPARSE_POINT
    assert not calls[-1][4] & output_module.FILE_FLAG_BACKUP_SEMANTICS


@windows_only
def test_windows_conversion_workspace_rejects_junction_parent(tmp_path, monkeypatch):
    protected = tmp_path / "protected"
    protected.mkdir()
    junction = tmp_path / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(protected)],
        check=True,
        capture_output=True,
        text=True,
    )
    source = tmp_path / "input.md"
    source.write_text("# Document", encoding="utf-8")
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    try:
        with pytest.raises(ConversionError, match="reparse|unsafe"):
            MarkdownToDocxConverter().convert_untrusted(
                source, junction / "nested" / "report.docx"
            )
        assert not (protected / "nested").exists()
    finally:
        junction.rmdir()


@windows_only
def test_windows_rejects_junction_output_parent(tmp_path):
    """A junction must not redirect publication into its target directory."""
    protected = tmp_path / "protected"
    nested = protected / "nested"
    nested.mkdir(parents=True)
    canary = nested / "report.docx"
    canary.write_bytes(b"protected")
    junction = tmp_path / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(protected)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        assert junction.is_dir()
        with pytest.raises(OSError, match="reparse point|unsafe output directory"):
            with staged_docx_output(junction / "nested" / "report.docx") as stage:
                stage.write_bytes(b"replacement")
        assert canary.read_bytes() == b"protected"
    finally:
        junction.rmdir()


@windows_only
def test_windows_staged_output_pins_parent_directory(tmp_path):
    """An open staging context must prevent its parent from being renamed."""
    parent = tmp_path / "output"
    parent.mkdir()
    output = parent / "report.docx"
    moved = tmp_path / "moved"

    with staged_docx_output(output) as stage:
        stage.write_bytes(b"before rename")
        with pytest.raises(OSError) as error:
            parent.rename(moved)
        assert getattr(error.value, "winerror", None) in {5, 32}
        assert parent.is_dir()
        assert not moved.exists()
        stage.write_bytes(b"after rename")

    assert output.read_bytes() == b"after rename"


@windows_only
def test_windows_no_overwrite_preserves_existing_file(tmp_path):
    """Exclusive Windows publication must leave an existing document untouched."""
    output = tmp_path / "report.docx"
    output.write_bytes(b"original")

    with pytest.raises(FileExistsError):
        with staged_docx_output(output, overwrite=False) as stage:
            stage.write_bytes(b"replacement")

    assert output.read_bytes() == b"original"


@windows_only
def test_windows_writer_failure_preserves_existing_file(render, tmp_path):
    """A failed Windows writer must not replace the previous document."""
    output = tmp_path / "report.docx"
    output.write_bytes(b"original")

    def fail():
        raise RuntimeError("writer failed")

    with pytest.raises((ConversionError, TemplateError), match="writer failed"):
        render(output, fail)

    assert output.read_bytes() == b"original"
    assert not list(tmp_path.glob(".markdown2docx-*"))


@windows_only
def test_windows_validation_failure_preserves_existing_file(monkeypatch, tmp_path):
    """Invalid staged output must never replace a valid Windows destination."""
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    source = tmp_path / "input.md"
    source.write_text("# Document")
    output = source.with_suffix(".docx")
    output.write_bytes(b"original")

    def invalid(*_args, outputfile, **_kwargs):
        Path(outputfile).write_bytes(b"invalid")

    monkeypatch.setattr("markdown2docx.converter.write_docx", invalid)
    with pytest.raises(ValidationError):
        MarkdownToDocxConverter().convert(source, validate_output=True)

    assert output.read_bytes() == b"original"
    assert not list(tmp_path.glob(".markdown2docx-*"))


@windows_only
def test_windows_rejects_real_casefolded_input_output_alias(collision_guards, tmp_path):
    """Exercise the case-insensitive Windows namespace without normcase patching."""
    source = tmp_path / "input.docx"
    original = b"# Markdown input\n"
    source.write_bytes(original)
    output = tmp_path / "INPUT.DOCX"
    assert source.samefile(output)

    with pytest.raises(
        ConversionError, match="Input and output paths must be different"
    ):
        MarkdownToDocxConverter().convert(source, output)

    _assert_no_conversion_side_effects(collision_guards)
    assert source.read_bytes() == original


@pytest.fixture
def reference_docx(tmp_path):
    """Create a valid reference document for output-identity checks."""
    path = tmp_path / "reference.docx"
    Document().save(str(path))
    return path


@pytest.fixture
def collision_guards(monkeypatch):
    """Fail if collision validation reaches Pandoc or font auditing."""
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    with (
        patch(
            "markdown2docx.converter.run_pandoc",
            side_effect=AssertionError("Pandoc ran before collision validation"),
        ) as pandoc,
        patch(
            "markdown2docx.converter.FontResolver.audit_family",
            side_effect=AssertionError("Font audit ran before collision validation"),
        ) as font_audit,
    ):
        yield pandoc, font_audit


def _assert_no_conversion_side_effects(guards):
    pandoc, font_audit = guards
    pandoc.assert_not_called()
    font_audit.assert_not_called()


def test_convert_rejects_default_output_equal_to_docx_input(collision_guards, tmp_path):
    """A Markdown input named .docx must not become its own default output."""
    source = tmp_path / "input.docx"
    original = b"# Markdown input\n"
    source.write_bytes(original)

    with pytest.raises(
        ConversionError, match="Input and output paths must be different"
    ):
        MarkdownToDocxConverter().convert(source)

    _assert_no_conversion_side_effects(collision_guards)
    assert source.read_bytes() == original


def test_convert_rejects_explicit_output_equal_to_input(collision_guards, tmp_path):
    """Explicit input/output identity must fail before conversion starts."""
    source = tmp_path / "input.docx"
    original = b"# Markdown input\n"
    source.write_bytes(original)

    with pytest.raises(
        ConversionError, match="Input and output paths must be different"
    ):
        MarkdownToDocxConverter().convert(source, source)

    _assert_no_conversion_side_effects(collision_guards)
    assert source.read_bytes() == original


def test_convert_rejects_output_equal_to_reference_template(
    collision_guards, reference_docx, tmp_path
):
    """Publishing output must never replace the reference template."""
    source = tmp_path / "input.md"
    source.write_bytes(b"# Markdown input\n")
    original = reference_docx.read_bytes()
    converter = MarkdownToDocxConverter(reference_doc=reference_docx)

    with pytest.raises(
        ConversionError,
        match="Output path must be different from the reference template",
    ):
        converter.convert(source, reference_docx)

    _assert_no_conversion_side_effects(collision_guards)
    assert reference_docx.read_bytes() == original


@pytest.mark.parametrize(
    ("protected_kind", "output_name", "message"),
    [
        ("input", "input.docx", "Input and output paths must be different"),
        (
            "template",
            "reference.docx",
            "Output path must be different from the reference template",
        ),
    ],
)
def test_convert_rejects_relative_parent_output_alias(
    collision_guards,
    reference_docx,
    tmp_path,
    monkeypatch,
    protected_kind,
    output_name,
    message,
):
    """Relative paths with .. must not alias an input or reference document."""
    source = tmp_path / ("input.docx" if protected_kind == "input" else "input.md")
    source.write_bytes(b"# Markdown input\n")
    protected = source if protected_kind == "input" else reference_docx
    original = protected.read_bytes()
    converter = MarkdownToDocxConverter(
        reference_doc=reference_docx if protected_kind == "template" else None
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConversionError, match=message):
        converter.convert(source.name, Path("missing") / ".." / output_name)

    _assert_no_conversion_side_effects(collision_guards)
    assert protected.read_bytes() == original


@pytest.mark.parametrize("protected_kind", ["input", "template"])
def test_convert_rejects_existing_hardlink_output_alias(
    collision_guards, reference_docx, tmp_path, protected_kind
):
    """samefile must catch existing aliases that lexical normalization misses."""
    source = tmp_path / ("input.docx" if protected_kind == "input" else "input.md")
    source.write_bytes(b"# Markdown input\n")
    protected = source if protected_kind == "input" else reference_docx
    original = protected.read_bytes()
    output = tmp_path / "output.docx"
    try:
        output.hardlink_to(protected)
    except OSError as exc:
        pytest.skip(f"Hard links are unavailable: {exc}")
    converter = MarkdownToDocxConverter(
        reference_doc=reference_docx if protected_kind == "template" else None
    )
    message = (
        "Input and output paths must be different"
        if protected_kind == "input"
        else "Output path must be different from the reference template"
    )

    with pytest.raises(ConversionError, match=message):
        converter.convert(source, output)

    _assert_no_conversion_side_effects(collision_guards)
    assert protected.read_bytes() == original
    assert output.read_bytes() == original


@posix_only
def test_convert_rejects_casefolded_input_output_alias(
    collision_guards, tmp_path, monkeypatch
):
    """Simulate Windows normcase folding on a case-sensitive host."""
    source = tmp_path / "input.docx"
    original = b"# Markdown input\n"
    source.write_bytes(original)
    output = tmp_path / "INPUT.DOCX"
    monkeypatch.setattr(os.path, "normcase", ntpath.normcase)

    with pytest.raises(
        ConversionError, match="Input and output paths must be different"
    ):
        MarkdownToDocxConverter().convert(source, output)

    _assert_no_conversion_side_effects(collision_guards)
    assert source.read_bytes() == original


@posix_only
@pytest.mark.parametrize("protected_kind", ["input", "template"])
def test_convert_allows_distinct_symlink_parent_paths(
    tmp_path, monkeypatch, protected_kind
):
    """Resolve symlinks before .. so distinct legal files are not rejected."""
    root = tmp_path / "root"
    actual = root / "actual"
    nested = actual / "nested"
    nested.mkdir(parents=True)
    alias = root / "alias"
    alias.symlink_to(nested, target_is_directory=True)
    name = "input.docx" if protected_kind == "input" else "reference.docx"
    protected = actual / name
    if protected_kind == "input":
        protected.write_bytes(b"# Markdown input\n")
        source = alias / ".." / name
        reference = None
    else:
        Document().save(str(protected))
        source = root / "source.md"
        source.write_bytes(b"# Markdown input\n")
        reference = alias / ".." / name
    protected_original = protected.read_bytes()
    source_original = source.read_bytes()
    output = root / name
    output.write_bytes(b"existing output")

    class PandocReached(Exception):
        pass

    def reach_pandoc(*_args, **_kwargs):
        raise PandocReached

    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    monkeypatch.setattr("markdown2docx.converter.run_pandoc", reach_pandoc)
    converter = MarkdownToDocxConverter(reference_doc=reference)

    with pytest.raises(PandocReached):
        converter.convert(source, output)

    assert protected.read_bytes() == protected_original
    assert source.read_bytes() == source_original
    assert output.read_bytes() == b"existing output"


def test_validate_output_path_ignores_missing_samefile(monkeypatch, tmp_path):
    """A not-yet-created output is not an identity collision."""
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    source = tmp_path / "input.docx"
    source.write_bytes(b"# Markdown input\n")
    output = tmp_path / "output.docx"
    converter = MarkdownToDocxConverter()

    with patch(
        "markdown2docx.converter.os.path.samefile",
        side_effect=FileNotFoundError,
    ):
        converter._validate_output_path(output, str(source))


def test_convert_wraps_samefile_oserror(collision_guards, tmp_path):
    """Identity check failures other than missing files must fail closed."""
    source = tmp_path / "input.docx"
    source.write_bytes(b"# Markdown input\n")
    output = tmp_path / "output.docx"
    output.write_bytes(b"existing output")

    with (
        patch(
            "markdown2docx.converter.os.path.samefile",
            side_effect=PermissionError("denied"),
        ),
        pytest.raises(
            ConversionError, match="Unable to compare output path identity"
        ) as error,
    ):
        MarkdownToDocxConverter().convert(source, output)

    _assert_no_conversion_side_effects(collision_guards)
    assert error.value.input_file == str(source)
    assert isinstance(error.value.original_error, PermissionError)
    assert source.read_bytes() == b"# Markdown input\n"
    assert output.read_bytes() == b"existing output"
