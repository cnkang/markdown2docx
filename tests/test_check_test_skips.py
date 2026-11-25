"""Synthetic JUnit coverage for the Windows skip audit."""

import importlib.util
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_test_skips.py"


@pytest.fixture(name="load_skip_checker")
def skip_checker_loader():
    def load():
        assert SCRIPT_PATH.is_file(), "scripts/check_test_skips.py is missing"
        spec = importlib.util.spec_from_file_location("check_test_skips", SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load


def write_junit(tmp_path, cases):
    root = ElementTree.Element("testsuite")
    for classname, name, reason in cases:
        case = ElementTree.SubElement(
            root, "testcase", {"classname": classname, "name": name}
        )
        if reason is not None:
            ElementTree.SubElement(case, "skipped", {"message": reason})
    path = tmp_path / "junit.xml"
    ElementTree.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_windows_accepts_prefixed_output_skips(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_junit(
        tmp_path,
        [
            (
                "tests.test_output",
                "test_posix_symlink",
                "posix_only: symlink semantics",
            ),
            ("tests.test_output", "test_windows_output", None),
        ],
    )

    assert skip_checker.find_unexpected_skips(report, windows=True) == []


def test_windows_rejects_unprefixed_output_skip(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_junit(
        tmp_path,
        [("tests.test_output", "test_optional_feature", "feature unavailable")],
    )

    violations = skip_checker.find_unexpected_skips(report, windows=True)

    assert len(violations) == 1
    assert "tests/test_output.py::test_optional_feature" in violations[0]
    assert "posix_only:" in violations[0]


def test_windows_rejects_skip_outside_output_tests(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_junit(
        tmp_path,
        [("tests.test_multilingual", "test_optional_feature", "posix_only: unused")],
    )

    violations = skip_checker.find_unexpected_skips(report, windows=True)

    assert len(violations) == 1
    assert "tests/test_multilingual.py::test_optional_feature" in violations[0]
    assert "outside tests/test_output.py" in violations[0]


def test_non_windows_does_not_enforce_skip_policy(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_junit(
        tmp_path,
        [
            ("tests.test_output", "test_optional_feature", "feature unavailable"),
            ("tests.test_multilingual", "test_windows_feature", "Windows only"),
        ],
    )

    assert skip_checker.find_unexpected_skips(report, windows=False) == []


def test_windows_reads_file_attribute_and_skipped_text(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    root = ElementTree.Element("testsuites")
    case = ElementTree.SubElement(
        root,
        "testcase",
        {"file": r"tests\test_output.py", "name": "test_posix_symlink"},
    )
    skipped = ElementTree.SubElement(case, "skipped")
    skipped.text = "posix_only: descriptor semantics"
    report = tmp_path / "junit.xml"
    ElementTree.ElementTree(root).write(report, encoding="utf-8")

    assert skip_checker.find_unexpected_skips(report, windows=True) == []


def test_cli_fails_on_unexpected_windows_skip(load_skip_checker, tmp_path, capsys):
    skip_checker = load_skip_checker()
    report = write_junit(
        tmp_path,
        [("tests.test_output", "test_optional_feature", "feature unavailable")],
    )

    assert skip_checker.main([str(report)], windows=True) == 1
    assert "tests/test_output.py::test_optional_feature" in capsys.readouterr().err


def test_cli_accepts_expected_windows_skips(load_skip_checker, tmp_path, capsys):
    skip_checker = load_skip_checker()
    report = write_junit(
        tmp_path,
        [("tests.test_output", "test_posix_symlink", "posix_only: symlink semantics")],
    )

    assert skip_checker.main([str(report)], windows=True) == 0
    assert capsys.readouterr().err == ""
