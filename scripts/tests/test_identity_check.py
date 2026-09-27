"""The pre-publish identifying-information check (docs/deploy-checklist.md)."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "identity_check.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Pseudonym")
    git(tmp_path, "config", "user.email", "pseudonym@example.org")
    (tmp_path / "README.md").write_text("A fictional company.\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def check(repo: Path, *patterns: str) -> subprocess.CompletedProcess:
    args = [a for p in patterns for a in ("--pattern", p)]
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args], capture_output=True, text=True, check=False)


def test_a_clean_repo_passes(repo):
    assert check(repo, "acme corp").returncode == 0


def test_a_term_in_a_tracked_file_fails_case_insensitively(repo):
    (repo / "notes.md").write_text("Built at ACME Corp.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "notes")
    result = check(repo, "acme corp")
    assert result.returncode == 1 and "notes.md" in result.stdout


def test_a_term_only_in_history_still_fails(repo):
    (repo / "old.md").write_text("acme corp\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add")
    git(repo, "rm", "-q", "old.md")
    git(repo, "commit", "-q", "-m", "remove")
    assert check(repo, "acme corp").returncode == 1


def test_a_term_in_an_author_identity_or_message_fails(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "empty", "--author", "Real Name <real@acme-corp.example>")
    assert check(repo, "acme-corp").returncode == 1
    git(repo, "commit", "-q", "--allow-empty", "-m", "done for Initech")
    assert check(repo, "initech").returncode == 1


def test_no_patterns_is_an_error_not_a_pass(repo):
    assert check(repo).returncode == 2
