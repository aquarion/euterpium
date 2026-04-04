import importlib
import subprocess

import version


def test_detect_git_branch_returns_branch(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/test\n")

    monkeypatch.setattr(version.subprocess, "run", fake_run)

    assert version._detect_git_branch() == "feature/test"


def test_detect_git_branch_returns_none_on_detached_head(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="HEAD\n")

    monkeypatch.setattr(version.subprocess, "run", fake_run)

    assert version._detect_git_branch() is None


def test_detect_git_branch_returns_none_when_git_fails(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="")

    monkeypatch.setattr(version.subprocess, "run", fake_run)

    assert version._detect_git_branch() is None


def test_version_defaults_to_dev_when_git_unavailable(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(version.subprocess, "run", fake_run)

    reloaded = importlib.reload(version)
    assert reloaded.__version__ == "0.1.0"
    assert reloaded.__display_version__ == "dev"


def test_version_uses_branch_name_when_available(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/my-branch\n")

    monkeypatch.setattr(version.subprocess, "run", fake_run)

    reloaded = importlib.reload(version)
    assert reloaded.__version__ == "0.1.0"
    assert reloaded.__display_version__ == "feature/my-branch"
