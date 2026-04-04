"""Runtime application version information."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _detect_git_branch() -> str | None:
    """Detect the current git branch name."""
    repo_root = Path(__file__).resolve().parent

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch and branch != "HEAD":
                return branch
    except (OSError, subprocess.SubprocessError):
        pass

    return None


__version__ = "0.1.0"

# In release builds, the workflow replaces __version__ with the actual version
# For development builds, show the git branch or "dev"
if __version__ != "0.1.0":
    __display_version__ = __version__
else:
    __display_version__ = _detect_git_branch() or "dev"
