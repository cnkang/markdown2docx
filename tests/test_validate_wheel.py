"""Synthetic wheel and sdist contracts for the release distribution validator."""

import importlib.util
import io
import json
import tarfile
import tomllib
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


def record_contents(files):
    rows = ["path,hash,size"]
    rows.extend(f"{name},," for name in files)
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


def test_sdist_extraction_rejects_path_traversal(validator, tmp_path):
    sdist = write_sdist(
        tmp_path,
        files=sdist_files(**{f"{SDIST_ROOT}/../escape.py": b"escape\n"}),
    )
    destination = tmp_path / "extracted"

    with pytest.raises(ValueError, match="unsafe|member|path"):
        validator.extract_sdist(sdist, destination)
    assert not (tmp_path / "escape.py").exists()


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


def test_project_version_comes_from_pyproject(validator, tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_bytes(PYPROJECT)

    assert validator.project_version(project) == VERSION


def test_sdist_rebuild_uses_only_the_wheel_target(validator, tmp_path):
    command = validator.sdist_rebuild_command(
        Path("/tools/uv"), tmp_path / "source", tmp_path / "rebuilt"
    )

    assert command == [
        "/tools/uv",
        "build",
        "--wheel",
        "--out-dir",
        str(tmp_path / "rebuilt"),
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
    assert step["env"]["RELEASE_REF"] == "${{ inputs.release_ref }}"
