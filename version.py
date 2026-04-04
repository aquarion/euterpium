"""Runtime application version information."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _detect_git_branch() -> str | None:
    repo_root = Path(__file__).resolve().parent

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        return None

    return branch


__version__ = _detect_git_branch() or "dev"
