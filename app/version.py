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


def _compute_display_version(version_str: str) -> str:
    """Compute display version based on the current version string.

    Args:
        version_str: The current __version__ value

    Returns:
        Display version string: version_str for releases, git branch or 'dev' for development
    """
    if version_str != DEV_VERSION:
        return version_str
    else:
        return _detect_git_branch() or "dev"


DEV_VERSION = "0.1.0"
# Keep this as a quoted string literal so the release workflow can replace it.
__version__ = "0.1.0"

# In release builds, the workflow replaces __version__ with the actual version.
# For development builds, show the git branch or "dev".
__display_version__ = _compute_display_version(__version__)
