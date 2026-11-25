"""Contract tests for the checkout-independent agent skill launcher."""

import importlib.util
import re
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = REPO_ROOT / "skills" / "markdown-to-docx" / "scripts" / "run.py"


@pytest.fixture
def launcher():
    spec = importlib.util.spec_from_file_location(
        "markdown_to_docx_skill_run", LAUNCHER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execution_revision_is_a_resolvable_commit(launcher):
    assert re.fullmatch(r"[0-9a-f]{40}", launcher.EXECUTION_REVISION)
    subprocess.run(
        ["git", "cat-file", "-e", f"{launcher.EXECUTION_REVISION}^{{commit}}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_source_uses_the_execution_revision(launcher):
    assert launcher.SOURCE == (
        f"git+https://github.com/cnkang/markdown2docx.git@{launcher.EXECUTION_REVISION}"
    )


def test_launcher_passes_uv_and_user_arguments(launcher, monkeypatch):
    user_arguments = [
        "/tmp/input file.md",
        "-o",
        "/tmp/output file.docx",
        "--json",
        "--ui-lang",
        "zh",
    ]
    which = Mock(return_value="/opt/uv")
    call = Mock(return_value=23)
    monkeypatch.setattr(launcher.shutil, "which", which)
    monkeypatch.setattr(launcher.subprocess, "call", call)
    monkeypatch.setattr(launcher.sys, "argv", ["run.py", *user_arguments])

    assert launcher.main() == 23

    which.assert_called_once_with("uv")
    call.assert_called_once_with(
        [
            "/opt/uv",
            "tool",
            "run",
            "--python",
            "3.14",
            "--from",
            launcher.SOURCE,
            "markdown2docx",
            *user_arguments,
        ]
    )


def test_user_offline_argument_also_disables_uv_network_access(launcher, monkeypatch):
    which = Mock(return_value="/opt/uv")
    call = Mock(return_value=0)
    monkeypatch.setattr(launcher.shutil, "which", which)
    monkeypatch.setattr(launcher.subprocess, "call", call)
    monkeypatch.setattr(launcher.sys, "argv", ["run.py", "input.md", "--offline"])

    assert launcher.main() == 0

    call.assert_called_once_with(
        [
            "/opt/uv",
            "tool",
            "run",
            "--offline",
            "--python",
            "3.14",
            "--from",
            launcher.SOURCE,
            "markdown2docx",
            "input.md",
            "--offline",
        ]
    )


def test_missing_uv_returns_127_without_running_a_command(
    launcher, monkeypatch, capsys
):
    which = Mock(return_value=None)
    call = Mock()
    monkeypatch.setattr(launcher.shutil, "which", which)
    monkeypatch.setattr(launcher.subprocess, "call", call)

    assert launcher.main() == 127

    which.assert_called_once_with("uv")
    call.assert_not_called()
    assert "requires uv" in capsys.readouterr().err
