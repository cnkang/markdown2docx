#!/usr/bin/env python3
"""Validate distribution contents, installed entry points, and sdist rebuilds."""

import argparse
import configparser
import csv
import io
import json
import os
import shutil
import stat
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
import tomllib
import unicodedata
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath

PROJECT_NAME = "markdown2docx"
CONSOLE_SCRIPT = "markdown2docx"
CONSOLE_TARGET = "markdown2docx.cli:main"
REQUIRES_PYTHON = ">=3.14"
LICENSE_EXPRESSION = "MIT"
BUILD_REQUIRES = ["hatchling==1.33.0"]
BUILD_BACKEND = "hatchling.build"
MAX_SDIST_MEMBERS = 10_000
MAX_SDIST_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
REQUIRED_PACKAGE_FILES = (
    "__init__.py",
    "cli.py",
    "version.py",
    "font_manifest.json",
    "report_schema.json",
)
REQUIRED_JSON_ASSETS = ("font_manifest.json", "report_schema.json")
REQUIRED_SDIST_FILES = (
    "pyproject.toml",
    "PKG-INFO",
    "README.md",
    "LICENSE",
    *(f"src/{PROJECT_NAME}/{name}" for name in REQUIRED_PACKAGE_FILES),
)
IMPORT_PROBE = """
import importlib.metadata
import json
import sysconfig
from importlib.resources import files
from pathlib import Path

import markdown2docx

package = Path(markdown2docx.__file__).resolve()
assets = {}
for name in ("font_manifest.json", "report_schema.json"):
    value = json.loads(files("markdown2docx").joinpath(name).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise RuntimeError(f"Invalid packaged JSON asset: {name}")
    assets[name] = value
print(json.dumps({
    "version": importlib.metadata.version("markdown2docx"),
    "package_path": str(package),
    "purelib": str(Path(sysconfig.get_path("purelib")).resolve()),
    "scripts": str(Path(sysconfig.get_path("scripts")).resolve()),
    "assets": assets,
}))
"""


class DistributionError(ValueError):
    """A distribution artifact or its installed smoke check is invalid."""


@dataclass(frozen=True)
class WheelInfo:
    path: Path
    version: str
    console_scripts: dict[str, str]


@dataclass(frozen=True)
class SdistInfo:
    path: Path
    version: str


@dataclass(frozen=True)
class DistributionArtifacts:
    wheel: WheelInfo
    sdist: SdistInfo


def _require_artifact(path: Path, label: str) -> None:
    try:
        if not path.is_file():
            raise DistributionError(f"Missing {label} artifact: {path}")
        if path.stat().st_size == 0:
            raise DistributionError(f"Empty {label} artifact: {path}")
    except OSError as error:
        raise DistributionError(
            f"Unable to read {label} artifact {path}: {error}"
        ) from error


def _safe_member_name(name: str) -> PurePosixPath:
    normalized = name.rstrip("/")
    parts = normalized.split("/")
    if (
        not normalized
        or "\\" in normalized
        or "\x00" in normalized
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or ":" in parts[0]
    ):
        raise DistributionError(f"Unsafe archive member path: {name!r}")
    return PurePosixPath(normalized)


def _sdist_member_path(name: str) -> PurePosixPath:
    path = _safe_member_name(name)
    for part in path.parts:
        if part.endswith((" ", ".")):
            raise DistributionError(
                f"Unsafe Windows trailing space or dot in sdist member: {name!r}"
            )
        if ":" in part:
            raise DistributionError(f"Unsafe Windows colon in sdist member: {name!r}")
        device_name = part.split(".", 1)[0].upper()
        if device_name in WINDOWS_DEVICE_NAMES:
            raise DistributionError(
                f"Unsafe Windows reserved device name in sdist member: {name!r}"
            )
    return path


def _validate_sdist_members(members: Sequence[tarfile.TarInfo]) -> None:
    if len(members) > MAX_SDIST_MEMBERS:
        raise DistributionError(
            f"Sdist exceeds the entry count limit: {len(members)} > {MAX_SDIST_MEMBERS}"
        )
    total_size = 0
    identities = {}
    normalized_names = {}
    for member in members:
        path = _sdist_member_path(member.name)
        identity = str(path)
        if identity in identities:
            raise DistributionError(f"Duplicate sdist member path: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise DistributionError(f"Unsafe sdist member type: {member.name}")
        if member.size < 0:
            raise DistributionError(f"Unsafe negative sdist member size: {member.name}")
        if member.isfile():
            total_size += member.size
        identities[identity] = member
        normalized = unicodedata.normalize("NFC", identity).casefold()
        if normalized in normalized_names:
            raise DistributionError(
                "Sdist member collision after casefold/NFC normalization: "
                f"{normalized_names[normalized]!r} and {identity!r}"
            )
        normalized_names[normalized] = identity
    if total_size > MAX_SDIST_UNCOMPRESSED_BYTES:
        raise DistributionError(
            "Sdist exceeds the total uncompressed size limit: "
            f"{total_size} > {MAX_SDIST_UNCOMPRESSED_BYTES}"
        )
    for normalized in normalized_names:
        parts = normalized.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            original_parent = normalized_names.get(parent)
            if original_parent is not None and not identities[original_parent].isdir():
                raise DistributionError(
                    "Sdist file/directory collision: "
                    f"{original_parent!r} and {normalized_names[normalized]!r}"
                )


def _reject_unwanted_members(names: Sequence[str], *, wheel: bool) -> None:
    forbidden_parts = {
        "__pycache__",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    if wheel:
        forbidden_parts.add("tests")
    for name in names:
        path = PurePosixPath(name)
        if forbidden_parts.intersection(path.parts) or path.suffix in {".pyc", ".pyo"}:
            raise DistributionError(f"Unwanted development file in artifact: {name}")


def _read_wheel(path: Path) -> dict[str, bytes]:
    _require_artifact(path, "wheel")
    if path.suffix != ".whl":
        raise DistributionError(f"Expected a .whl artifact: {path}")
    files = {}
    seen = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                _safe_member_name(member.filename)
                if member.filename in seen:
                    raise DistributionError(
                        f"Duplicate wheel member path: {member.filename}"
                    )
                seen.add(member.filename)
                if member.flag_bits & 1:
                    raise DistributionError(
                        f"Encrypted wheel member is not allowed: {member.filename}"
                    )
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise DistributionError(
                        f"Wheel member must not be a symlink: {member.filename}"
                    )
                if not member.is_dir():
                    files[member.filename] = archive.read(member)
    except DistributionError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise DistributionError(f"Invalid wheel archive {path}: {error}") from error
    if not files:
        raise DistributionError(f"Wheel artifact has no files: {path}")
    return files


def _read_sdist(path: Path) -> dict[str, bytes]:
    _require_artifact(path, "sdist")
    if not path.name.endswith(".tar.gz"):
        raise DistributionError(f"Expected a .tar.gz sdist artifact: {path}")
    files = {}
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            _validate_sdist_members(members)
            for member in members:
                if member.isfile():
                    identity = str(_sdist_member_path(member.name))
                    source = archive.extractfile(member)
                    if source is None:
                        raise DistributionError(
                            f"Unable to read sdist member: {member.name}"
                        )
                    files[identity] = source.read()
    except DistributionError:
        raise
    except (EOFError, OSError, tarfile.TarError) as error:
        raise DistributionError(f"Invalid sdist archive {path}: {error}") from error
    if not files:
        raise DistributionError(f"Sdist artifact has no files: {path}")
    return files


def _parse_metadata(data: bytes, label: str):
    message = BytesParser(policy=default).parsebytes(data)
    if message.defects:
        raise DistributionError(f"Invalid {label}: {message.defects}")
    return message


def _validate_metadata(message, expected_version: str, label: str) -> None:
    name = str(message.get("Name", "")).strip()
    if name.replace("_", "-").lower() != PROJECT_NAME:
        raise DistributionError(f"{label} Name must be {PROJECT_NAME!r}, got {name!r}")
    version = str(message.get("Version", "")).strip()
    if version != expected_version:
        raise DistributionError(
            f"{label} Version must be {expected_version!r}, got {version!r}"
        )
    requires_python = str(message.get("Requires-Python", "")).strip()
    if requires_python != REQUIRES_PYTHON:
        raise DistributionError(
            f"{label} Requires-Python must be {REQUIRES_PYTHON!r}, "
            f"got {requires_python!r}"
        )
    license_expression = str(
        message.get("License-Expression", message.get("License", ""))
    ).strip()
    if license_expression != LICENSE_EXPRESSION:
        raise DistributionError(
            f"{label} license must be {LICENSE_EXPRESSION!r}, "
            f"got {license_expression!r}"
        )
    if "LICENSE" not in {
        str(item).strip() for item in message.get_all("License-File", [])
    }:
        raise DistributionError(f"{label} must declare License-File: LICENSE")


def _validate_license(data: bytes, label: str) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DistributionError(f"{label} LICENSE is not UTF-8") from error
    if "MIT License" not in text or "Permission is hereby granted" not in text:
        raise DistributionError(f"{label} LICENSE is missing or truncated")


def _validate_json_asset(data: bytes, name: str, label: str) -> None:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DistributionError(f"{label} {name} is not valid JSON: {error}") from error
    if not isinstance(value, dict) or not value:
        raise DistributionError(f"{label} {name} must be a non-empty JSON object")


def _validate_record(files: Mapping[str, bytes], record_path: str) -> None:
    if record_path not in files:
        raise DistributionError(f"Wheel RECORD is missing: {record_path}")
    try:
        rows = list(
            csv.reader(io.StringIO(files[record_path].decode("utf-8")), strict=True)
        )
    except (UnicodeDecodeError, csv.Error) as error:
        raise DistributionError(f"Wheel RECORD is invalid: {error}") from error
    if rows and rows[0] == ["path", "hash", "size"]:
        rows = rows[1:]
    if not rows or any(len(row) != 3 for row in rows):
        raise DistributionError("Wheel RECORD has invalid inventory rows")
    recorded = [row[0] for row in rows]
    if len(recorded) != len(set(recorded)) or set(recorded) != set(files):
        raise DistributionError("Wheel RECORD does not match the wheel inventory")


def validate_wheel(path: Path, expected_version: str) -> WheelInfo:
    """Validate a wheel's inventory, metadata, entry point, license, and assets."""
    path = Path(path)
    files = _read_wheel(path)
    if not path.name.startswith(f"{PROJECT_NAME}-{expected_version}-"):
        raise DistributionError(
            f"Wheel filename does not match {PROJECT_NAME} {expected_version}: {path.name}"
        )
    _reject_unwanted_members(tuple(files), wheel=True)
    for name in REQUIRED_PACKAGE_FILES:
        required = f"{PROJECT_NAME}/{name}"
        if required not in files:
            raise DistributionError(
                f"Wheel is missing required package file: {required}"
            )

    dist_info = f"{PROJECT_NAME}-{expected_version}.dist-info"
    dist_infos = {
        PurePosixPath(name).parts[0]
        for name in files
        if PurePosixPath(name).parts[0].endswith(".dist-info")
    }
    if dist_infos != {dist_info}:
        raise DistributionError(
            f"Wheel must contain exactly one matching dist-info directory: {dist_info}"
        )

    metadata_path = f"{dist_info}/METADATA"
    if metadata_path not in files:
        raise DistributionError(f"Wheel METADATA is missing: {metadata_path}")
    metadata = _parse_metadata(files[metadata_path], "wheel METADATA")
    _validate_metadata(metadata, expected_version, "Wheel METADATA")

    wheel_metadata_path = f"{dist_info}/WHEEL"
    if wheel_metadata_path not in files:
        raise DistributionError(
            f"Wheel WHEEL metadata is missing: {wheel_metadata_path}"
        )
    wheel_metadata = _parse_metadata(files[wheel_metadata_path], "wheel WHEEL metadata")
    if str(wheel_metadata.get("Root-Is-Purelib", "")).lower() != "true":
        raise DistributionError("Wheel Root-Is-Purelib must be true")
    if str(wheel_metadata.get("Tag", "")) != "py3-none-any":
        raise DistributionError("Wheel Tag must be py3-none-any")

    entry_points_path = f"{dist_info}/entry_points.txt"
    if entry_points_path not in files:
        raise DistributionError(
            f"Wheel entry_points.txt is missing: {entry_points_path}"
        )
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(files[entry_points_path].decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error) as error:
        raise DistributionError(
            f"Wheel entry_points.txt is invalid: {error}"
        ) from error
    if not parser.has_section("console_scripts"):
        raise DistributionError(
            "Wheel entry_points.txt has no console_scripts section; expected "
            f"{CONSOLE_SCRIPT} = {CONSOLE_TARGET}"
        )
    console_scripts = dict(parser.items("console_scripts"))
    if console_scripts.get(CONSOLE_SCRIPT) != CONSOLE_TARGET:
        raise DistributionError(
            f"Wheel console script must be {CONSOLE_SCRIPT} = {CONSOLE_TARGET}"
        )
    module = CONSOLE_TARGET.partition(":")[0].replace(".", "/")
    if f"{module}.py" not in files:
        raise DistributionError(
            f"Wheel console entry point module is missing: {module}"
        )

    license_path = f"{dist_info}/licenses/LICENSE"
    if license_path not in files:
        raise DistributionError(f"Wheel LICENSE is missing: {license_path}")
    _validate_license(files[license_path], "Wheel")
    for name in REQUIRED_JSON_ASSETS:
        asset_path = f"{PROJECT_NAME}/{name}"
        _validate_json_asset(files[asset_path], name, "Wheel")
    _validate_record(files, f"{dist_info}/RECORD")
    return WheelInfo(
        path=path, version=expected_version, console_scripts=console_scripts
    )


def _validate_pyproject(data: bytes, expected_version: str) -> None:
    try:
        project = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DistributionError(f"Sdist pyproject.toml is invalid: {error}") from error
    build_system = project.get("build-system", {})
    if build_system.get("requires") != BUILD_REQUIRES:
        raise DistributionError(
            f"Sdist build-system.requires must be {BUILD_REQUIRES!r}"
        )
    if build_system.get("build-backend") != BUILD_BACKEND:
        raise DistributionError(
            f"Sdist build-system.build-backend must be {BUILD_BACKEND!r}"
        )
    metadata = project.get("project", {})
    if metadata.get("name") != PROJECT_NAME:
        raise DistributionError("Sdist pyproject.toml project Name is incorrect")
    if metadata.get("version") != expected_version:
        raise DistributionError("Sdist pyproject.toml project Version is incorrect")
    if metadata.get("requires-python") != REQUIRES_PYTHON:
        raise DistributionError("Sdist pyproject.toml Requires-Python is incorrect")
    if metadata.get("license") != LICENSE_EXPRESSION:
        raise DistributionError("Sdist pyproject.toml license must be MIT")
    scripts = metadata.get("scripts", {})
    if scripts.get(CONSOLE_SCRIPT) != CONSOLE_TARGET:
        raise DistributionError(
            f"Sdist pyproject.toml must define {CONSOLE_SCRIPT} = {CONSOLE_TARGET}"
        )


def validate_sdist(path: Path, expected_version: str) -> SdistInfo:
    """Validate the source archive's identity, build metadata, and key files."""
    path = Path(path)
    files = _read_sdist(path)
    root_name = f"{PROJECT_NAME}-{expected_version}"
    if path.name != f"{root_name}.tar.gz":
        raise DistributionError(
            f"Sdist filename does not match {PROJECT_NAME} {expected_version}: {path.name}"
        )
    roots = {PurePosixPath(name).parts[0] for name in files}
    if roots != {root_name}:
        raise DistributionError(f"Sdist must contain one project root: {root_name}")
    _reject_unwanted_members(tuple(files), wheel=False)
    for relative_path in REQUIRED_SDIST_FILES:
        required = f"{root_name}/{relative_path}"
        if required not in files:
            raise DistributionError(f"Sdist is missing key file: {relative_path}")

    metadata = _parse_metadata(files[f"{root_name}/PKG-INFO"], "sdist PKG-INFO")
    _validate_metadata(metadata, expected_version, "Sdist PKG-INFO")
    _validate_pyproject(files[f"{root_name}/pyproject.toml"], expected_version)
    _validate_license(files[f"{root_name}/LICENSE"], "Sdist")
    for name in REQUIRED_JSON_ASSETS:
        asset_path = f"{root_name}/src/{PROJECT_NAME}/{name}"
        _validate_json_asset(files[asset_path], name, "Sdist")
    return SdistInfo(path=path, version=expected_version)


def _sdist_target(root: Path, member_name: str) -> Path:
    relative = _sdist_member_path(member_name).parts[1:]
    target = root.joinpath(*relative)
    if not target.resolve().is_relative_to(root.resolve()):
        raise DistributionError(
            f"Sdist extraction target resolves outside its root: {member_name!r}"
        )
    return target


def extract_sdist(path: Path, destination: Path) -> Path:
    """Safely extract a bounded sdist beneath its single resolved project root."""
    _require_artifact(path, "sdist")
    if not path.name.endswith(".tar.gz"):
        raise DistributionError(f"Expected a .tar.gz sdist artifact: {path}")
    destination = Path(destination)
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            _validate_sdist_members(members)
            roots = {_sdist_member_path(member.name).parts[0] for member in members}
            if len(roots) != 1:
                raise DistributionError("Sdist must contain exactly one project root")
            root = destination / roots.pop()
            if root.exists() or root.is_symlink():
                raise DistributionError(
                    f"Sdist extraction destination already exists: {root}"
                )
            destination.mkdir(parents=True, exist_ok=True)
            if root.resolve().parent != destination.resolve():
                raise DistributionError(
                    f"Sdist extraction root resolves outside its destination: {root}"
                )
            for member in members:
                _sdist_target(root, member.name)
            # Members are bounded and tarfile's data filter rejects unsafe metadata.
            archive.extractall(  # nosec B202
                path=destination, filter=tarfile.data_filter
            )
            if not root.is_dir() or root.is_symlink():
                raise DistributionError(f"Sdist extraction root is invalid: {root}")
            for member in members:
                _sdist_target(root, member.name)
    except DistributionError:
        raise
    except (EOFError, OSError, tarfile.TarError) as error:
        raise DistributionError(f"Invalid sdist archive {path}: {error}") from error
    return root


def project_version(path: Path) -> str:
    """Read the expected release version from the checkout's project metadata."""
    try:
        project = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DistributionError(
            f"Unable to read project pyproject.toml: {error}"
        ) from error
    version = project.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise DistributionError("Project pyproject.toml has no valid project version")
    return version


def _select_artifact(directory: Path, suffix: str, label: str) -> Path:
    directory = Path(directory)
    try:
        candidates = sorted(
            path for path in directory.glob(f"*{suffix}") if path.is_file()
        )
    except OSError as error:
        raise DistributionError(
            f"Unable to inspect {label} directory: {error}"
        ) from error
    if len(candidates) != 1:
        raise DistributionError(
            f"Expected exactly one {label} artifact in {directory}, found {len(candidates)}"
        )
    return candidates[0]


def validate_distribution_directory(
    directory: Path, expected_version: str
) -> DistributionArtifacts:
    """Require and validate exactly one wheel and one source distribution."""
    directory = Path(directory)
    wheel_path = _select_artifact(directory, ".whl", "wheel")
    sdist_path = _select_artifact(directory, ".tar.gz", "sdist")
    return DistributionArtifacts(
        wheel=validate_wheel(wheel_path, expected_version),
        sdist=validate_sdist(sdist_path, expected_version),
    )


def sdist_rebuild_command(uv: Path, source: Path, output: Path) -> list[str]:
    """Build only a wheel from an extracted sdist, leaving published files intact."""
    return [str(uv), "build", "--wheel", "--out-dir", str(output)]


def venv_python_path(venv: Path, *, windows: bool) -> Path:
    return Path(venv) / ("Scripts/python.exe" if windows else "bin/python")


def console_script_path(scripts: Path, *, windows: bool) -> Path:
    return Path(scripts) / (f"{CONSOLE_SCRIPT}.exe" if windows else CONSOLE_SCRIPT)


def check_version_output(output: str, expected_version: str) -> None:
    expected = f"{CONSOLE_SCRIPT} {expected_version}"
    if output.strip() != expected:
        raise DistributionError(
            f"Console script version mismatch: expected {expected!r}, got {output.strip()!r}"
        )


def check_import_probe(
    probe: Mapping[str, object], venv: Path, expected_version: str
) -> None:
    try:
        version = str(probe["version"])
        package = Path(str(probe["package_path"])).resolve()
        purelib = Path(str(probe["purelib"])).resolve()
        scripts = Path(str(probe["scripts"])).resolve()
    except KeyError as error:
        raise DistributionError(
            f"Installed package probe is missing {error.args[0]}"
        ) from error
    if version != expected_version:
        raise DistributionError(
            f"Installed package version mismatch: expected {expected_version!r}, got {version!r}"
        )
    venv = Path(venv).resolve()
    if not purelib.is_relative_to(venv) or package.parent != purelib / PROJECT_NAME:
        raise DistributionError(
            "Imported package is not installed in the wheel venv site-packages"
        )
    if not scripts.is_relative_to(venv):
        raise DistributionError("Console scripts directory is outside the wheel venv")


def check_conversion_report(report: str, output: Path) -> None:
    try:
        payload = json.loads(report)
    except json.JSONDecodeError as error:
        raise DistributionError(
            f"Console conversion did not return JSON: {error}"
        ) from error
    checks = payload.get("checks") if isinstance(payload, dict) else None
    if not isinstance(checks, dict) or checks.get("text_integrity") != "passed":
        raise DistributionError("Installed wheel conversion failed text_integrity")
    try:
        valid_output = output.is_file() and output.stat().st_size > 0
    except OSError as error:
        raise DistributionError(
            f"Unable to inspect converted DOCX output: {error}"
        ) from error
    if not valid_output:
        raise DistributionError("Installed wheel conversion produced no DOCX output")


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    for name in tuple(environment):
        if name.startswith("MD2DOCX_"):
            environment.pop(name)
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(  # nosec B603
            list(command),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DistributionError(f"Unable to run {command[0]}: {error}") from error
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise DistributionError(
            f"Command failed with exit code {result.returncode}: {command!r}\n{details}"
        )
    return result


def _validate_docx(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise DistributionError("Converted DOCX contains a corrupt ZIP member")
            if not {"[Content_Types].xml", "word/document.xml"} <= set(
                archive.namelist()
            ):
                raise DistributionError(
                    "Converted DOCX is missing required OOXML parts"
                )
    except (OSError, zipfile.BadZipFile) as error:
        raise DistributionError(f"Converted DOCX is invalid: {error}") from error


def install_and_smoke(
    wheel: Path,
    workspace: Path,
    uv: Path,
    interpreter: Path,
    expected_version: str,
    *,
    conversion: bool,
) -> None:
    """Install a wheel into a fresh venv and exercise its real console script."""
    label = wheel.stem
    venv = workspace / f"{label}-venv"
    run_directory = workspace / f"{label}-run"
    run_directory.mkdir(parents=True)
    environment = _clean_environment()
    _run(
        [str(uv), "venv", str(venv), "--python", str(interpreter)],
        cwd=workspace,
        timeout=120,
        env=environment,
    )
    python = venv_python_path(venv, windows=os.name == "nt")
    _run(
        [str(uv), "pip", "install", "--python", str(python), str(wheel)],
        cwd=workspace,
        timeout=300,
        env=environment,
    )
    probe_result = _run(
        [str(python), "-I", "-c", IMPORT_PROBE],
        cwd=run_directory,
        timeout=60,
        env=environment,
    )
    try:
        probe = json.loads(probe_result.stdout)
    except json.JSONDecodeError as error:
        raise DistributionError(
            f"Installed package probe returned invalid JSON: {error}"
        ) from error
    check_import_probe(probe, venv, expected_version)
    console = console_script_path(Path(str(probe["scripts"])), windows=os.name == "nt")
    if not console.is_file():
        raise DistributionError(f"Installed console script is missing: {console}")
    version = _run(
        [str(console), "--version"],
        cwd=run_directory,
        timeout=30,
        env=environment,
    )
    check_version_output(version.stdout, expected_version)
    if not conversion:
        return

    source = run_directory / "input.md"
    source.write_text("# Wheel smoke test\n\nEditable document.\n", encoding="utf-8")
    output = run_directory / "output.docx"
    conversion_result = _run(
        [
            str(console),
            str(source),
            "--output",
            str(output),
            "--offline",
            "--json",
        ],
        cwd=run_directory,
        timeout=180,
        env=environment,
    )
    check_conversion_report(conversion_result.stdout, output)
    _validate_docx(output)
    _run(
        [str(console), "--doctor", "--json"],
        cwd=run_directory,
        timeout=60,
        env=environment,
    )


@dataclass(frozen=True)
class DistributionDependencies:
    """External operations injected into main for deterministic orchestration tests."""

    validate_distribution_directory: Callable[[Path, str], DistributionArtifacts] = (
        validate_distribution_directory
    )
    find_uv: Callable[[str], str | None] = shutil.which
    temporary_directory: Callable[..., AbstractContextManager[str]] = (
        tempfile.TemporaryDirectory
    )
    install_and_smoke: Callable[..., None] = install_and_smoke
    extract_sdist: Callable[[Path, Path], Path] = extract_sdist
    run: Callable[..., subprocess.CompletedProcess[str]] = _run
    select_artifact: Callable[[Path, str, str], Path] = _select_artifact
    validate_wheel: Callable[[Path, str], WheelInfo] = validate_wheel


def main(
    argv: Sequence[str] | None = None,
    *,
    dependencies: DistributionDependencies | None = None,
) -> int:
    dependencies = dependencies or DistributionDependencies()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--uv", type=Path, default=Path("uv"))
    parser.add_argument("--expected-version")
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args(argv)

    try:
        expected_version = args.expected_version or project_version(args.project)
        artifacts = dependencies.validate_distribution_directory(
            args.dist_dir, expected_version
        )
        uv_executable = dependencies.find_uv(str(args.uv.expanduser()))
        if uv_executable is None:
            raise DistributionError(f"Unable to find uv executable: {args.uv}")
        uv = Path(uv_executable).resolve()
        interpreter = args.python.expanduser().resolve()
        with dependencies.temporary_directory(
            prefix="md2docx-distribution-"
        ) as directory:
            workspace = Path(directory)
            dependencies.install_and_smoke(
                artifacts.wheel.path.resolve(),
                workspace / "published",
                uv,
                interpreter,
                expected_version,
                conversion=True,
            )
            print("Published wheel inventory and installed console smoke passed")
            extracted = dependencies.extract_sdist(
                artifacts.sdist.path.resolve(), workspace / "sdist-source"
            )
            rebuilt_directory = workspace / "rebuilt"
            rebuilt_directory.mkdir()
            dependencies.run(
                sdist_rebuild_command(uv, extracted, rebuilt_directory),
                cwd=extracted,
                timeout=300,
                env=_clean_environment(),
            )
            rebuilt_path = dependencies.select_artifact(
                rebuilt_directory, ".whl", "rebuilt wheel"
            )
            rebuilt = dependencies.validate_wheel(rebuilt_path, expected_version)
            dependencies.install_and_smoke(
                rebuilt.path.resolve(),
                workspace / "rebuilt-install",
                uv,
                interpreter,
                expected_version,
                conversion=False,
            )
            print("Sdist rebuild, inventory, and installed wheel smoke passed")
    except (DistributionError, OSError) as error:
        print(f"Distribution validation failed: {error}", file=sys.stderr)
        return 1
    print(f"Validated wheel and sdist for {PROJECT_NAME} {expected_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
