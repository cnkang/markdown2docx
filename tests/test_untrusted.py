"""Default-safe conversion for Markdown whose caller is not trusted."""

import base64
import errno
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pypandoc
import pytest

import markdown2docx
from markdown2docx import MarkdownToDocxConverter
from markdown2docx.cli import handle_conversion
from markdown2docx.config import MarkdownToDocxConfig
from markdown2docx.exceptions import ConfigurationError, ConversionError
from markdown2docx.resources import stage_local_resources, validate_resources


def untrusted_converter(tmp_path):
    config = MarkdownToDocxConfig()
    config.international.offline = False
    config.international.resources_offline = False
    config.international.restricted = False
    with patch.object(MarkdownToDocxConverter, "_validate_pandoc"):
        return MarkdownToDocxConverter(config=config)


def parse_ast(directory, markdown):
    source = directory / "input.md"
    source.write_text(markdown, encoding="utf-8")
    parsed = subprocess.run(
        [
            pypandoc.get_pandoc_path(),
            "-f",
            "gfm",
            "-t",
            "json",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(parsed.stdout)


@pytest.mark.parametrize(
    "entry", ["convert_untrusted", "convert_untrusted_with_report"]
)
def test_package_untrusted_entry_points_forward_to_converter(entry, tmp_path):
    source = tmp_path / "input.md"
    source.write_text("Safe text", encoding="utf-8")
    output = tmp_path / "output.docx"
    report = Mock(output_path=str(output), warnings=[])
    with patch("markdown2docx.MarkdownToDocxConverter") as converter_class:
        converter = converter_class.return_value
        getattr(converter, entry).return_value = (
            output if entry == "convert_untrusted" else report
        )

        result = getattr(markdown2docx, entry)(source, output)

    converter_class.assert_called_once_with()
    getattr(converter, entry).assert_called_once_with(source, output)
    assert result == (output if entry == "convert_untrusted" else report)


def test_untrusted_entry_points_are_public():
    assert markdown2docx.convert_untrusted is not None
    assert markdown2docx.convert_untrusted_with_report is not None
    assert "convert_untrusted" in markdown2docx.__all__
    assert "convert_untrusted_with_report" in markdown2docx.__all__


@pytest.mark.parametrize(
    "entry", ["convert_untrusted", "convert_untrusted_with_report"]
)
@pytest.mark.parametrize(
    ("location", "message"),
    [
        ("https://example.com/image.png", "Remote images"),
        ("http://example.com/image.png", "Remote images"),
        ("{relative}", "outside the document"),
        ("{outside}", "outside the document"),
        ("{missing}", "Image resource does not exist"),
        ("{raw_block}", "Raw content"),
        ("{raw_inline}", "Raw content"),
    ],
)
def test_untrusted_entry_rejects_unsafe_content_before_processing(
    tmp_path, entry, location, message
):
    document = tmp_path / entry
    document.mkdir()
    outside = document.parent / f"{entry}-outside.png"
    outside.write_bytes(b"image")
    if location.startswith("https://") or location.startswith("http://"):
        markdown = f"![remote]({location})"
    elif location in {"{relative}", "{outside}"}:
        target = "../outside.png" if location == "{relative}" else outside.as_uri()
        markdown = f"![local]({target})"
    elif location == "{missing}":
        markdown = f"![local]({(document / 'missing.png').as_uri()})"
    elif location == "{raw_block}":
        markdown = "<script>alert(1)</script>"
    else:
        markdown = "text <script>alert(1)</script>"
    converter = untrusted_converter(document)
    source = document / "input.md"
    source.write_text(markdown, encoding="utf-8")
    output = document / "output.docx"
    ast = parse_ast(document, markdown)
    original_validate_resources = markdown2docx.converter.validate_resources

    def validate_then_fail_fast(*args, **kwargs):
        original_validate_resources(*args, **kwargs)
        raise AssertionError("Unsafe content unexpectedly passed validation")

    with (
        patch(
            "markdown2docx.converter.run_pandoc",
            return_value=Mock(stdout=json.dumps(ast)),
        ),
        patch(
            "markdown2docx.converter.validate_resources",
            side_effect=validate_then_fail_fast,
        ),
        patch("markdown2docx.converter.FontResolver") as fonts,
        patch("markdown2docx.converter.DocxTemplateManager") as templates,
        patch("markdown2docx.converter.write_docx") as writer,
        pytest.raises(ConversionError, match=message),
    ):
        getattr(converter, entry)(
            source,
            output,
            restricted=None,
            resources_offline=None,
            offline=None,
        )

    fonts.assert_not_called()
    templates.assert_not_called()
    writer.assert_not_called()
    assert not output.exists()


def image_ast(location):
    return {"t": "Image", "c": [["", [], []], [], [location, ""]]}


PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.mark.skipif(os.name == "nt", reason="posix_only: macOS system temporary alias")
def test_restricted_conversion_under_macos_tmp_alias(monkeypatch):
    document = Path(tempfile.mkdtemp(prefix="resource-root-", dir="/tmp"))
    source = document / "input.md"
    source.write_text("![pixel](image.png)\n", encoding="utf-8")
    (document / "image.png").write_bytes(PIXEL_PNG)
    output = document / "output.docx"
    monkeypatch.setattr(MarkdownToDocxConverter, "_validate_pandoc", lambda _: None)
    from zipfile import ZipFile

    path = MarkdownToDocxConverter().convert_untrusted(source, output)

    assert path == output
    with ZipFile(path) as archive:
        assert any(name.startswith("word/media/") for name in archive.namelist())


@pytest.mark.parametrize(
    "location",
    [
        "../outside.png",
        "sub/../../outside.png",
        "file:///outside.png",
        "file://localhost/outside.png",
        "file://server/share/outside.png",
    ],
)
def test_lexical_escapes_fail_before_path_resolution(tmp_path, location):
    document = tmp_path / "document"
    document.mkdir()
    ast = image_ast(location)

    with (
        patch.object(Path, "resolve", side_effect=AssertionError("resolve called")),
        pytest.raises(
            ConversionError,
            match="outside the document|Remote images",
        ),
    ):
        validate_resources(ast, document, offline=False, restricted=True)


@pytest.mark.skipif(
    os.name == "nt", reason="posix_only: POSIX no-follow directory validation"
)
def test_symlink_escape_does_not_touch_external_canary(tmp_path):
    document = tmp_path / "document"
    document.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "canary.png"
    canary.write_bytes(b"external canary")
    link = document / "escape"
    link.symlink_to(outside, target_is_directory=True)
    ast = image_ast("escape/canary.png")
    accesses = []
    original_open = os.open
    root_descriptor = os.open(document, os.O_RDONLY | os.O_DIRECTORY)
    borrowed_descriptor = os.dup(root_descriptor)

    def record_open(path, flags, *args, **kwargs):
        accesses.append((os.fspath(path), flags))
        return original_open(path, flags, *args, **kwargs)

    try:
        with (
            patch(
                "markdown2docx.output._open_parent",
                return_value=borrowed_descriptor,
            ),
            patch("os.open", side_effect=record_open),
            pytest.raises(ConversionError, match="symbolic link"),
        ):
            validate_resources(ast, document, offline=False, restricted=True)
        with pytest.raises(OSError) as error:
            os.fstat(borrowed_descriptor)
        assert error.value.errno == errno.EBADF
    finally:
        os.close(root_descriptor)

    assert canary.read_bytes() == b"external canary"
    assert not any("canary.png" in path for path, _ in accesses)
    assert any(path == "escape" and flags & os.O_NOFOLLOW for path, flags in accesses)


@pytest.mark.skipif(os.name == "nt", reason="posix_only: POSIX no-follow staging")
def test_posix_staging_maps_deleted_resource_to_conversion_error(tmp_path):
    document = tmp_path / "document"
    document.mkdir()
    image = document / "image.png"
    image.write_bytes(PIXEL_PNG)
    ast = image_ast("image.png")
    validate_resources(ast, document, offline=False, restricted=True)
    image.unlink()

    with pytest.raises(ConversionError, match="does not exist"):
        stage_local_resources(ast, document, tmp_path / "staged", max_bytes=1024)


@pytest.mark.skipif(os.name == "nt", reason="posix_only: POSIX no-follow staging")
def test_posix_staging_rejects_resource_replaced_with_symlink(tmp_path):
    document = tmp_path / "document"
    document.mkdir()
    image = document / "image.png"
    image.write_bytes(PIXEL_PNG)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"external canary")
    ast = image_ast("image.png")
    validate_resources(ast, document, offline=False, restricted=True)
    image.unlink()
    image.symlink_to(outside)

    with pytest.raises(ConversionError, match="symbolic link|reparse"):
        stage_local_resources(ast, document, tmp_path / "staged", max_bytes=1024)

    assert outside.read_bytes() == b"external canary"
    assert not list((tmp_path / "staged").glob("*"))


@pytest.mark.skipif(os.name == "nt", reason="posix_only: POSIX descriptor staging")
@pytest.mark.parametrize(
    ("operation", "error", "message"),
    [
        ("open", FileNotFoundError("removed"), "does not exist"),
        ("open", PermissionError("denied"), "Unable to stage"),
        ("open", OSError(errno.ELOOP, "loop"), "symbolic link"),
        ("fdopen", PermissionError("denied"), "Unable to stage"),
    ],
)
def test_posix_staging_maps_open_and_fdopen_errors(tmp_path, operation, error, message):
    document = tmp_path / "document"
    document.mkdir()
    image = document / "image.png"
    image.write_bytes(PIXEL_PNG)
    staged = tmp_path / "staged"
    staged.mkdir()
    parent = os.open(document, os.O_RDONLY | os.O_DIRECTORY)
    target = (
        "markdown2docx.resources.os.open"
        if operation == "open"
        else "markdown2docx.resources.os.fdopen"
    )
    try:
        with (
            patch("markdown2docx.output._open_parent", return_value=parent),
            patch(target, side_effect=error),
            pytest.raises(ConversionError, match=message),
        ):
            stage_local_resources(
                image_ast(str(image)), document, staged, max_bytes=1024
            )
    finally:
        try:
            os.close(parent)
        except OSError:
            pass


def test_cli_staging_race_is_conversion_failed_not_input_not_found(tmp_path, capsys):
    document = tmp_path / "document"
    document.mkdir()
    image = document / "image.png"
    image.write_bytes(PIXEL_PNG)
    ast = image_ast("image.png")
    validate_resources(ast, document, offline=False, restricted=True)

    def fail_during_staging(*args, **kwargs):
        image.unlink()
        stage_local_resources(ast, document, tmp_path / "staged", max_bytes=1024)

    with patch("markdown2docx.cli.MarkdownToDocxConverter") as converter_class:
        converter_class.return_value.convert_untrusted_with_report.side_effect = (
            fail_during_staging
        )
        result = handle_conversion(
            str(document / "input.md"),
            str(document / "output.docx"),
            None,
            None,
            None,
            None,
            MarkdownToDocxConfig(),
            json_output=True,
            untrusted=True,
        )

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "CONVERSION_FAILED"
    assert payload["error"]["code"] != "INPUT_NOT_FOUND"
    assert not (document / "output.docx").exists()


@pytest.mark.parametrize("location", ["", "."])
def test_document_root_image_is_rejected_as_non_file(tmp_path, location):
    with pytest.raises(ConversionError, match="regular file"):
        validate_resources(
            image_ast(location), tmp_path, offline=False, restricted=True
        )


def test_windows_document_root_is_rejected_before_open(tmp_path, monkeypatch):
    from markdown2docx.resources import _validate_restricted_image

    with (
        patch("markdown2docx.resources.os.name", "nt"),
        patch("markdown2docx.output.open_windows_resource") as opener,
        pytest.raises(ConversionError, match="regular file"),
    ):
        _validate_restricted_image(tmp_path, tmp_path)
    opener.assert_not_called()


@pytest.mark.skipif(
    os.name == "nt", reason="posix_only: POSIX directory descriptor semantics"
)
def test_posix_resource_validation_pins_document_root_once(tmp_path, monkeypatch):
    import markdown2docx.output as output_module

    document = tmp_path / "document"
    document.mkdir()
    image = document / "image.png"
    image.write_bytes(PIXEL_PNG)
    root_descriptor = os.open(document, os.O_RDONLY | os.O_DIRECTORY)
    calls = []

    def pin_root(path):
        calls.append(path)
        return os.dup(root_descriptor)

    monkeypatch.setattr(output_module, "_open_parent", pin_root)
    try:
        validate_resources(
            image_ast("image.png"), document, offline=False, restricted=True
        )
    finally:
        os.close(root_descriptor)

    assert calls == [document]


@pytest.mark.skipif(os.name != "nt", reason="Windows secure handle contract")
def test_windows_stages_readable_local_image(tmp_path):
    document = tmp_path / "document"
    document.mkdir()
    image = document / "image.png"
    image.write_bytes(PIXEL_PNG)
    staged = tmp_path / "staged"
    staged.mkdir()
    ast = image_ast("image.png")

    stage_local_resources(ast, document, staged, max_bytes=1024)

    staged_image = Path(ast["c"][2][0])
    assert staged_image.parent == staged
    assert staged_image.read_bytes() == PIXEL_PNG


@pytest.mark.skipif(os.name != "nt", reason="Windows secure handle contract")
@pytest.mark.parametrize("entry", ["validation", "staging"])
def test_windows_missing_resource_has_stable_error(tmp_path, entry):
    document = tmp_path / "document"
    document.mkdir()
    missing = document / "missing.png"
    with pytest.raises(ConversionError, match="does not exist"):
        if entry == "validation":
            validate_resources(
                image_ast("missing.png"), document, offline=False, restricted=True
            )
        else:
            stage_local_resources(
                image_ast(str(missing)), document, tmp_path / "staged", max_bytes=1024
            )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction and symlink semantics")
@pytest.mark.parametrize("entry", ["validation", "staging"])
@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_windows_resource_links_cannot_escape_document(tmp_path, entry, kind):
    document = tmp_path / "document"
    document.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "canary.png"
    canary.write_bytes(b"external canary")
    link = document / "escape"
    if kind == "junction":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"Directory symlink privilege unavailable: {exc}")
    try:
        with pytest.raises(ConversionError, match="reparse point|symbolic link"):
            if entry == "validation":
                validate_resources(
                    image_ast("escape/canary.png"),
                    document,
                    offline=False,
                    restricted=True,
                )
            else:
                stage_local_resources(
                    image_ast(str(link / "canary.png")),
                    document,
                    tmp_path / "staged",
                    max_bytes=1024,
                )
        assert canary.read_bytes() == b"external canary"
        assert not list((tmp_path / "staged").glob("*"))
    finally:
        if kind == "junction":
            link.rmdir()
        else:
            link.unlink()


def test_windows_resource_constants_are_named():
    import ctypes

    from markdown2docx import output

    assert output.FILE_READ_ATTRIBUTES == 0x80
    assert output.GENERIC_READ == 0x80000000
    assert output.FILE_SHARE_READ == 0x1
    assert output.FILE_SHARE_WRITE == 0x2
    assert output.OPEN_EXISTING == 3
    assert output.FILE_FLAG_OPEN_REPARSE_POINT == 0x00200000
    assert output.FILE_FLAG_BACKUP_SEMANTICS == 0x02000000
    assert output.FILE_ATTRIBUTE_REPARSE_POINT == 0x400
    assert output.FILE_ATTRIBUTE_DIRECTORY == 0x10
    assert output.FILE_TYPE_DISK == 1
    assert output.INVALID_HANDLE_VALUE == ctypes.c_void_p(-1).value
    assert output.WindowsFileAttributes._fields_ == [
        ("attributes", ctypes.c_uint32),
        ("tag", ctypes.c_uint32),
    ]


def test_windows_resource_helpers_reject_reparse_points(monkeypatch, tmp_path):
    """Run the Windows API contract on every host with a minimal ctypes double."""
    import ctypes
    import sys

    from markdown2docx import output

    handles = list(range(100, 140))
    kernels = []
    handle_index = 0
    opened: list[str] = []
    access_modes: list[int] = []
    file_attributes = 0x821
    file_type = 1
    invalid_handle = False

    class Structure(ctypes.Structure):
        _fields_ = [("attributes", ctypes.c_uint32), ("tag", ctypes.c_uint32)]

    reparse_kind = "reparse"

    class WinDLL:
        def __init__(self, *args, **kwargs):
            kernels.append(self)

            def create_file(path, access, *args):
                nonlocal handle_index
                if invalid_handle:
                    return ctypes.c_void_p(-1).value
                handle = handles[handle_index]
                handle_index += 1
                opened.append(path)
                access_modes.append(access)
                return handle

            self.CreateFileW = Mock(side_effect=create_file)
            self.CloseHandle = Mock()

            def information(handle, kind, buffer, size):
                target = Structure.from_address(
                    ctypes.cast(buffer, ctypes.c_void_p).value
                )
                target.attributes = 0x10
                target.tag = 0
                if reparse_kind == "reparse":
                    target.attributes |= 0x400
                if reparse_kind == "file" and opened[-1].endswith("resource"):
                    target.attributes = file_attributes
                return True

            self.GetFileInformationByHandleEx = Mock(side_effect=information)
            self.GetFileType = Mock(side_effect=lambda handle: file_type)

    modules = {
        "ctypes": ctypes,
        "ctypes.wintypes": type(
            "Wintypes",
            (),
            {
                "DWORD": ctypes.c_uint32,
                "HANDLE": ctypes.c_void_p,
                "LPCWSTR": ctypes.c_wchar_p,
                "BOOL": ctypes.c_int,
            },
        ),
        "msvcrt": Mock(
            open_osfhandle=Mock(side_effect=lambda handle, flags: handle + 1000)
        ),
    }
    monkeypatch.setitem(sys.modules, "ctypes", ctypes)
    monkeypatch.setitem(sys.modules, "ctypes.wintypes", modules["ctypes.wintypes"])
    monkeypatch.setitem(sys.modules, "msvcrt", modules["msvcrt"])
    monkeypatch.setattr(ctypes, "WinDLL", WinDLL, raising=False)
    resource_os = SimpleNamespace(
        name="nt",
        path=os.path,
        fspath=os.fspath,
        close=os.close,
    )
    with ExitStack() as stack:
        stack.enter_context(patch("markdown2docx.resources.os", resource_os))
        handle_index = 0
        opened.clear()
        access_modes.clear()
        reparse_kind = "reparse"
        with pytest.raises(OSError, match="reparse point"):
            output.open_windows_resource(tmp_path / "resource", directory=True)
        handle_index = 0
        opened.clear()
        access_modes.clear()
        reparse_kind = "reparse"
        with pytest.raises(OSError, match="reparse point"):
            output.open_windows_resource(tmp_path / "resource", directory=False)
        monkeypatch.setattr(output.os, "O_BINARY", 0x8000, raising=False)
        handle_index = 0
        opened.clear()
        access_modes.clear()
        reparse_kind = "file"
        descriptor = output.open_windows_resource(
            tmp_path / "resource", directory=False
        )
        assert descriptor >= 1100
        directory_access = output.FILE_READ_ATTRIBUTES | output.FILE_TRAVERSE
        assert access_modes[:-1] == [directory_access] * (len(access_modes) - 1)
        assert access_modes[-1] == 0x80000000
        kernel = kernels[-1]
        calls = kernel.CreateFileW.call_args_list
        assert [call.args[2] for call in calls] == [0x3] * len(calls)
        assert [call.args[4] for call in calls] == [3] * len(calls)
        assert all(call.args[5] & 0x00200000 for call in calls)
        assert all(call.args[5] & 0x02000000 for call in calls[:-1])
        assert not calls[-1].args[5] & 0x02000000
        assert kernel.CloseHandle.call_count == len(calls) - 1
        kernel.GetFileType.assert_called_once_with(handles[handle_index - 1])
        assert modules["msvcrt"].open_osfhandle.called

        file_attributes = 0x80
        file_type = 2
        handle_index = 0
        opened.clear()
        access_modes.clear()
        with pytest.raises(OSError, match="regular file"):
            output.open_windows_resource(tmp_path / "resource", directory=False)

        file_attributes = output.FILE_ATTRIBUTE_DIRECTORY
        file_type = 1
        handle_index = 0
        opened.clear()
        access_modes.clear()
        with pytest.raises(OSError, match="regular file"):
            output.open_windows_resource(tmp_path / "resource", directory=False)

        file_attributes = 0x821
        file_type = 1
        modules["msvcrt"].open_osfhandle.side_effect = OSError("fd conversion failed")
        handle_index = 0
        opened.clear()
        access_modes.clear()
        reparse_kind = "file"
        with pytest.raises(OSError, match="fd conversion failed"):
            output.open_windows_resource(tmp_path / "resource", directory=False)
        failed_kernel = kernels[-1]
        assert failed_kernel.CloseHandle.call_count == len(opened)

        monkeypatch.setattr(
            ctypes,
            "WinError",
            lambda code: FileNotFoundError(f"missing resource ({code})"),
            raising=False,
        )
        monkeypatch.setattr(ctypes, "get_last_error", lambda: 2, raising=False)
        invalid_handle = True
        handle_index = 0
        opened.clear()
        access_modes.clear()
        with pytest.raises(FileNotFoundError, match="missing resource"):
            output.open_windows_resource(tmp_path / "resource", directory=False)
        from markdown2docx.resources import _validate_restricted_image

        with pytest.raises(ConversionError, match="does not exist"):
            _validate_restricted_image(tmp_path, tmp_path / "resource")


def test_windows_output_reuses_shared_attribute_contract(monkeypatch, tmp_path):
    import ctypes

    from markdown2docx import output

    calls = []

    def create_file(path, access, share, security, creation, flags, template):
        calls.append((path, access, share, creation, flags))
        return 200

    kernel = SimpleNamespace(
        CreateFileW=Mock(side_effect=create_file),
        CloseHandle=Mock(),
        GetFileInformationByHandleEx=Mock(
            side_effect=lambda handle, kind, buffer, size: (
                setattr(
                    output.WindowsFileAttributes.from_address(
                        ctypes.cast(buffer, ctypes.c_void_p).value
                    ),
                    "attributes",
                    output.FILE_ATTRIBUTE_DIRECTORY,
                )
                or True
            )
        ),
    )
    windows = SimpleNamespace(
        WinError=lambda code: OSError(code),
        get_last_error=lambda: 2,
    )
    wintypes = SimpleNamespace(DWORD=ctypes.c_uint32)
    monkeypatch.setattr(output, "_windows_api", lambda: (windows, kernel, wintypes))
    destination = tmp_path / "output.docx"

    with output._windows_output(destination, overwrite=True) as source:
        source.write_bytes(b"document")

    assert destination.read_bytes() == b"document"
    assert calls
    assert all(access == output.FILE_READ_ATTRIBUTES for _, access, _, _, _ in calls)
    assert all(share == 0x3 for _, _, share, _, _ in calls)
    assert all(creation == output.OPEN_EXISTING for _, _, _, creation, _ in calls)
    assert all(
        flags == output.FILE_FLAG_OPEN_REPARSE_POINT | output.FILE_FLAG_BACKUP_SEMANTICS
        for _, _, _, _, flags in calls
    )
    assert kernel.CloseHandle.called


@pytest.mark.parametrize(
    "entry", ["convert_untrusted", "convert_untrusted_with_report"]
)
@pytest.mark.parametrize(
    "extra_args",
    [
        ["--filter=program"],
        ["--lua-filter=program"],
        ["-Lprogram"],
        ["--defaults=settings.yaml"],
        ["-dsettings.yaml"],
    ],
)
def test_untrusted_entry_rejects_unsafe_arguments_before_processing(
    tmp_path, entry, extra_args
):
    converter = untrusted_converter(tmp_path)
    source = tmp_path / "input.md"
    source.write_text("Safe text", encoding="utf-8")
    output = tmp_path / "output.docx"

    with (
        patch("markdown2docx.converter.run_pandoc") as parser,
        patch("markdown2docx.converter.FontResolver") as fonts,
        patch("markdown2docx.converter.DocxTemplateManager") as templates,
        patch("markdown2docx.converter.write_docx") as writer,
        pytest.raises(ConversionError, match="unavailable in restricted mode"),
    ):
        getattr(converter, entry)(
            source,
            output,
            extra_args=extra_args,
            restricted=None,
            resources_offline=None,
            offline=None,
        )

    parser.assert_not_called()
    fonts.assert_not_called()
    templates.assert_not_called()
    writer.assert_not_called()
    assert not output.exists()


@pytest.mark.parametrize("option", ["offline", "resources_offline", "restricted"])
def test_untrusted_report_rejects_explicit_false_policy(tmp_path, option):
    converter = untrusted_converter(tmp_path)
    source = tmp_path / "input.md"
    source.write_text("Safe text", encoding="utf-8")

    with (
        patch.object(converter, "convert_with_report") as pipeline,
        pytest.raises(ConfigurationError, match=option),
    ):
        converter.convert_untrusted_with_report(source, **{option: False})
    pipeline.assert_not_called()


@pytest.mark.parametrize("option", ["offline", "resources_offline", "restricted"])
@pytest.mark.parametrize("value", [None, True])
def test_untrusted_report_accepts_none_or_true_policy(tmp_path, option, value):
    converter = untrusted_converter(tmp_path)
    source = tmp_path / "input.md"
    source.write_text("Safe text", encoding="utf-8")

    with patch.object(converter, "convert_with_report") as pipeline:
        pipeline.return_value = Mock()
        converter.convert_untrusted_with_report(source, **{option: value})

    assert pipeline.call_args.kwargs[option] is True


@pytest.mark.parametrize(
    "entry",
    [
        "convert",
        "convert_with_report",
        "convert_untrusted",
        "convert_untrusted_with_report",
    ],
)
def test_converters_forward_fixed_untrusted_policy(tmp_path, entry):
    converter = untrusted_converter(tmp_path)
    source = tmp_path / "input.md"
    source.write_text("Safe text", encoding="utf-8")
    output = tmp_path / "output.docx"

    with patch.object(converter, "convert_with_report") as pipeline:
        pipeline.return_value = Mock(output_path=str(output), warnings=[])
        getattr(converter, entry)(source, output)

    kwargs = pipeline.call_args.kwargs
    if entry.startswith("convert_untrusted"):
        assert kwargs["restricted"] is True
        assert kwargs["resources_offline"] is True
        assert kwargs["offline"] is True
    else:
        assert "restricted" not in kwargs
        assert "resources_offline" not in kwargs
        assert "offline" not in kwargs


def test_cli_untrusted_forwards_fixed_safe_policy(capsys):
    report = Mock()
    report.to_dict.return_value = {
        "status": "success",
        "output_path": "output.docx",
    }
    with patch("markdown2docx.cli.MarkdownToDocxConverter") as converter_class:
        converter = converter_class.return_value
        converter.convert_untrusted_with_report.return_value = report

        result = handle_conversion(
            "input.md",
            "output.docx",
            None,
            None,
            None,
            None,
            MarkdownToDocxConfig(),
            json_output=True,
            untrusted=True,
            offline=False,
            resources_offline=False,
            restricted=False,
        )

    assert result == 0
    converter.convert_untrusted_with_report.assert_called_once()
    kwargs = converter.convert_untrusted_with_report.call_args.kwargs
    assert kwargs["offline"] is True
    assert kwargs["resources_offline"] is True
    assert kwargs["restricted"] is True
    converter.convert_with_report.assert_not_called()
    assert json.loads(capsys.readouterr().out)["status"] == "success"


def test_cli_parser_accepts_untrusted_alongside_negative_policy_flags():
    from markdown2docx.cli import create_argument_parser

    args = create_argument_parser().parse_args(
        [
            "input.md",
            "--untrusted",
            "--no-restricted",
            "--no-resources-offline",
            "--no-offline",
        ]
    )
    assert args.untrusted is True
    assert args.restricted is False
    assert args.resources_offline is False
    assert args.offline is False


@pytest.mark.parametrize(
    "markdown",
    [
        "![remote](https://example.com/image.png)",
        "<script>alert(1)</script>",
    ],
)
def test_cli_untrusted_returns_stable_json_error_without_docx(tmp_path, markdown):
    source = tmp_path / "input.md"
    source.write_text(markdown, encoding="utf-8")
    output = tmp_path / "output.docx"
    results = [
        subprocess.run(
            [
                sys.executable,
                "-m",
                "markdown2docx.cli",
                str(source),
                "--output",
                str(output),
                "--untrusted",
                "--no-restricted",
                "--no-resources-offline",
                "--no-offline",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        for _ in range(2)
    ]

    for result in results:
        assert result.returncode == 1, result.stderr
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "error": {
                "code": "CONVERSION_FAILED",
                "message": payload["error"]["message"],
            },
        }
        assert payload["error"]["message"]
        assert "Traceback" not in result.stderr
    assert results[0].stdout == results[1].stdout
    assert not output.exists()
