"""Synthetic JUnit coverage for the Windows skip and coverage audit."""

import importlib.util
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_test_skips.py"
REQUIRED_WINDOWS_OUTPUT_CASES = (
    "test_windows_rejects_junction_output_parent",
    "test_windows_staged_output_pins_parent_directory",
    "test_windows_no_overwrite_preserves_existing_file",
    "test_windows_writer_failure_preserves_existing_file[conversion]",
    "test_windows_writer_failure_preserves_existing_file[template]",
    "test_windows_validation_failure_preserves_existing_file",
    "test_windows_rejects_real_casefolded_input_output_alias",
)


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


def required_windows_cases():
    return [("tests.test_output", name, None) for name in REQUIRED_WINDOWS_OUTPUT_CASES]


def write_complete_report(tmp_path, extra_cases=()):
    return write_junit(tmp_path, [*required_windows_cases(), *extra_cases])


def test_windows_accepts_prefixed_output_skips(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_complete_report(
        tmp_path,
        [("tests.test_output", "test_posix_symlink", "posix_only: symlink semantics")],
    )

    assert skip_checker.find_unexpected_skips(report, windows=True) == []


def test_windows_rejects_unprefixed_output_skip(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_complete_report(
        tmp_path,
        [("tests.test_output", "test_optional_feature", "feature unavailable")],
    )

    violations = skip_checker.find_unexpected_skips(report, windows=True)

    assert len(violations) == 1
    assert "tests/test_output.py::test_optional_feature" in violations[0]
    assert "posix_only:" in violations[0]


def test_windows_rejects_skip_outside_output_tests(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_complete_report(
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
    report = write_complete_report(tmp_path)
    tree = ElementTree.parse(report)
    root = tree.getroot()
    root.tag = "testsuites"
    case = ElementTree.SubElement(
        root,
        "testcase",
        {"file": r"tests\test_output.py", "name": "test_posix_symlink"},
    )
    skipped = ElementTree.SubElement(case, "skipped")
    skipped.text = "posix_only: descriptor semantics"
    tree.write(report, encoding="utf-8")

    assert skip_checker.find_unexpected_skips(report, windows=True) == []


def test_windows_rejects_missing_required_output_case(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_junit(tmp_path, required_windows_cases()[1:])

    violations = skip_checker.find_unexpected_skips(report, windows=True)

    assert len(violations) == 1
    assert REQUIRED_WINDOWS_OUTPUT_CASES[0] in violations[0]
    assert "missing required Windows output case" in violations[0]


def test_windows_rejects_missing_writer_template_variant(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    required_name = "test_windows_writer_failure_preserves_existing_file[template]"
    cases = [case for case in required_windows_cases() if case[1] != required_name]
    report = write_junit(tmp_path, cases)

    violations = skip_checker.find_unexpected_skips(report, windows=True)

    assert len(violations) == 1
    assert required_name in violations[0]
    assert "missing required Windows output case" in violations[0]


def test_windows_wrong_writer_variant_cannot_replace_required_case(
    load_skip_checker, tmp_path
):
    skip_checker = load_skip_checker()
    required_name = "test_windows_writer_failure_preserves_existing_file[conversion]"
    cases = [case for case in required_windows_cases() if case[1] != required_name]
    cases.append(
        (
            "tests.test_output",
            "test_windows_writer_failure_preserves_existing_file[other]",
            None,
        )
    )
    report = write_junit(tmp_path, cases)

    violations = skip_checker.find_unexpected_skips(report, windows=True)

    assert len(violations) == 1
    assert required_name in violations[0]
    assert "missing required Windows output case" in violations[0]


def test_windows_rejects_required_output_case_marked_posix_only(
    load_skip_checker, tmp_path
):
    skip_checker = load_skip_checker()
    cases = required_windows_cases()
    cases[0] = (*cases[0][:2], "posix_only: incorrectly scoped")
    report = write_junit(tmp_path, cases)

    violations = skip_checker.find_unexpected_skips(report, windows=True)

    assert len(violations) == 1
    assert REQUIRED_WINDOWS_OUTPUT_CASES[0] in violations[0]
    assert "required Windows output case was skipped" in violations[0]


def test_windows_rejects_empty_report(load_skip_checker, tmp_path):
    skip_checker = load_skip_checker()
    report = write_junit(tmp_path, [])

    violations = skip_checker.find_unexpected_skips(report, windows=True)

    assert len(violations) == len(REQUIRED_WINDOWS_OUTPUT_CASES)
    assert all("missing required Windows output case" in item for item in violations)


def test_cli_fails_on_unexpected_windows_skip(load_skip_checker, tmp_path, capsys):
    skip_checker = load_skip_checker()
    report = write_complete_report(
        tmp_path,
        [("tests.test_output", "test_optional_feature", "feature unavailable")],
    )

    assert skip_checker.main([str(report)], windows=True) == 1
    assert "tests/test_output.py::test_optional_feature" in capsys.readouterr().err


def test_cli_accepts_expected_windows_skips(load_skip_checker, tmp_path, capsys):
    skip_checker = load_skip_checker()
    report = write_complete_report(
        tmp_path,
        [("tests.test_output", "test_posix_symlink", "posix_only: symlink semantics")],
    )

    assert skip_checker.main([str(report)], windows=True) == 0
    assert capsys.readouterr().err == ""
