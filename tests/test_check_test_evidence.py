"""Synthetic directory coverage for required cross-platform test evidence."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_test_evidence.py"
REQUIRED_FILES = (
    "artifacts/junit.xml",
    "coverage.xml",
    "artifacts/multilingual/report.json",
    "artifacts/multilingual/multilingual.docx",
)
DISTRIBUTION_PATTERNS = ("*.whl", "*.tar.gz")


@pytest.fixture(name="evidence_checker")
def evidence_checker_fixture():
    if not SCRIPT_PATH.is_file():

        def missing_checker(*args, **kwargs):
            pytest.fail("scripts/check_test_evidence.py is missing")

        return SimpleNamespace(
            find_missing_evidence=missing_checker,
            main=missing_checker,
        )
    spec = importlib.util.spec_from_file_location("check_test_evidence", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_complete_evidence(root):
    for relative_path in REQUIRED_FILES:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"required evidence\n")
    dist = root / "artifacts" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "markdown2docx-0.2.0-py3-none-any.whl").write_bytes(b"wheel\n")
    (dist / "markdown2docx-0.2.0.tar.gz").write_bytes(b"sdist\n")


def test_complete_evidence_is_accepted(evidence_checker, tmp_path):
    write_complete_evidence(tmp_path)

    assert evidence_checker.find_missing_evidence(tmp_path) == []


@pytest.mark.parametrize("relative_path", REQUIRED_FILES)
def test_missing_required_file_is_rejected(evidence_checker, tmp_path, relative_path):
    write_complete_evidence(tmp_path)
    (tmp_path / relative_path).unlink()

    missing = evidence_checker.find_missing_evidence(tmp_path)

    assert relative_path in missing


@pytest.mark.parametrize("relative_path", REQUIRED_FILES)
def test_empty_required_file_is_rejected(evidence_checker, tmp_path, relative_path):
    write_complete_evidence(tmp_path)
    (tmp_path / relative_path).write_bytes(b"")

    missing = evidence_checker.find_missing_evidence(tmp_path)

    assert relative_path in missing


@pytest.mark.parametrize("pattern", DISTRIBUTION_PATTERNS)
def test_missing_distribution_is_rejected(evidence_checker, tmp_path, pattern):
    write_complete_evidence(tmp_path)
    dist = tmp_path / "artifacts" / "dist"
    for path in dist.glob(pattern):
        path.unlink()

    missing = evidence_checker.find_missing_evidence(tmp_path)

    assert f"artifacts/dist/{pattern}" in missing


@pytest.mark.parametrize("pattern", DISTRIBUTION_PATTERNS)
def test_empty_distribution_is_rejected(evidence_checker, tmp_path, pattern):
    write_complete_evidence(tmp_path)
    dist = tmp_path / "artifacts" / "dist"
    for path in dist.glob(pattern):
        path.unlink()
    (dist / f"empty{Path(pattern).suffix}").write_bytes(b"")

    missing = evidence_checker.find_missing_evidence(tmp_path)

    assert f"artifacts/dist/{pattern}" in missing


def test_cli_fails_on_missing_evidence(evidence_checker, tmp_path, capsys):
    assert evidence_checker.main(["--root", str(tmp_path)]) == 1

    error = capsys.readouterr().err
    assert "artifacts/junit.xml" in error
    assert "artifacts/dist/*.whl" in error
    assert "artifacts/dist/*.tar.gz" in error


def test_cli_accepts_complete_evidence(evidence_checker, tmp_path):
    write_complete_evidence(tmp_path)

    assert evidence_checker.main(["--root", str(tmp_path)]) == 0
