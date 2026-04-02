"""GitHub Releases-based update checks and installer downloads."""

from __future__ import annotations

import logging
import queue
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

GITHUB_OWNER = "aquarion"
GITHUB_REPO = "euterpium"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT = (5, 30)


class UpdateError(RuntimeError):
    """Raised when update checking or download fails."""


@dataclass(frozen=True)
class AvailableUpdate:
    version: str
    release_url: str
    installer_name: str
    installer_url: str


def normalize_version(version: str) -> tuple[int, int, int]:
    """Convert a tag or version string into a comparable 3-part tuple."""
    parts = re.findall(r"\d+", version)
    if not parts:
        raise ValueError(f"Unsupported version string: {version!r}")

    numbers = [int(part) for part in parts[:3]]
    while len(numbers) < 3:
        numbers.append(0)

    return tuple(numbers)


def is_newer_version(current_version: str, candidate_version: str) -> bool:
    """True when the candidate version is newer than the current version."""
    return normalize_version(candidate_version) > normalize_version(current_version)


def find_installer_asset(assets: list[dict]) -> dict | None:
    """Choose the preferred Windows installer asset from a GitHub release."""
    executables = [asset for asset in assets if asset.get("name", "").lower().endswith(".exe")]
    if not executables:
        return None

    preferred = [
        asset
        for asset in executables
        if any(keyword in asset.get("name", "").lower() for keyword in ("setup", "installer"))
    ]

    return (preferred or executables)[0]


def parse_latest_release(release: dict, current_version: str) -> AvailableUpdate | None:
    """Convert GitHub release JSON into an installable update, if newer."""
    if release.get("draft"):
        return None

    tag_name = release.get("tag_name")
    if not tag_name or not is_newer_version(current_version, tag_name):
        return None

    asset = find_installer_asset(release.get("assets", []))
    if not asset:
        raise UpdateError("Latest release does not contain a Windows installer")

    download_url = asset.get("browser_download_url")
    name = asset.get("name")
    if not download_url or not name:
        raise UpdateError("Latest release installer asset is missing download metadata")

    return AvailableUpdate(
        version=tag_name.lstrip("v"),
        release_url=release.get("html_url", ""),
        installer_name=name,
        installer_url=download_url,
    )


def fetch_latest_update(current_version: str) -> AvailableUpdate | None:
    """Query GitHub Releases and return the newest available installer update."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{GITHUB_REPO}-updater",
    }

    try:
        response = requests.get(LATEST_RELEASE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise UpdateError(f"Unable to reach GitHub Releases: {exc}") from exc
    except ValueError as exc:
        raise UpdateError("GitHub Releases returned invalid JSON") from exc

    return parse_latest_release(payload, current_version)


def download_installer(update: AvailableUpdate, destination_dir: str | Path | None = None) -> Path:
    """Download the installer for the given update and return the local file path."""
    target_dir = Path(destination_dir or tempfile.mkdtemp(prefix="euterpium-update-"))
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / update.installer_name

    try:
        response = requests.get(update.installer_url, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        with target_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    handle.write(chunk)
    except requests.RequestException as exc:
        raise UpdateError(f"Failed to download installer: {exc}") from exc
    except OSError as exc:
        raise UpdateError(f"Failed to save installer: {exc}") from exc

    return target_path


def launch_installer(installer_path: str | Path) -> None:
    """Launch the downloaded installer without blocking the main application."""
    path = Path(installer_path)
    try:
        subprocess.Popen([str(path)], close_fds=True)
    except OSError as exc:
        raise UpdateError(f"Failed to launch installer: {exc}") from exc


class UpdateManager:
    """Coordinate background update checks and installer launches."""

    def __init__(self, event_queue: queue.Queue, current_version: str):
        self.event_queue = event_queue
        self.current_version = current_version
        self._lock = threading.Lock()
        self._available_update: AvailableUpdate | None = None
        self._check_in_progress = False
        self._install_in_progress = False

    def _emit(self, event_type: str, *args) -> None:
        self.event_queue.put((event_type, *args))

    def get_available_update(self) -> AvailableUpdate | None:
        with self._lock:
            return self._available_update

    def check_for_updates(self, manual: bool = False) -> None:
        with self._lock:
            if self._check_in_progress:
                if manual:
                    self._emit("status", "Update check already in progress")
                return
            self._check_in_progress = True

        threading.Thread(target=self._check_worker, args=(manual,), daemon=True).start()

    def _check_worker(self, manual: bool) -> None:
        try:
            if manual:
                self._emit("status", "Checking for updates...")

            update = fetch_latest_update(self.current_version)
            with self._lock:
                self._available_update = update

            if update:
                self._emit("update_available", update)
            elif manual:
                self._emit("status", f"Euterpium {self.current_version} is up to date")
        except UpdateError as exc:
            logger.warning("Update check failed: %s", exc)
            if manual:
                self._emit("error", f"Update check failed: {exc}")
        finally:
            with self._lock:
                self._check_in_progress = False

    def install_available_update(self) -> None:
        with self._lock:
            if self._install_in_progress:
                self._emit("status", "Update installation already in progress")
                return

            update = self._available_update
            if update is None:
                self._emit("status", "No update available")
                return

            self._install_in_progress = True

        threading.Thread(target=self._install_worker, args=(update,), daemon=True).start()

    def _install_worker(self, update: AvailableUpdate) -> None:
        try:
            self._emit("status", f"Downloading Euterpium {update.version} installer...")
            installer_path = download_installer(update)
            launch_installer(installer_path)
            self._emit("update_installer_launched", update, str(installer_path))
        except UpdateError as exc:
            logger.warning("Update install failed: %s", exc)
            self._emit("error", f"Update install failed: {exc}")
        finally:
            with self._lock:
                self._install_in_progress = False
