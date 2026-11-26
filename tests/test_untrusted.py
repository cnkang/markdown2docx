"""Default-safe conversion for Markdown whose caller is not trusted."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import markdown2docx
from markdown2docx import MarkdownToDocxConverter
from markdown2docx.cli import handle_conversion
from markdown2docx.config import MarkdownToDocxConfig
from markdown2docx.exceptions import ConversionError
from markdown2docx.resources import validate_resources


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
            "pandoc",
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
            restricted=False,
            resources_offline=False,
            offline=False,
        )

    fonts.assert_not_called()
    templates.assert_not_called()
    writer.assert_not_called()
    assert not output.exists()


def image_ast(location):
    return {"t": "Image", "c": [["", [], []], [], [location, ""]]}


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow directory validation")
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

    def record_open(path, flags, *args, **kwargs):
        accesses.append((os.fspath(path), flags))
        return original_open(path, flags, *args, **kwargs)

    with (
        patch("os.open", side_effect=record_open),
        pytest.raises(ConversionError, match="symbolic link"),
    ):
        validate_resources(ast, document, offline=False, restricted=True)

    assert canary.read_bytes() == b"external canary"
    assert not any("canary.png" in path for path, _ in accesses)
    assert any(path == "escape" and flags & os.O_NOFOLLOW for path, flags in accesses)


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
            restricted=False,
            resources_offline=False,
            offline=False,
        )

    parser.assert_not_called()
    fonts.assert_not_called()
    templates.assert_not_called()
    writer.assert_not_called()
    assert not output.exists()


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
