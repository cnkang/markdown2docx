"""Fail-closed contracts for reusable CI and same-commit release gates."""

import os
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_WORKFLOW_PATH = "./.github/workflows/test.yml"
ACTIONLINT_COMMAND = "go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7"
MATRIX_TEST_COMMAND = (
    "uv run --locked pytest --cov=src --cov-branch --cov-report=xml "
    "--cov-report=term-missing --junitxml=artifacts/junit.xml"
)
CRITICAL_JOB_IDS = ("quality", "skill", "test")
CRITICAL_STEP_LOCATIONS = (
    ("quality", "quality"),
    ("quality", "actionlint"),
    ("quality", "pre-commit"),
    ("skill", "skill-smoke"),
    ("test", "matrix-test"),
    ("test", "multilingual-validation"),
    ("test", "wheel-validation"),
    ("test", "check-test-evidence"),
)
STEP_IF_ALLOWLIST = {
    "skill-smoke-artifacts": "always()",
    "required-artifacts": "always()",
    "preview-artifacts": "always()",
    "distribution-artifacts": "always()",
    "windows-junit-gate": "runner.os == 'Windows'",
    "install-rendering-dependencies": "runner.os == 'Linux'",
    "install-linux-fixture-fonts": "runner.os == 'Linux'",
    "render-multilingual": "runner.os == 'Linux'",
    "publish-testpypi": "inputs.repository == 'testpypi'",
    "publish-pypi": "inputs.repository == 'pypi'",
}
BUILD_STEP_IDS = (
    "require-release-tag",
    "checkout",
    "setup-uv",
    "install-pandoc",
    "prepare-fonts",
    "build-distribution",
    "verify-distributions",
    "distribution-artifacts",
)
ARTIFACT_SPECS = (
    {
        "workflow": "test",
        "job": "skill",
        "id": "skill-smoke-artifacts",
        "name": "skill-smoke",
        "paths": ("artifacts/skill-smoke/",),
        "policy": "error",
        "required": True,
    },
    {
        "workflow": "test",
        "job": "test",
        "id": "required-artifacts",
        "name": "evidence-${{ runner.os }}",
        "paths": (
            "artifacts/multilingual/multilingual.docx",
            "artifacts/multilingual/report.json",
            "artifacts/dist/",
            "artifacts/junit.xml",
            "coverage.xml",
        ),
        "policy": "error",
        "required": True,
    },
    {
        "workflow": "test",
        "job": "test",
        "id": "preview-artifacts",
        "name": "preview-${{ runner.os }}",
        "paths": ("artifacts/multilingual/preview/",),
        "policy": "warn",
        "required": False,
    },
    {
        "workflow": "release",
        "job": "build",
        "id": "distribution-artifacts",
        "name": "distribution",
        "paths": ("dist/",),
        "policy": "error",
        "required": True,
    },
)
REQUIRED_ARTIFACT_SPECS = tuple(spec for spec in ARTIFACT_SPECS if spec["required"])
VALID_TAG_STEP = {
    "id": "require-release-tag",
    "env": {
        "RELEASE_REF": "${{ inputs.release_ref }}",
        "RUN_REF": "${{ github.ref_name }}",
        "RUN_REF_TYPE": "${{ github.ref_type }}",
    },
    "run": """if [[ ! "$RELEASE_REF" =~ ^v[0-9]+\\.[0-9]+\\.[0-9]+$ ]]; then
  echo "Expected a vX.Y.Z release tag"
  exit 1
fi
if [ "$RUN_REF_TYPE" != "tag" ] || [ "$RUN_REF" != "$RELEASE_REF" ]; then
  echo "Dispatch this workflow on the reviewed release tag itself"
  exit 1
fi
""",
}


def load_workflow(filename):
    path = REPO_ROOT / ".github" / "workflows" / filename
    assert path.is_file(), f"{path} is missing"
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def required_jobs(job):
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def step_by_id(job, step_id):
    matches = [step for step in job.get("steps", []) if step.get("id") == step_id]
    assert len(matches) == 1, f"expected exactly one step with id {step_id!r}"
    return matches[0]


def continue_on_error_errors(workflow):
    errors = []
    for job_id, job in workflow.get("jobs", {}).items():
        if "continue-on-error" in job:
            errors.append(f"job {job_id} defines continue-on-error")
        for step in job.get("steps", []):
            if "continue-on-error" in step:
                errors.append(
                    f"job {job_id} step {step.get('id', '<missing id>')} "
                    "defines continue-on-error"
                )
    return errors


def condition_errors(workflow):
    errors = []
    for job_id, job in workflow.get("jobs", {}).items():
        if "if" in job:
            errors.append(f"job {job_id} must not define if")
        for step in job.get("steps", []):
            step_id = step.get("id", "<missing id>")
            if "if" in step and step["if"] != STEP_IF_ALLOWLIST.get(step_id):
                errors.append(f"job {job_id} step {step_id} has a disallowed if")
    return errors


def tag_structure_errors(step):
    errors = []
    if "if" in step:
        errors.append("release tag validation must not be conditionally skipped")
    if "continue-on-error" in step:
        errors.append("release tag validation must not continue on error")
    expected_env = {
        "RELEASE_REF": "${{ inputs.release_ref }}",
        "RUN_REF": "${{ github.ref_name }}",
        "RUN_REF_TYPE": "${{ github.ref_type }}",
    }
    if step.get("env") != expected_env:
        errors.append("release tag validation environment contract changed")
    return errors


def run_tag_validation(step, release_ref, run_ref, run_ref_type):
    env = os.environ.copy()
    env.update(
        RELEASE_REF=release_ref,
        RUN_REF=run_ref,
        RUN_REF_TYPE=run_ref_type,
    )
    return subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def artifact_paths(step):
    raw_path = step.get("with", {}).get("path", "")
    return tuple(line.strip() for line in raw_path.splitlines() if line.strip())


def artifact_contract_errors(test_workflow, release_workflow):
    workflows = {"test": test_workflow, "release": release_workflow}
    errors = []
    for spec in ARTIFACT_SPECS:
        label = f"{spec['workflow']}/{spec['job']}/{spec['id']}"
        job = workflows[spec["workflow"]].get("jobs", {}).get(spec["job"], {})
        matches = [
            step for step in job.get("steps", []) if step.get("id") == spec["id"]
        ]
        if not matches and not spec["required"]:
            continue
        if len(matches) != 1:
            errors.append(f"{label} must exist exactly once")
            continue
        step = matches[0]
        config = step.get("with", {})
        if not step.get("uses", "").startswith("actions/upload-artifact@"):
            errors.append(f"{label} must upload an artifact")
        if config.get("name") != spec["name"]:
            errors.append(f"{label} artifact name changed")
        if artifact_paths(step) != spec["paths"]:
            errors.append(f"{label} artifact paths changed")
        if config.get("if-no-files-found") != spec["policy"]:
            errors.append(f"{label} must use if-no-files-found: {spec['policy']}")
        if step.get("if") != "always()":
            errors.append(f"{label} must run even after an earlier failure")
    return errors


def synthetic_artifact_workflows():
    def upload(spec):
        return {
            "id": spec["id"],
            "if": "always()",
            "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
            "with": {
                "name": spec["name"],
                "path": "\n".join(spec["paths"]),
                "if-no-files-found": spec["policy"],
            },
        }

    test_workflow = {
        "jobs": {
            "skill": {"steps": [upload(ARTIFACT_SPECS[0])]},
            "test": {"steps": [upload(ARTIFACT_SPECS[1]), upload(ARTIFACT_SPECS[2])]},
        }
    }
    release_workflow = {"jobs": {"build": {"steps": [upload(ARTIFACT_SPECS[3])]}}}
    return test_workflow, release_workflow


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
    assert required_jobs(release_workflow["jobs"]["build"]) == {"test"}


def test_release_publish_requires_the_gated_build(release_workflow):
    assert required_jobs(release_workflow["jobs"]["publish"]) == {"build"}


def test_repository_pins_python_314():
    version_path = REPO_ROOT / ".python-version"

    assert version_path.is_file(), ".python-version is missing"
    assert version_path.read_text(encoding="utf-8").strip() == "3.14"


def test_release_build_has_only_packaging_steps(release_workflow):
    steps = release_workflow["jobs"]["build"]["steps"]

    assert tuple(step.get("id") for step in steps) == BUILD_STEP_IDS
    assert (
        step_by_id(release_workflow["jobs"]["build"], "build-distribution")[
            "run"
        ].strip()
        == "uv build"
    )


def test_release_build_verifies_wheel_and_sdist(release_workflow):
    verify = step_by_id(release_workflow["jobs"]["build"], "verify-distributions")

    assert "dist/*.whl" in verify["run"]
    assert "scripts/validate_wheel.py" in verify["run"]
    assert "*.tar.gz" in verify["run"]
    assert "tarfile.open" in verify["run"]


def test_release_build_and_reusable_jobs_check_out_github_sha(
    test_workflow, release_workflow
):
    checkout_jobs = [*test_workflow["jobs"].values(), release_workflow["jobs"]["build"]]

    for job in checkout_jobs:
        checkout = step_by_id(job, "checkout")
        ref = checkout.get("with", {}).get("ref", "${{ github.sha }}")
        assert ref == "${{ github.sha }}"


def test_quality_runs_locked_checks_and_pinned_actionlint(test_workflow):
    quality = test_workflow["jobs"]["quality"]

    assert quality["runs-on"] == "ubuntu-latest"
    assert step_by_id(quality, "quality")["run"].strip() == "make quality"
    assert step_by_id(quality, "pre-commit")["run"].strip() == (
        "uv run --locked pre-commit run --all-files"
    )
    assert step_by_id(quality, "actionlint")["run"].strip() == ACTIONLINT_COMMAND


def test_reusable_workflow_runs_real_skill_smoke(test_workflow):
    smoke = step_by_id(test_workflow["jobs"]["skill"], "skill-smoke")

    assert "skills/markdown-to-docx/scripts/run.py" in smoke["run"]
    assert "artifacts/skill-smoke/output.docx" in smoke["run"]
    assert "--offline --json" in smoke["run"]


def test_reusable_workflow_runs_three_platform_tests_after_quality(test_workflow):
    test = test_workflow["jobs"]["test"]
    platforms = test["strategy"]["matrix"]["os"]

    assert required_jobs(test) == {"quality"}
    assert set(platforms) == {"ubuntu-latest", "macos-latest", "windows-latest"}
    assert step_by_id(test, "matrix-test")["run"].strip() == MATRIX_TEST_COMMAND


def test_reusable_workflow_enforces_windows_junit_skips(test_workflow):
    audit = step_by_id(test_workflow["jobs"]["test"], "windows-junit-gate")

    assert audit["if"] == "runner.os == 'Windows'"
    assert audit["run"].strip() == (
        "uv run --locked python scripts/check_test_skips.py artifacts/junit.xml"
    )


def test_required_evidence_is_checked_before_artifact_upload(test_workflow):
    steps = test_workflow["jobs"]["test"]["steps"]
    check_indices = [
        index
        for index, step in enumerate(steps)
        if step.get("id") == "check-test-evidence"
    ]
    upload_indices = [
        index
        for index, step in enumerate(steps)
        if step.get("id") == "required-artifacts"
    ]

    assert len(check_indices) == 1
    assert len(upload_indices) == 1
    assert check_indices[0] < upload_indices[0]
    assert steps[check_indices[0]]["run"].strip() == (
        "uv run --locked python scripts/check_test_evidence.py"
    )


@pytest.mark.parametrize("job_id", CRITICAL_JOB_IDS)
def test_critical_jobs_are_unconditional(test_workflow, job_id):
    job = test_workflow["jobs"][job_id]

    assert "if" not in job
    assert "continue-on-error" not in job


@pytest.mark.parametrize(("job_id", "step_id"), CRITICAL_STEP_LOCATIONS)
def test_critical_steps_are_unconditional(test_workflow, job_id, step_id):
    step = step_by_id(test_workflow["jobs"][job_id], step_id)

    assert "if" not in step
    assert "continue-on-error" not in step


def test_only_explicit_step_conditions_are_allowed(test_workflow, release_workflow):
    assert condition_errors(test_workflow) == []
    assert condition_errors(release_workflow) == []


def test_required_and_optional_artifacts_are_fail_closed(
    test_workflow, release_workflow
):
    assert artifact_contract_errors(test_workflow, release_workflow) == []


def test_critical_workflow_nodes_do_not_continue_on_error(
    test_workflow, release_workflow
):
    assert continue_on_error_errors(test_workflow) == []
    assert continue_on_error_errors(release_workflow) == []


def test_release_tag_validation_is_unconditional_and_bound_to_dispatch(
    release_workflow,
):
    tag_step = step_by_id(release_workflow["jobs"]["build"], "require-release-tag")

    assert tag_structure_errors(tag_step) == []
    assert release_workflow["jobs"]["build"]["steps"][0]["id"] == tag_step["id"]


@pytest.mark.parametrize(
    ("release_ref", "run_ref", "run_ref_type"),
    [
        ("1.2.3", "1.2.3", "tag"),
        ("v1.2.3", "v1.2.3", "branch"),
        ("v1.2.3", "v9.9.9", "tag"),
    ],
)
def test_release_tag_validation_rejects_invalid_dispatch(
    release_workflow, release_ref, run_ref, run_ref_type
):
    tag_step = step_by_id(release_workflow["jobs"]["build"], "require-release-tag")

    result = run_tag_validation(tag_step, release_ref, run_ref, run_ref_type)

    assert result.returncode != 0


def test_release_tag_validation_accepts_matching_tag(release_workflow):
    tag_step = step_by_id(release_workflow["jobs"]["build"], "require-release-tag")

    result = run_tag_validation(tag_step, "v1.2.3", "v1.2.3", "tag")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("location", ["job", "step"])
def test_synthetic_continue_on_error_is_rejected(location):
    workflow = {"jobs": {"quality": {"steps": [{"id": "quality"}]}}}
    target = workflow["jobs"]["quality"]
    if location == "step":
        target = target["steps"][0]
    target["continue-on-error"] = "true"

    assert continue_on_error_errors(workflow)


@pytest.mark.parametrize(
    ("job_id", "step_id"),
    [(job_id, None) for job_id in CRITICAL_JOB_IDS] + list(CRITICAL_STEP_LOCATIONS),
)
def test_synthetic_false_if_is_rejected(job_id, step_id):
    job = {"steps": []}
    workflow = {"jobs": {job_id: job}}
    target = job
    if step_id is not None:
        target = {"id": step_id}
        job["steps"].append(target)
    target["if"] = "false"

    assert condition_errors(workflow)


@pytest.mark.parametrize(("step_id", "condition"), STEP_IF_ALLOWLIST.items())
def test_synthetic_whitelisted_step_condition_is_allowed(step_id, condition):
    workflow = {"jobs": {"publish": {"steps": [{"id": step_id, "if": condition}]}}}

    assert condition_errors(workflow) == []


def test_synthetic_disabled_tag_step_is_rejected():
    tag_step = deepcopy(VALID_TAG_STEP)
    tag_step["if"] = "false"

    assert tag_structure_errors(tag_step)


@pytest.mark.parametrize("spec", REQUIRED_ARTIFACT_SPECS)
def test_synthetic_missing_required_artifact_is_rejected(spec):
    test_workflow, release_workflow = synthetic_artifact_workflows()
    workflow = test_workflow if spec["workflow"] == "test" else release_workflow
    job = workflow["jobs"][spec["job"]]
    job["steps"] = [step for step in job["steps"] if step["id"] != spec["id"]]

    errors = artifact_contract_errors(test_workflow, release_workflow)

    assert any(spec["id"] in error for error in errors)


@pytest.mark.parametrize("spec", REQUIRED_ARTIFACT_SPECS)
def test_synthetic_required_artifact_warn_policy_is_rejected(spec):
    test_workflow, release_workflow = synthetic_artifact_workflows()
    workflow = test_workflow if spec["workflow"] == "test" else release_workflow
    step = step_by_id(workflow["jobs"][spec["job"]], spec["id"])
    step["with"]["if-no-files-found"] = "warn"

    errors = artifact_contract_errors(test_workflow, release_workflow)

    assert any(spec["id"] in error for error in errors)


def test_synthetic_optional_preview_can_warn():
    assert artifact_contract_errors(*synthetic_artifact_workflows()) == []


def test_synthetic_missing_optional_preview_is_allowed():
    test_workflow, release_workflow = synthetic_artifact_workflows()
    job = test_workflow["jobs"]["test"]
    job["steps"] = [step for step in job["steps"] if step["id"] != "preview-artifacts"]

    assert artifact_contract_errors(test_workflow, release_workflow) == []
