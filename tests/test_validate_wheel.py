"""Synthetic wheel and sdist contracts for the release distribution validator."""

import base64
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import os
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import unicodedata
import zipfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_wheel.py"
PROJECT_NAME = "markdown2docx"
VERSION = "0.2.0"
DIST_INFO = f"{PROJECT_NAME}-{VERSION}.dist-info"
SDIST_ROOT = f"{PROJECT_NAME}-{VERSION}"
METADATA = f"""Metadata-Version: 2.5
Name: {PROJECT_NAME}
Version: {VERSION}
Summary: Synthetic distribution fixture
License-Expression: MIT
License-File: LICENSE
Requires-Python: >=3.14

Synthetic package.
""".encode()
ENTRY_POINTS = b"[console_scripts]\nmarkdown2docx = markdown2docx.cli:main\n"
WHEEL_METADATA = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
LICENSE = b"MIT License\n\nPermission is hereby granted, free of charge.\n"
PYPROJECT = f"""[build-system]
requires = ["hatchling==1.33.0"]
build-backend = "hatchling.build"

[project]
name = "{PROJECT_NAME}"
version = "{VERSION}"
license = "MIT"
requires-python = ">=3.14"

[project.scripts]
{PROJECT_NAME} = "{PROJECT_NAME}.cli:main"
""".encode()
PKG_INFO = METADATA


@pytest.fixture(name="validator")
def validator_fixture():
    assert SCRIPT_PATH.is_file(), "scripts/validate_wheel.py is missing"
    spec = importlib.util.spec_from_file_location("validate_wheel", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wheel_files(**overrides):
    files = {
        f"{PROJECT_NAME}/__init__.py": b'__version__ = "0.2.0"\n',
        f"{PROJECT_NAME}/cli.py": b"def main():\n    pass\n",
        f"{PROJECT_NAME}/version.py": b'__version__ = "0.2.0"\n',
        f"{PROJECT_NAME}/font_manifest.json": b'{"fonts": []}\n',
        f"{PROJECT_NAME}/report_schema.json": b'{"type": "object"}\n',
        f"{DIST_INFO}/METADATA": METADATA,
        f"{DIST_INFO}/WHEEL": WHEEL_METADATA,
        f"{DIST_INFO}/entry_points.txt": ENTRY_POINTS,
        f"{DIST_INFO}/licenses/LICENSE": LICENSE,
    }
    files.update(overrides)
    return files


def record_hash(data):
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def record_contents(files):
    rows = [f"{name},{record_hash(data)},{len(data)}" for name, data in files.items()]
    rows.append(f"{DIST_INFO}/RECORD,,")
    return "\n".join(rows).encode() + b"\n"


def record_with_fields(files, target, hash_value, size_value):
    rows = []
    for name, data in files.items():
        if name == target:
            rows.append(f"{name},{hash_value},{size_value}")
        else:
            rows.append(f"{name},{record_hash(data)},{len(data)}")
    rows.append(f"{DIST_INFO}/RECORD,,")
    return "\n".join(rows).encode() + b"\n"


def write_wheel(
    directory,
    *,
    filename=None,
    files=None,
    omit=(),
    record=True,
):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (filename or f"{PROJECT_NAME}-{VERSION}-py3-none-any.whl")
    contents = dict(wheel_files() if files is None else files)
    for name in omit:
        contents.pop(name, None)
    if record:
        contents[f"{DIST_INFO}/RECORD"] = record_contents(contents)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    return path


def sdist_files(**overrides):
    files = {
        f"{SDIST_ROOT}/pyproject.toml": PYPROJECT,
        f"{SDIST_ROOT}/PKG-INFO": PKG_INFO,
        f"{SDIST_ROOT}/README.md": b"# Synthetic distribution\n",
        f"{SDIST_ROOT}/LICENSE": LICENSE,
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/__init__.py": b'__version__ = "0.2.0"\n',
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/cli.py": b"def main():\n    pass\n",
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/version.py": b'__version__ = "0.2.0"\n',
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/font_manifest.json": b'{"fonts": []}\n',
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/report_schema.json": b'{"type": "object"}\n',
    }
    files.update(overrides)
    return files


def write_sdist(directory, *, files=None, omit=()):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SDIST_ROOT}.tar.gz"
    contents = dict(sdist_files() if files is None else files)
    for name in omit:
        contents.pop(name, None)
    with tarfile.open(path, "w:gz") as archive:
        for name, data in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return path


def write_member_sdist(directory, members):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SDIST_ROOT}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for member, data in members:
            source = io.BytesIO(data) if member.isfile() else None
            archive.addfile(member, source)
    return path


def file_member(name, data=b"payload"):
    member = tarfile.TarInfo(name)
    member.size = len(data)
    return member, data


def raw_tar_header(name, size=0, typeflag=b"0"):
    header = bytearray(512)
    encoded_name = name.encode("utf-8")
    header[: len(encoded_name)] = encoded_name
    header[124:136] = f"{size:011o}\0".encode("ascii")
    header[148:156] = b"        "
    header[156:157] = typeflag
    checksum = sum(header)
    header[148:156] = f"{checksum:06o}\0 ".encode("ascii")
    return bytes(header)


def write_raw_tar(directory, headers):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SDIST_ROOT}.tar.gz"
    with gzip.open(path, "wb") as archive:
        for name, size, typeflag in headers:
            archive.write(raw_tar_header(name, size, typeflag))
            archive.write(b"x" * size)
            archive.write(b"\0" * (-size % 512))
        archive.write(b"\0" * 1024)
    return path


def zip_eocd(entries=0, directory_size=0, directory_offset=0, comment=b""):
    return (
        struct.pack(
            "<4s4H2LH",
            b"PK\x05\x06",
            0,
            0,
            entries,
            entries,
            directory_size,
            directory_offset,
            len(comment),
        )
        + comment
    )


def write_complete_distribution(directory):
    return write_wheel(directory), write_sdist(directory)


def test_complete_distribution_is_accepted(validator, tmp_path):
    wheel, sdist = write_complete_distribution(tmp_path)

    artifacts = validator.validate_distribution_directory(tmp_path, VERSION)

    assert artifacts.wheel.path == wheel
    assert artifacts.wheel.version == VERSION
    assert artifacts.wheel.console_scripts == {
        "markdown2docx": "markdown2docx.cli:main"
    }
    assert artifacts.sdist.path == sdist
    assert artifacts.sdist.version == VERSION


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (f"Name: {PROJECT_NAME}", "Name: other-project", "Name"),
        (f"Version: {VERSION}", "Version: 9.9.9", "Version"),
        ("Requires-Python: >=3.14", "Requires-Python: >=3.13", "Requires-Python"),
        ("License-Expression: MIT", "License-Expression: Apache-2.0", "MIT"),
        ("License-File: LICENSE\n", "", "License-File"),
    ],
)
def test_wheel_rejects_incorrect_metadata(validator, tmp_path, old, new, message):
    files = wheel_files(
        **{f"{DIST_INFO}/METADATA": METADATA.replace(old.encode(), new.encode())}
    )
    wheel = write_wheel(tmp_path, files=files)

    with pytest.raises(ValueError, match=message):
        validator.validate_wheel(wheel, VERSION)


def test_wheel_rejects_filename_version_mismatch(validator, tmp_path):
    wheel = write_wheel(
        tmp_path,
        filename=f"{PROJECT_NAME}-9.9.9-py3-none-any.whl",
    )

    with pytest.raises(ValueError, match="filename"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize(
    "entry_points",
    [
        b"",
        b"[console_scripts]\nother = markdown2docx.cli:main\n",
        b"[console_scripts]\nmarkdown2docx = markdown2docx.other:main\n",
        b"[console_scripts]\nmarkdown2docx = markdown2docx.cli\n",
    ],
)
def test_wheel_rejects_missing_or_incorrect_console_entry_point(
    validator, tmp_path, entry_points
):
    wheel = write_wheel(
        tmp_path,
        files=wheel_files(**{f"{DIST_INFO}/entry_points.txt": entry_points}),
    )

    with pytest.raises(ValueError, match="markdown2docx.cli:main"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize("asset", ["font_manifest.json", "report_schema.json"])
def test_wheel_rejects_missing_json_asset(validator, tmp_path, asset):
    wheel = write_wheel(tmp_path, omit=(f"{PROJECT_NAME}/{asset}",))

    with pytest.raises(ValueError, match=asset):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize("asset", ["font_manifest.json", "report_schema.json"])
@pytest.mark.parametrize("data", [b"{broken", b"[]", b""])
def test_wheel_rejects_invalid_json_asset(validator, tmp_path, asset, data):
    wheel = write_wheel(
        tmp_path,
        files=wheel_files(**{f"{PROJECT_NAME}/{asset}": data}),
    )

    with pytest.raises(ValueError, match=asset):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize(
    "extra",
    [
        f"{PROJECT_NAME}/__pycache__/cli.pyc",
        "tests/test_distribution.py",
        f"{PROJECT_NAME}/tests/test_distribution.py",
        ".venv/lib/python3.14/site-packages/other.py",
        f"{PROJECT_NAME}/.venv/other.py",
    ],
)
def test_wheel_rejects_development_or_environment_files(validator, tmp_path, extra):
    wheel = write_wheel(tmp_path, files=wheel_files(**{extra: b"unwanted\n"}))

    with pytest.raises(ValueError, match="unwanted|__pycache__|tests|\\.venv"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize("contents", [b"", b"MIT License\n"])
def test_wheel_rejects_missing_or_truncated_license(validator, tmp_path, contents):
    wheel = write_wheel(
        tmp_path,
        files=wheel_files(**{f"{DIST_INFO}/licenses/LICENSE": contents}),
    )

    with pytest.raises(ValueError, match="LICENSE|license"):
        validator.validate_wheel(wheel, VERSION)


def test_wheel_rejects_missing_license(validator, tmp_path):
    wheel = write_wheel(tmp_path, omit=(f"{DIST_INFO}/licenses/LICENSE",))

    with pytest.raises(ValueError, match="LICENSE|license"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize(
    "record",
    [
        b"path,hash,size\n",
        record_contents(wheel_files()) + b"unlisted.py,,\n",
        record_contents(wheel_files()) + f"{DIST_INFO}/RECORD,,\n".encode(),
    ],
)
def test_wheel_rejects_incomplete_or_inconsistent_record(validator, tmp_path, record):
    wheel = write_wheel(
        tmp_path,
        files=wheel_files(**{f"{DIST_INFO}/RECORD": record}),
        record=False,
    )

    with pytest.raises(ValueError, match="RECORD"):
        validator.validate_wheel(wheel, VERSION)


def test_wheel_rejects_missing_record(validator, tmp_path):
    wheel = write_wheel(tmp_path, record=False)

    with pytest.raises(ValueError, match="RECORD"):
        validator.validate_wheel(wheel, VERSION)


def test_record_reader_stops_when_line_count_exceeds_member_count(
    validator, tmp_path, monkeypatch
):
    files = wheel_files()
    record = record_contents(files) + b"extra-one,,\nextra-two,,\n"
    wheel = write_wheel(
        tmp_path,
        files={**files, f"{DIST_INFO}/RECORD": record},
        record=False,
    )
    original_reader = csv.reader
    member_count = len(files) + 1

    def guarded_reader(*args, **kwargs):
        for index, row in enumerate(original_reader(*args, **kwargs)):
            if index > member_count:
                raise AssertionError("RECORD reader consumed past the first excess row")
            yield row

    monkeypatch.setattr(validator.csv, "reader", guarded_reader)

    with pytest.raises(validator.DistributionError, match="RECORD"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize(
    "size_value",
    ["9" * 10_000, "+1", "-1", "1.0", "\uff11\uff12", " 1", "1 "],
)
def test_record_illegal_sizes_raise_distribution_error(validator, tmp_path, size_value):
    files = wheel_files()
    target = f"{PROJECT_NAME}/__init__.py"
    record = record_with_fields(files, target, record_hash(files[target]), size_value)
    wheel = write_wheel(
        tmp_path,
        files={**files, f"{DIST_INFO}/RECORD": record},
        record=False,
    )

    with pytest.raises(validator.DistributionError, match="RECORD.*size"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize(
    "relative_path",
    [
        "../escape.py",
        f"/{PROJECT_NAME}/escape.py",
        f"{DIST_INFO}\\METADATA",
    ],
)
def test_wheel_rejects_unsafe_member_names(validator, tmp_path, relative_path):
    wheel = write_wheel(
        tmp_path,
        files=wheel_files(**{relative_path: b"escape\n"}),
    )

    with pytest.raises(ValueError, match="unsafe|member|path"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize(
    ("constant", "size_delta"),
    [
        ("MAX_WHEEL_BYTES", -1),
        ("MAX_WHEEL_MEMBERS", -1),
        ("MAX_WHEEL_MEMBER_BYTES", -1),
        ("MAX_WHEEL_UNCOMPRESSED_BYTES", -1),
    ],
)
def test_wheel_enforces_archive_resource_limits(
    validator, tmp_path, monkeypatch, constant, size_delta
):
    files = wheel_files()
    wheel = write_wheel(tmp_path, files=files)
    sizes = {
        "MAX_WHEEL_BYTES": wheel.stat().st_size,
        "MAX_WHEEL_MEMBERS": len(files) + 1,
        "MAX_WHEEL_MEMBER_BYTES": max(len(data) for data in files.values()),
        "MAX_WHEEL_UNCOMPRESSED_BYTES": sum(len(data) for data in files.values()),
    }
    monkeypatch.setattr(validator, constant, sizes[constant] + size_delta)

    with pytest.raises(ValueError, match="wheel|Wheel|limit|size|members"):
        validator.validate_wheel(wheel, VERSION)


def test_wheel_accepts_exact_archive_resource_limits(validator, tmp_path, monkeypatch):
    files = wheel_files()
    wheel = write_wheel(tmp_path, files=files)
    monkeypatch.setattr(validator, "MAX_WHEEL_BYTES", wheel.stat().st_size)
    monkeypatch.setattr(validator, "MAX_WHEEL_MEMBERS", len(files) + 1)
    with zipfile.ZipFile(wheel) as archive:
        member_sizes = [member.file_size for member in archive.infolist()]
    monkeypatch.setattr(validator, "MAX_WHEEL_MEMBER_BYTES", max(member_sizes))
    monkeypatch.setattr(validator, "MAX_WHEEL_UNCOMPRESSED_BYTES", sum(member_sizes))

    assert validator.validate_wheel(wheel, VERSION).version == VERSION


def test_zip_preflight_accepts_standard_eocd(validator, tmp_path):
    path = tmp_path / "empty.whl"
    path.write_bytes(zip_eocd())

    validator._preflight_zip(path)


def test_zip_preflight_enforces_entry_count(validator, tmp_path, monkeypatch):
    path = tmp_path / "entries.whl"
    path.write_bytes(zip_eocd(entries=2))
    monkeypatch.setattr(validator, "MAX_WHEEL_MEMBERS", 1)

    with pytest.raises(validator.DistributionError, match="entry count|members|limit"):
        validator._preflight_zip(path)


def test_zip_preflight_enforces_central_directory_size(
    validator, tmp_path, monkeypatch
):
    path = tmp_path / "directory.whl"
    path.write_bytes(zip_eocd(directory_size=2048))
    monkeypatch.setattr(validator, "MAX_WHEEL_CENTRAL_DIRECTORY_BYTES", 1024)

    with pytest.raises(validator.DistributionError, match="central directory|limit"):
        validator._preflight_zip(path)


@pytest.mark.parametrize(
    "eocd",
    [
        zip_eocd(entries=0xFFFF),
        zip_eocd(directory_size=0xFFFFFFFF),
        zip_eocd(directory_offset=0xFFFFFFFF),
    ],
)
def test_zip_preflight_rejects_zip64(validator, tmp_path, eocd):
    path = tmp_path / "zip64.whl"
    path.write_bytes(eocd)

    with pytest.raises(validator.DistributionError, match="ZIP64"):
        validator._preflight_zip(path)


def test_zip_preflight_rejects_missing_eocd(validator, tmp_path):
    path = tmp_path / "invalid.whl"
    path.write_bytes(b"not a zip")

    with pytest.raises(validator.DistributionError, match="EOCD|ZIP"):
        validator._preflight_zip(path)


def test_wheel_preflight_runs_before_zipfile(validator, tmp_path, monkeypatch):
    wheel = write_wheel(tmp_path)
    monkeypatch.setattr(validator, "MAX_WHEEL_MEMBERS", 1)

    def forbidden_zipfile(*args, **kwargs):
        raise AssertionError("ZipFile must not open before central-directory preflight")

    monkeypatch.setattr(validator.zipfile, "ZipFile", forbidden_zipfile)

    with pytest.raises(validator.DistributionError, match="entry count|members|limit"):
        validator.validate_wheel(wheel, VERSION)


def test_wheel_reads_members_without_unbounded_archive_read(
    validator, tmp_path, monkeypatch
):
    wheel = write_wheel(tmp_path)

    def forbidden_read(*args, **kwargs):
        raise AssertionError("ZipFile.read must not be used")

    monkeypatch.setattr(zipfile.ZipFile, "read", forbidden_read)

    assert validator.validate_wheel(wheel, VERSION).version == VERSION


@pytest.mark.parametrize(
    "extra",
    [
        f"{PROJECT_NAME}/case.txt",
        f"{PROJECT_NAME}/caf\u00e9.txt",
        f"{PROJECT_NAME}/trailing space ",
        f"{PROJECT_NAME}/trailing dot.",
        f"{PROJECT_NAME}/C:drive.txt",
        f"{PROJECT_NAME}/COM\u00b9.txt",
        f"{PROJECT_NAME}/LPT\u00b9.txt",
    ],
)
def test_wheel_rejects_casefold_nfc_and_windows_unsafe_names(
    validator, tmp_path, extra
):
    files = wheel_files()
    if extra.endswith("case.txt"):
        files[f"{PROJECT_NAME}/CASE.txt"] = b"collision\n"
    if extra.endswith("caf\u00e9.txt"):
        files[f"{PROJECT_NAME}/cafe\u0301.txt"] = b"collision\n"
    files[extra] = b"unsafe\n"
    wheel = write_wheel(tmp_path, files=files)

    with pytest.raises(ValueError, match="collision|Windows|casefold|NFC"):
        validator.validate_wheel(wheel, VERSION)


def test_wheel_rejects_file_directory_collisions(validator, tmp_path):
    files = wheel_files(
        **{
            f"{PROJECT_NAME}/collision": b"file\n",
            f"{PROJECT_NAME}/collision/child.txt": b"child\n",
        }
    )
    wheel = write_wheel(tmp_path, files=files)

    with pytest.raises(ValueError, match="collision"):
        validator.validate_wheel(wheel, VERSION)


def test_wheel_rejects_windows_83_alias_collisions(validator, tmp_path):
    files = wheel_files(
        **{
            f"{PROJECT_NAME}/README~10.MD": b"alias\n",
            f"{PROJECT_NAME}/README-long.md": b"long\n",
        }
    )
    wheel = write_wheel(tmp_path, files=files)

    with pytest.raises(ValueError, match="8\\.3|alias.*collision"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize(
    ("hash_value", "size_value"),
    [
        ("", "10"),
        ("sha256=not-base64!", "10"),
        ("sha256=" + "A" * 43 + "=", "10"),
        ("sha512=" + "A" * 43, "10"),
        ("sha256=" + "A" * 43, ""),
        ("sha256=" + "A" * 43, "999"),
    ],
)
def test_wheel_rejects_empty_or_incorrect_record_hash_and_size(
    validator, tmp_path, hash_value, size_value
):
    files = wheel_files()
    target = f"{PROJECT_NAME}/__init__.py"
    record = record_with_fields(files, target, hash_value, size_value)
    wheel = write_wheel(
        tmp_path,
        files={**files, f"{DIST_INFO}/RECORD": record},
        record=False,
    )

    with pytest.raises(ValueError, match="RECORD"):
        validator.validate_wheel(wheel, VERSION)


def test_wheel_rejects_content_changed_after_record_creation(validator, tmp_path):
    original = wheel_files()
    files = dict(original)
    target = f"{PROJECT_NAME}/__init__.py"
    files[target] = b"tampered content\n"
    record = record_contents(original)
    wheel = write_wheel(
        tmp_path,
        files={**files, f"{DIST_INFO}/RECORD": record},
        record=False,
    )

    with pytest.raises(ValueError, match="RECORD"):
        validator.validate_wheel(wheel, VERSION)


@pytest.mark.parametrize(
    "relative_path",
    [
        f"{SDIST_ROOT}/pyproject.toml",
        f"{SDIST_ROOT}/PKG-INFO",
        f"{SDIST_ROOT}/README.md",
        f"{SDIST_ROOT}/LICENSE",
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/__init__.py",
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/cli.py",
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/version.py",
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/font_manifest.json",
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/report_schema.json",
    ],
)
def test_sdist_rejects_missing_key_file(validator, tmp_path, relative_path):
    sdist = write_sdist(tmp_path, omit=(relative_path,))

    with pytest.raises(ValueError, match=Path(relative_path).name):
        validator.validate_sdist(sdist, VERSION)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (f"Name: {PROJECT_NAME}", "Name: other-project", "Name"),
        (f"Version: {VERSION}", "Version: 9.9.9", "Version"),
        ("Requires-Python: >=3.14", "Requires-Python: >=3.13", "Requires-Python"),
        ("License-Expression: MIT", "License-Expression: Apache-2.0", "MIT"),
    ],
)
def test_sdist_rejects_incorrect_pkg_info(validator, tmp_path, old, new, message):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(
            **{f"{SDIST_ROOT}/PKG-INFO": PKG_INFO.replace(old.encode(), new.encode())}
        ),
    )

    with pytest.raises(ValueError, match=message):
        validator.validate_sdist(sdist, VERSION)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('requires = ["hatchling==1.33.0"]', 'requires = ["hatchling>=1.33.0"]'),
        ('build-backend = "hatchling.build"', 'build-backend = "other.build"'),
        (f'version = "{VERSION}"', 'version = "9.9.9"'),
        (f'name = "{PROJECT_NAME}"', 'name = "other-project"'),
        (
            f'{PROJECT_NAME} = "{PROJECT_NAME}.cli:main"',
            f'{PROJECT_NAME} = "{PROJECT_NAME}.other:main"',
        ),
    ],
)
def test_sdist_rejects_inconsistent_pyproject(validator, tmp_path, old, new):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(
            **{
                f"{SDIST_ROOT}/pyproject.toml": PYPROJECT.replace(
                    old.encode(), new.encode()
                )
            }
        ),
    )

    with pytest.raises(ValueError, match="pyproject|build-system|Name|Version"):
        validator.validate_sdist(sdist, VERSION)


@pytest.mark.parametrize(
    "pyproject",
    [
        b'build-system = "not-a-table"\n[project]\nname = "markdown2docx"\n',
        b'build-system = []\n[project]\nname = "markdown2docx"\n',
        (
            b'project = "not-a-table"\n[build-system]\n'
            b'requires = ["hatchling==1.33.0"]\n'
            b'build-backend = "hatchling.build"\n'
        ),
        (
            b"project = []\n[build-system]\n"
            b'requires = ["hatchling==1.33.0"]\n'
            b'build-backend = "hatchling.build"\n'
        ),
        (
            b'[build-system]\nrequires = ["hatchling==1.33.0"]\n'
            b'build-backend = "hatchling.build"\n[project]\n'
            b'name = "markdown2docx"\nversion = "0.2.0"\n'
            b'license = "MIT"\nrequires-python = ">=3.14"\n'
            b'scripts = "not-a-table"\n'
        ),
        (
            b'[build-system]\nrequires = ["hatchling==1.33.0"]\n'
            b'build-backend = "hatchling.build"\n[project]\n'
            b'name = "markdown2docx"\nversion = "0.2.0"\n'
            b'license = "MIT"\nrequires-python = ">=3.14"\nscripts = []\n'
        ),
    ],
)
def test_sdist_rejects_non_table_toml_sections(validator, tmp_path, pyproject):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(**{f"{SDIST_ROOT}/pyproject.toml": pyproject}),
    )

    with pytest.raises(validator.DistributionError, match="table|mapping"):
        validator.validate_sdist(sdist, VERSION)


@pytest.mark.parametrize("asset", ["font_manifest.json", "report_schema.json"])
def test_sdist_rejects_invalid_json_asset(validator, tmp_path, asset):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(**{f"{SDIST_ROOT}/src/{PROJECT_NAME}/{asset}": b"{broken"}),
    )

    with pytest.raises(ValueError, match=asset):
        validator.validate_sdist(sdist, VERSION)


@pytest.mark.parametrize(
    "extra",
    [
        f"{SDIST_ROOT}/src/{PROJECT_NAME}/__pycache__/cli.pyc",
        f"{SDIST_ROOT}/.venv/lib/python3.14/site-packages/other.py",
    ],
)
def test_sdist_rejects_cache_or_environment_files(validator, tmp_path, extra):
    sdist = write_sdist(tmp_path, files=sdist_files(**{extra: b"unwanted\n"}))

    with pytest.raises(ValueError, match="unwanted|__pycache__|\\.venv"):
        validator.validate_sdist(sdist, VERSION)


def test_sdist_allows_source_tests(validator, tmp_path):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(
            **{f"{SDIST_ROOT}/tests/test_package.py": b"def test_x(): pass\n"}
        ),
    )

    assert validator.validate_sdist(sdist, VERSION).version == VERSION


def test_sdist_extraction_preserves_the_single_project_root(validator, tmp_path):
    sdist = write_sdist(tmp_path)
    destination = tmp_path / "extracted"

    root = validator.extract_sdist(sdist, destination)

    assert root == destination / SDIST_ROOT
    assert (root / "pyproject.toml").read_bytes() == PYPROJECT
    assert (root / f"src/{PROJECT_NAME}/report_schema.json").is_file()


def test_sdist_physical_size_limit_is_centralized_at_64_mib(validator):
    assert validator.MAX_SDIST_BYTES == 64 * 1024 * 1024


def test_sdist_oversized_file_fails_before_snapshot_open(
    validator, tmp_path, monkeypatch
):
    sdist = write_sdist(tmp_path)
    with sdist.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)

    def forbidden_open(*args, **kwargs):
        raise AssertionError("Oversized sdist must fail before any file open")

    monkeypatch.setattr(validator.Path, "open", forbidden_open)

    with pytest.raises(validator.DistributionError, match="physical|size|limit"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_snapshot_accepts_exact_physical_size_limit(
    validator, tmp_path, monkeypatch
):
    sdist = write_sdist(tmp_path)
    monkeypatch.setattr(validator, "MAX_SDIST_BYTES", sdist.stat().st_size)

    with validator._sdist_snapshot(sdist) as (snapshot, digest):
        assert snapshot.stat().st_size == sdist.stat().st_size
        assert len(digest) == 64


def test_sdist_snapshot_rechecks_fstat_after_copy(validator, tmp_path, monkeypatch):
    sdist = write_sdist(tmp_path)
    monkeypatch.setattr(validator, "MAX_SDIST_BYTES", 1024 * 1024)
    real_fstat = os.fstat
    calls = []

    class OversizedStat:
        st_size = validator.MAX_SDIST_BYTES + 1

    def fake_fstat(file_descriptor):
        calls.append(file_descriptor)
        if len(calls) == 2:
            return OversizedStat()
        return real_fstat(file_descriptor)

    monkeypatch.setattr(validator.os, "fstat", fake_fstat)

    with pytest.raises(validator.DistributionError, match="physical|size|limit"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


@pytest.mark.skipif(
    os.name == "nt", reason="posix_only: POSIX private-directory permission bits"
)
def test_sdist_snapshot_uses_private_temporary_root(validator, tmp_path, monkeypatch):
    real_temporary_directory = tempfile.TemporaryDirectory
    modes = []

    def recording_temporary_directory(*args, **kwargs):
        directory = real_temporary_directory(*args, **kwargs)
        modes.append(Path(directory.name).stat().st_mode & 0o777)
        return directory

    monkeypatch.setattr(
        validator.tempfile, "TemporaryDirectory", recording_temporary_directory
    )
    sdist = write_sdist(tmp_path)

    validator.extract_sdist(sdist, tmp_path / "extracted")

    assert modes == [0o700]


def test_sdist_snapshot_is_unaffected_by_original_path_replacement(
    validator, tmp_path, monkeypatch
):
    sdist = write_sdist(tmp_path)
    original_scan = validator._scan_sdist_archive

    def scan_and_replace(snapshot):
        result = original_scan(snapshot)
        sdist.write_bytes(b"original path replaced")
        return result

    monkeypatch.setattr(validator, "_scan_sdist_archive", scan_and_replace)

    root = validator.extract_sdist(sdist, tmp_path / "extracted")

    assert (root / "pyproject.toml").read_bytes() == PYPROJECT


def test_sdist_snapshot_hash_is_verified(validator, tmp_path, monkeypatch):
    sdist = write_sdist(tmp_path)
    monkeypatch.setattr(validator, "_sha256_file", lambda path: "0" * 64)

    with pytest.raises(validator.DistributionError, match="snapshot|hash"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_snapshot_hash_is_rechecked_after_extraction(
    validator, tmp_path, monkeypatch
):
    sdist = write_sdist(tmp_path)
    original_scan = validator._scan_sdist_archive
    original_extractall = tarfile.TarFile.extractall
    snapshots = []

    def capture_snapshot(snapshot):
        snapshots.append(snapshot)
        return original_scan(snapshot)

    def corrupt_snapshot_after_extract(self, *args, **kwargs):
        result = original_extractall(self, *args, **kwargs)
        snapshots[0].write_bytes(b"snapshot changed after extraction")
        return result

    monkeypatch.setattr(validator, "_scan_sdist_archive", capture_snapshot)
    monkeypatch.setattr(tarfile.TarFile, "extractall", corrupt_snapshot_after_extract)

    with pytest.raises(validator.DistributionError, match="snapshot|hash"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_extraction_rejects_path_traversal(validator, tmp_path):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(**{f"{SDIST_ROOT}/../escape.py": b"escape\n"}),
    )
    destination = tmp_path / "extracted"

    with pytest.raises(ValueError, match="unsafe|member|path"):
        validator.extract_sdist(sdist, destination)
    assert not (tmp_path / "escape.py").exists()


def test_sdist_extraction_rejects_casefold_collisions(validator, tmp_path):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(**{f"{SDIST_ROOT}/readme.md": b"collision\n"}),
    )

    with pytest.raises(ValueError, match="casefold|collision"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_extraction_rejects_unicode_nfc_collisions(validator, tmp_path):
    composed = unicodedata.normalize("NFC", "caf\u00e9.txt")
    decomposed = unicodedata.normalize("NFD", "caf\u00e9.txt")
    assert composed != decomposed
    files = sdist_files(
        **{
            f"{SDIST_ROOT}/{composed}": b"composed\n",
            f"{SDIST_ROOT}/{decomposed}": b"decomposed\n",
        }
    )
    sdist = write_sdist(tmp_path, files=files)

    with pytest.raises(ValueError, match="NFC|collision"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


@pytest.mark.parametrize(
    "name",
    [
        "trailing space ",
        "trailing dot.",
        "nested/trailing space ",
        "nested/trailing dot.",
        "C:drive.txt",
        "nested/C:drive.txt",
        "CON",
        "PRN.txt",
        "AUX",
        "NUL",
        "COM1",
        "COM9.log",
        "COM\u00b9",
        "COM\u00b2.txt",
        "COM\u00b3",
        "LPT1",
        "LPT9.txt",
        "LPT\u00b9",
        "LPT\u00b2.txt",
        "LPT\u00b3",
    ],
)
def test_sdist_extraction_rejects_windows_unsafe_names(validator, tmp_path, name):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(**{f"{SDIST_ROOT}/{name}": b"unsafe\n"}),
    )

    with pytest.raises(ValueError, match="Windows|trailing|colon|device|reserved"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


@pytest.mark.parametrize(
    "name",
    [
        "/absolute.txt",
        f"{SDIST_ROOT}//double-slash.txt",
        f"{SDIST_ROOT}/./dot.txt",
        f"{SDIST_ROOT}/../parent.txt",
        "C:/absolute.txt",
        r"root\absolute.txt",
    ],
)
def test_sdist_extraction_rejects_unsafe_archive_paths(validator, tmp_path, name):
    member, data = file_member(name)
    sdist = write_member_sdist(tmp_path, [(member, data)])

    with pytest.raises(ValueError, match="unsafe|member|path"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


@pytest.mark.parametrize(
    ("member_type", "linkname"),
    [
        (tarfile.SYMTYPE, "../outside"),
        (tarfile.LNKTYPE, f"{SDIST_ROOT}/README.md"),
        (tarfile.CHRTYPE, ""),
        (tarfile.BLKTYPE, ""),
        (tarfile.FIFOTYPE, ""),
    ],
)
def test_sdist_extraction_rejects_special_member_types(
    validator, tmp_path, member_type, linkname
):
    member = tarfile.TarInfo(f"{SDIST_ROOT}/unsafe")
    member.type = member_type
    member.linkname = linkname
    sdist = write_member_sdist(tmp_path, [(member, b"")])

    with pytest.raises(ValueError, match="type|symlink|hardlink|device|FIFO|unsafe"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_extraction_rejects_file_directory_collisions(validator, tmp_path):
    files = sdist_files()
    files[f"{SDIST_ROOT}/collision"] = b"file\n"
    files[f"{SDIST_ROOT}/collision/child.txt"] = b"child\n"
    sdist = write_sdist(tmp_path, files=files)

    with pytest.raises(ValueError, match="collision"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


@pytest.mark.parametrize(
    ("alias", "long_name"),
    [
        ("PYPROJ~1.TOM", "pyproject.toml"),
        ("README~1.MD", "README-long.md"),
        ("CONFIG~2.CON", "configuration-long.conf"),
        ("README~10.MD", "README-long.md"),
        ("PROJEC~1/pyproject.toml", "project-long/pyproject.toml"),
    ],
)
def test_sdist_extraction_rejects_windows_83_alias_collisions(
    validator, tmp_path, alias, long_name
):
    files = sdist_files()
    files[f"{SDIST_ROOT}/{alias}"] = b"alias\n"
    files[f"{SDIST_ROOT}/{long_name}"] = b"long name\n"
    if alias == "PYPROJ~1.TOM":
        files[f"{SDIST_ROOT}/pyproject.toml"] = PYPROJECT
    sdist = write_sdist(tmp_path, files=files)

    with pytest.raises(ValueError, match="8\\.3|alias.*collision"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_extraction_allows_short_names_without_alias_evidence(
    validator, tmp_path
):
    files = sdist_files(
        **{
            f"{SDIST_ROOT}/short.txt": b"short\n",
            f"{SDIST_ROOT}/file~1.txt": b"literal tilde\n",
            f"{SDIST_ROOT}/README~1.MD": b"no long sibling\n",
        }
    )
    sdist = write_sdist(tmp_path, files=files)

    root = validator.extract_sdist(sdist, tmp_path / "extracted")

    assert (root / "file~1.txt").read_bytes() == b"literal tilde\n"
    assert (root / "README~1.MD").read_bytes() == b"no long sibling\n"


def test_sdist_extraction_allows_alias_candidates_in_different_directories(
    validator, tmp_path
):
    files = sdist_files(
        **{
            f"{SDIST_ROOT}/first/PYPROJ~1.TOM": b"alias\n",
            f"{SDIST_ROOT}/second/pyproject.toml": b"different directory\n",
        }
    )
    sdist = write_sdist(tmp_path, files=files)

    root = validator.extract_sdist(sdist, tmp_path / "extracted")

    assert (root / "first/PYPROJ~1.TOM").read_bytes() == b"alias\n"


def test_tar_preflight_accepts_bounded_extension_headers(validator, tmp_path):
    sdist = write_raw_tar(
        tmp_path,
        [
            (f"{SDIST_ROOT}/./@PaxHeader", 3, b"x"),
            (f"{SDIST_ROOT}/file.txt", 0, b"0"),
        ],
    )

    validator._preflight_tar(sdist)


@pytest.mark.parametrize(
    ("constant", "limit", "headers", "message"),
    [
        (
            "MAX_TAR_EXTENSION_MEMBER_BYTES",
            1024,
            [(f"{SDIST_ROOT}/pax", 1025, b"x")],
            "extension|single|limit",
        ),
        (
            "MAX_TAR_EXTENSION_MEMBER_BYTES",
            1024,
            [(f"{SDIST_ROOT}/solaris", 1025, b"X")],
            "extension|single|limit",
        ),
        (
            "MAX_TAR_EXTENSION_BYTES",
            1024,
            [
                (f"{SDIST_ROOT}/pax1", 512, b"x"),
                (f"{SDIST_ROOT}/pax2", 513, b"g"),
            ],
            "extension|total|limit",
        ),
        (
            "MAX_TAR_EXTENSION_BYTES",
            1024,
            [
                (f"{SDIST_ROOT}/solaris1", 512, b"X"),
                (f"{SDIST_ROOT}/solaris2", 513, b"X"),
            ],
            "extension|total|limit",
        ),
        (
            "MAX_TAR_EXTENSION_HEADERS",
            1,
            [
                (f"{SDIST_ROOT}/long1", 1, b"L"),
                (f"{SDIST_ROOT}/long2", 1, b"K"),
            ],
            "extension|count|limit",
        ),
        (
            "MAX_TAR_EXTENSION_HEADERS",
            1,
            [
                (f"{SDIST_ROOT}/solaris1", 1, b"X"),
                (f"{SDIST_ROOT}/solaris2", 1, b"X"),
            ],
            "extension|count|limit",
        ),
        (
            "MAX_TAR_PHYSICAL_HEADERS",
            2,
            [
                (f"{SDIST_ROOT}/one", 0, b"0"),
                (f"{SDIST_ROOT}/two", 0, b"0"),
                (f"{SDIST_ROOT}/three", 0, b"0"),
            ],
            "physical|header|limit",
        ),
        (
            "MAX_TAR_DECLARED_BYTES",
            1024,
            [(f"{SDIST_ROOT}/large", 1025, b"0")],
            "declared|total|limit",
        ),
    ],
)
def test_tar_preflight_rejects_limits_before_tarfile_open(
    validator, tmp_path, monkeypatch, constant, limit, headers, message
):
    sdist = write_raw_tar(tmp_path, headers)
    monkeypatch.setattr(validator, constant, limit)

    def forbidden_tarfile(*args, **kwargs):
        raise AssertionError("tarfile.open must not run before raw TAR preflight")

    monkeypatch.setattr(validator.tarfile, "open", forbidden_tarfile)

    with pytest.raises(validator.DistributionError, match=message):
        validator.validate_sdist(sdist, VERSION)


@pytest.mark.parametrize("operation", ["validate", "extract"])
def test_sdist_never_materializes_members_with_getmembers(
    validator, tmp_path, monkeypatch, operation
):
    def forbidden_getmembers(self):
        raise AssertionError("TarFile.getmembers must not be used")

    monkeypatch.setattr(tarfile.TarFile, "getmembers", forbidden_getmembers)
    sdist = write_sdist(tmp_path)

    if operation == "validate":
        assert validator.validate_sdist(sdist, VERSION).version == VERSION
    else:
        assert validator.extract_sdist(sdist, tmp_path / "extracted").is_dir()


def test_sdist_member_reads_are_bounded(validator, tmp_path, monkeypatch):
    original_read = tarfile.ExFileObject.read

    def bounded_read(self, size=-1):
        assert 0 <= size <= 1024 * 1024
        return original_read(self, size)

    monkeypatch.setattr(tarfile.ExFileObject, "read", bounded_read)
    sdist = write_sdist(tmp_path)

    assert validator.validate_sdist(sdist, VERSION).version == VERSION


def test_sdist_enforces_single_member_size_limit(validator, tmp_path, monkeypatch):
    contents = sdist_files()
    monkeypatch.setattr(
        validator,
        "MAX_SDIST_MEMBER_BYTES",
        max(len(data) for data in contents.values()) - 1,
    )
    sdist = write_sdist(tmp_path, files=contents)

    with pytest.raises(ValueError, match="member|size|limit"):
        validator.validate_sdist(sdist, VERSION)


def test_sdist_extraction_enforces_entry_count_limit(validator, tmp_path, monkeypatch):
    contents = sdist_files()
    monkeypatch.setattr(validator, "MAX_SDIST_MEMBERS", len(contents) - 1)
    sdist = write_sdist(tmp_path, files=contents)

    with pytest.raises(ValueError, match="entry count|members|limit"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_extraction_enforces_total_size_limit(validator, tmp_path, monkeypatch):
    contents = sdist_files()
    total_size = sum(len(data) for data in contents.values())
    monkeypatch.setattr(validator, "MAX_SDIST_UNCOMPRESSED_BYTES", total_size - 1)
    sdist = write_sdist(tmp_path, files=contents)

    with pytest.raises(ValueError, match="total size|bytes|limit"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_extraction_accepts_exact_resource_limits(
    validator, tmp_path, monkeypatch
):
    contents = sdist_files()
    monkeypatch.setattr(validator, "MAX_SDIST_MEMBERS", len(contents))
    monkeypatch.setattr(
        validator,
        "MAX_SDIST_UNCOMPRESSED_BYTES",
        sum(len(data) for data in contents.values()),
    )
    sdist = write_sdist(tmp_path, files=contents)

    root = validator.extract_sdist(sdist, tmp_path / "extracted")

    assert (root / "pyproject.toml").read_bytes() == PYPROJECT


def test_sdist_extraction_uses_tarfile_data_filter(validator, tmp_path, monkeypatch):
    original_filter = tarfile.data_filter
    filtered = []

    def record_filter(member, path):
        filtered.append(member.name)
        return original_filter(member, path)

    monkeypatch.setattr(validator.tarfile, "data_filter", record_filter)
    sdist = write_sdist(tmp_path)

    validator.extract_sdist(sdist, tmp_path / "extracted")

    assert filtered == list(sdist_files())


@pytest.mark.parametrize("same_size", [False, True])
def test_sdist_extraction_detects_post_extraction_tampering(
    validator, tmp_path, monkeypatch, same_size
):
    original_extractall = tarfile.TarFile.extractall
    original = b"# Synthetic distribution\n"
    tampered = b"X" * len(original) if same_size else b"tampered\n"

    def tamper_after_extract(self, *args, **kwargs):
        result = original_extractall(self, *args, **kwargs)
        path = args[0] if args else kwargs["path"]
        (Path(path) / SDIST_ROOT / "README.md").write_bytes(tampered)
        return result

    monkeypatch.setattr(tarfile.TarFile, "extractall", tamper_after_extract)
    sdist = write_sdist(tmp_path)

    with pytest.raises(ValueError, match="SHA-256|size|content|mismatch"):
        validator.extract_sdist(sdist, tmp_path / "extracted")


def test_sdist_extraction_rejects_preexisting_root_symlink(validator, tmp_path):
    destination = tmp_path / "extracted"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (destination / SDIST_ROOT).symlink_to(outside, target_is_directory=True)
    sdist = write_sdist(tmp_path)

    with pytest.raises(ValueError, match="exists|root|path"):
        validator.extract_sdist(sdist, destination)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_empty_artifact_is_rejected(validator, tmp_path, kind):
    suffix = ".whl" if kind == "wheel" else ".tar.gz"
    path = tmp_path / f"empty{suffix}"
    path.write_bytes(b"")
    check = validator.validate_wheel if kind == "wheel" else validator.validate_sdist

    with pytest.raises(ValueError, match="empty|artifact"):
        check(path, VERSION)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_corrupt_artifact_is_rejected(validator, tmp_path, kind):
    suffix = ".whl" if kind == "wheel" else ".tar.gz"
    path = tmp_path / f"corrupt{suffix}"
    path.write_bytes(b"not a valid archive")
    check = validator.validate_wheel if kind == "wheel" else validator.validate_sdist

    with pytest.raises(ValueError, match="wheel|sdist|archive|artifact"):
        check(path, VERSION)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_missing_artifact_is_rejected(validator, tmp_path, kind):
    suffix = ".whl" if kind == "wheel" else ".tar.gz"
    check = validator.validate_wheel if kind == "wheel" else validator.validate_sdist

    with pytest.raises(ValueError, match="missing|artifact"):
        check(tmp_path / f"missing{suffix}", VERSION)


def test_distribution_directory_requires_exactly_one_of_each(validator, tmp_path):
    write_complete_distribution(tmp_path)
    write_wheel(tmp_path, filename=f"{PROJECT_NAME}-{VERSION}-1-py3-none-any.whl")

    with pytest.raises(ValueError, match="exactly one.*wheel"):
        validator.validate_distribution_directory(tmp_path, VERSION)


@pytest.mark.skipif(
    os.name == "nt",
    reason="posix_only: POSIX process sessions are not supported on Windows",
)
def test_run_starts_a_new_posix_process_session(validator, tmp_path, monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        def __init__(self, command, **kwargs):
            self.args = command
            captured.update(kwargs)

        def communicate(self, input=None, timeout=None):
            return "ok", ""

        def kill(self):
            self.returncode = -9

        def poll(self):
            return self.returncode

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(validator.subprocess, "Popen", FakeProcess)

    result = validator._run(
        [sys.executable, "-c", "print('ok')"], cwd=tmp_path, timeout=5
    )

    assert result.stdout == "ok"
    assert captured["start_new_session"] is True
    assert captured["shell"] is False


def test_windows_cleanup_uses_taskkill_tree_and_bounded_wait(validator, monkeypatch):
    commands = []
    waits = []

    class FakeProcess:
        pid = 4321
        returncode = None

        def wait(self, timeout=None):
            waits.append(timeout)
            self.returncode = 0
            return 0

    def fake_run(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] == validator.PROCESS_TERMINATION_TIMEOUT
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(validator.subprocess, "run", fake_run)

    validator._terminate_process_tree(FakeProcess(), windows=True)

    assert commands == [["taskkill", "/PID", "4321", "/T", "/F"]]
    assert waits == [validator.PROCESS_TERMINATION_TIMEOUT]


def test_run_cleans_up_process_tree_on_cancellation(validator, tmp_path, monkeypatch):
    cleaned = []

    class CancelledProcess:
        returncode = None

        def __init__(self, command, **kwargs):
            self.args = command

        def communicate(self, input=None, timeout=None):
            raise KeyboardInterrupt

        def kill(self):
            self.returncode = -9

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(validator.subprocess, "Popen", CancelledProcess)
    monkeypatch.setattr(
        validator,
        "_terminate_process_tree",
        lambda process, *, windows: cleaned.append(process),
    )

    with pytest.raises(KeyboardInterrupt):
        validator._run([sys.executable, "-c", "pass"], cwd=tmp_path, timeout=5)

    assert len(cleaned) == 1


@pytest.mark.skipif(
    os.name == "nt", reason="posix_only: POSIX process-group descendant check"
)
def test_run_timeout_kills_real_descendant_processes(validator, tmp_path):
    marker = tmp_path / "descendant-survived"
    child_code = (
        "import pathlib,time; "
        f"time.sleep(2); pathlib.Path({str(marker)!r}).write_text('survived')"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(60)"
    )

    with pytest.raises(validator.DistributionError, match="timed out"):
        validator._run([sys.executable, "-c", parent_code], cwd=tmp_path, timeout=0.5)

    time.sleep(2.2)
    assert not marker.exists()


def orchestration_dependencies(validator, tmp_path, events, fail_event=None):
    wheel = tmp_path / "published.whl"
    sdist = tmp_path / "published.tar.gz"
    rebuilt = tmp_path / "rebuilt.whl"
    artifacts = validator.DistributionArtifacts(
        wheel=validator.WheelInfo(
            wheel, VERSION, {PROJECT_NAME: validator.CONSOLE_TARGET}
        ),
        sdist=validator.SdistInfo(sdist, VERSION),
    )
    temporary_directories = []

    def record(name):
        events.append(name)
        if name == fail_event:
            raise validator.DistributionError(f"injected failure: {name}")

    def temporary_directory(*, prefix):
        directory = tempfile.TemporaryDirectory(prefix=prefix)
        temporary_directories.append(directory)
        return directory

    def validate_distribution_directory(directory, expected_version):
        record("validate-distribution")
        return artifacts

    def install_and_smoke(*args, **kwargs):
        record(f"install-smoke:{kwargs['conversion']}")

    def extract_sdist(path, destination):
        record("extract-sdist")
        return tmp_path / "source"

    def run(*args, **kwargs):
        record("run-rebuild")
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    def select_artifact(directory, suffix, label):
        record("select-rebuilt")
        return rebuilt

    def validate_wheel(path, expected_version):
        record("validate-wheel")
        return validator.WheelInfo(
            path, expected_version, {PROJECT_NAME: validator.CONSOLE_TARGET}
        )

    dependencies = validator.DistributionDependencies(
        validate_distribution_directory=validate_distribution_directory,
        find_uv=lambda command: str(tmp_path / "uv"),
        temporary_directory=temporary_directory,
        install_and_smoke=install_and_smoke,
        extract_sdist=extract_sdist,
        run=run,
        select_artifact=select_artifact,
        validate_wheel=validate_wheel,
    )
    return dependencies, temporary_directories


def test_main_orchestrates_every_distribution_step_and_cleans_workspace(
    validator, tmp_path
):
    events = []
    dependencies, temporary_directories = orchestration_dependencies(
        validator, tmp_path, events
    )

    result = validator.main(
        [
            "--dist-dir",
            str(tmp_path / "dist"),
            "--expected-version",
            VERSION,
            "--uv",
            str(tmp_path / "uv"),
        ],
        dependencies=dependencies,
    )

    assert result == 0
    assert events == [
        "validate-distribution",
        "install-smoke:True",
        "extract-sdist",
        "run-rebuild",
        "select-rebuilt",
        "validate-wheel",
        "install-smoke:False",
    ]
    assert len(temporary_directories) == 1
    assert not Path(temporary_directories[0].name).exists()


def test_main_can_skip_sdist_rebuild_on_non_linux_platforms(validator, tmp_path):
    events = []
    dependencies, temporary_directories = orchestration_dependencies(
        validator, tmp_path, events
    )

    result = validator.main(
        [
            "--dist-dir",
            str(tmp_path / "dist"),
            "--expected-version",
            VERSION,
            "--uv",
            str(tmp_path / "uv"),
            "--skip-sdist-rebuild",
        ],
        dependencies=dependencies,
    )

    assert result == 0
    assert events == ["validate-distribution", "install-smoke:True"]
    assert all(not Path(directory.name).exists() for directory in temporary_directories)


def test_main_validate_only_skips_install_and_rebuild(validator, tmp_path):
    events = []
    dependencies, temporary_directories = orchestration_dependencies(
        validator, tmp_path, events
    )

    result = validator.main(
        [
            "--dist-dir",
            str(tmp_path / "dist"),
            "--expected-version",
            VERSION,
            "--validate-only",
        ],
        dependencies=dependencies,
    )

    assert result == 0
    assert events == ["validate-distribution"]
    assert temporary_directories == []


@pytest.mark.parametrize(
    "fail_event",
    [
        "validate-distribution",
        "install-smoke:True",
        "extract-sdist",
        "run-rebuild",
        "select-rebuilt",
        "validate-wheel",
        "install-smoke:False",
    ],
)
def test_main_fails_and_cleans_workspace_when_any_step_fails(
    validator, tmp_path, fail_event
):
    events = []
    dependencies, temporary_directories = orchestration_dependencies(
        validator, tmp_path, events, fail_event=fail_event
    )

    result = validator.main(
        [
            "--dist-dir",
            str(tmp_path / "dist"),
            "--expected-version",
            VERSION,
            "--uv",
            str(tmp_path / "uv"),
        ],
        dependencies=dependencies,
    )

    assert result == 1
    assert events[-1] == fail_event
    assert all(not Path(directory.name).exists() for directory in temporary_directories)


def test_project_version_comes_from_pyproject(validator, tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_bytes(PYPROJECT)

    assert validator.project_version(project) == VERSION


def test_project_version_rejects_non_table_project(validator, tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text('project = "not-a-table"\n', encoding="utf-8")

    with pytest.raises(validator.DistributionError, match="table|mapping"):
        validator.project_version(project)


def test_sdist_rebuild_uses_only_the_wheel_target(validator, tmp_path):
    uv = tmp_path / "uv"
    command = validator.sdist_rebuild_command(uv, tmp_path / "rebuilt")

    assert command == [
        str(uv),
        "build",
        "--wheel",
        "--out-dir",
        str(tmp_path / "rebuilt"),
    ]


def test_pip_install_command_uses_locked_constraints(validator, tmp_path):
    python = tmp_path / "venv" / "bin" / "python"
    wheel = tmp_path / "package.whl"
    constraints = tmp_path / "constraints.txt"

    assert validator.pip_install_command(python, wheel, constraints) == [
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--constraint",
        str(constraints),
        str(wheel),
    ]


def test_pip_install_command_without_constraints(validator, tmp_path):
    python = tmp_path / "python"
    wheel = tmp_path / "package.whl"

    assert validator.pip_install_command(python, wheel) == [
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        str(wheel),
    ]


@pytest.mark.parametrize(
    ("windows", "relative"),
    [
        (False, "bin/python"),
        (True, "Scripts/python.exe"),
    ],
)
def test_venv_interpreter_path(validator, tmp_path, windows, relative):
    assert validator.venv_python_path(tmp_path, windows=windows) == (
        tmp_path / relative
    )


@pytest.mark.parametrize(
    ("windows", "filename"),
    [(False, "markdown2docx"), (True, "markdown2docx.exe")],
)
def test_console_script_path(validator, tmp_path, windows, filename):
    assert (
        validator.console_script_path(tmp_path, windows=windows) == tmp_path / filename
    )


def test_console_version_must_match_expected_version(validator):
    validator.check_version_output(f"{PROJECT_NAME} {VERSION}\n", VERSION)

    with pytest.raises(ValueError, match="version"):
        validator.check_version_output(f"{PROJECT_NAME} 9.9.9\n", VERSION)


def test_import_probe_requires_venv_site_packages(validator, tmp_path):
    venv = tmp_path / "venv"
    purelib = venv / "lib" / "python3.14" / "site-packages"
    package = purelib / PROJECT_NAME / "__init__.py"
    scripts = venv / "bin"
    probe = {
        "version": VERSION,
        "package_path": str(package),
        "purelib": str(purelib),
        "scripts": str(scripts),
    }

    validator.check_import_probe(probe, venv, VERSION)

    probe["package_path"] = str(REPO_ROOT / "src" / PROJECT_NAME / "__init__.py")
    with pytest.raises(ValueError, match="site-packages"):
        validator.check_import_probe(probe, venv, VERSION)


def test_import_probe_rejects_version_mismatch(validator, tmp_path):
    venv = tmp_path / "venv"
    purelib = venv / "lib" / "python3.14" / "site-packages"
    probe = {
        "version": "9.9.9",
        "package_path": str(purelib / PROJECT_NAME / "__init__.py"),
        "purelib": str(purelib),
        "scripts": str(venv / "bin"),
    }

    with pytest.raises(ValueError, match="version"):
        validator.check_import_probe(probe, venv, VERSION)


def test_conversion_report_requires_integrity_and_output(validator, tmp_path):
    output = tmp_path / "input.docx"
    output.write_bytes(b"DOCX placeholder")
    report = json.dumps({"checks": {"text_integrity": "passed"}})

    validator.check_conversion_report(report, output)

    with pytest.raises(ValueError, match="text_integrity"):
        validator.check_conversion_report(
            json.dumps({"checks": {"text_integrity": "failed"}}), output
        )
    output.unlink()
    with pytest.raises(ValueError, match="DOCX|output"):
        validator.check_conversion_report(report, output)


def load_workflow(filename):
    return yaml.load(
        (REPO_ROOT / ".github" / "workflows" / filename).read_text(),
        Loader=yaml.BaseLoader,
    )


def test_build_backend_requirement_is_exactly_pinned():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert project["build-system"] == {
        "requires": ["hatchling==1.33.0"],
        "build-backend": "hatchling.build",
    }


@pytest.mark.parametrize(
    ("filename", "job_id", "step_id", "dist_dir"),
    [
        ("test.yml", "test", "wheel-validation", "artifacts/dist"),
        ("release.yml", "build", "verify-distributions", "dist"),
    ],
)
def test_workflows_delegate_complete_distribution_validation(
    filename, job_id, step_id, dist_dir
):
    workflow = load_workflow(filename)
    step = next(
        step for step in workflow["jobs"][job_id]["steps"] if step.get("id") == step_id
    )

    assert f"scripts/validate_wheel.py --dist-dir {dist_dir}" in step["run"]
    assert "*.tar.gz" not in step["run"]
    assert "uv pip install" not in step["run"]


def test_release_validator_checks_the_tag_version():
    workflow = load_workflow("release.yml")
    step = next(
        step
        for step in workflow["jobs"]["build"]["steps"]
        if step.get("id") == "verify-distributions"
    )

    assert '--expected-version "${RELEASE_REF#v}"' in step["run"]
    assert "--validate-only" in step["run"]
    assert step["env"]["RELEASE_REF"] == "${{ inputs.release_ref }}"
