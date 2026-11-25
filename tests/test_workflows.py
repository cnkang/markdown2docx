"""Contract tests for reusable CI and same-commit release gates."""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_WORKFLOW_PATH = "./.github/workflows/test.yml"


def load_workflow(filename):
    path = REPO_ROOT / ".github" / "workflows" / filename
    assert path.is_file(), f"{path} is missing"
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def run_commands(job):
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def required_jobs(job):
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def named_step(job, name):
    return next(
        (step for step in job.get("steps", []) if step.get("name") == name), None
    )


@pytest.fixture(name="test_workflow")
def test_workflow_fixture():
    return load_workflow("test.yml")


@pytest.fixture(name="release_workflow")
def release_workflow_fixture():
    return load_workflow("release.yml")


def test_test_workflow_supports_push_pull_request_and_call(test_workflow):
    assert {"push", "pull_request", "workflow_call"} <= set(test_workflow["on"])


def test_release_calls_the_test_workflow(release_workflow):
    gate = release_workflow["jobs"].get("test", {})

    assert gate.get("uses") == TEST_WORKFLOW_PATH
    assert "runs-on" not in gate
    assert "steps" not in gate


def test_release_build_requires_the_reusable_test_gate(release_workflow):
    build = release_workflow["jobs"]["build"]

    assert required_jobs(build) == {"test"}


def test_release_publish_requires_the_gated_build(release_workflow):
    publish = release_workflow["jobs"]["publish"]

    assert required_jobs(publish) == {"build"}


def test_repository_pins_python_314():
    version_path = REPO_ROOT / ".python-version"

    assert version_path.is_file(), ".python-version is missing"
    assert version_path.read_text(encoding="utf-8").strip() == "3.14"


def test_release_build_does_not_duplicate_reusable_gates(release_workflow):
    build = release_workflow["jobs"]["build"]
    commands = run_commands(build)

    for duplicate in (
        "make quality",
        "pytest",
        "ruff ",
        "mypy ",
        "bandit ",
        "pre-commit",
        "scripts/validate_multilingual.py",
    ):
        assert duplicate not in commands, f"release build repeats {duplicate}"


def test_release_build_verifies_wheel_and_sdist(release_workflow):
    commands = run_commands(release_workflow["jobs"]["build"])

    assert "uv build" in commands
    assert "dist/*.whl" in commands
    assert "scripts/validate_wheel.py" in commands
    assert "*.tar.gz" in commands
    assert "tarfile" in commands


def test_release_build_and_reusable_jobs_check_out_github_sha(
    test_workflow, release_workflow
):
    build_checkouts = [
        step
        for step in release_workflow["jobs"]["build"]["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    reusable_checkouts = [
        step
        for job in test_workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("uses", "").startswith("actions/checkout@")
    ]

    assert build_checkouts
    assert reusable_checkouts
    for checkout in [*build_checkouts, *reusable_checkouts]:
        ref = checkout.get("with", {}).get("ref", "${{ github.sha }}")
        assert ref == "${{ github.sha }}"


def test_reusable_workflow_runs_quality_on_ubuntu(test_workflow):
    quality = test_workflow["jobs"]["quality"]
    commands = run_commands(quality)

    assert quality["runs-on"] == "ubuntu-latest"
    assert "make quality" in commands
    assert "pre-commit run --all-files" in commands


def test_reusable_workflow_runs_real_skill_smoke(test_workflow):
    skill = test_workflow["jobs"]["skill"]
    smoke = named_step(skill, "Smoke test the real agent skill launcher")

    assert smoke is not None
    commands = smoke["run"]
    assert "skills/markdown-to-docx/scripts/run.py" in commands
    assert "--offline --json" in commands
    assert "Real agent skill launcher smoke passed" in commands


def test_reusable_workflow_runs_three_platform_tests_after_quality(test_workflow):
    test = test_workflow["jobs"]["test"]
    platforms = test["strategy"]["matrix"]["os"]

    assert required_jobs(test) == {"quality"}
    assert set(platforms) == {"ubuntu-latest", "macos-latest", "windows-latest"}
    assert "--junitxml=artifacts/junit.xml" in run_commands(test)


def test_reusable_workflow_enforces_windows_junit_skips(test_workflow):
    test = test_workflow["jobs"]["test"]
    audit = named_step(test, "Audit Windows test skips")

    assert audit is not None
    assert audit["if"] == "runner.os == 'Windows'"
    assert "scripts/check_test_skips.py artifacts/junit.xml" in audit["run"]
