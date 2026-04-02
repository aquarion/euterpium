"""GitHub Releases-based update checks and installer downloads."""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

GITHUB_OWNER = "aquarion"
GITHUB_REPO = "euterpium"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT = (5, 30)
UPDATE_TEMP_DIR_PREFIX = "euterpium-update-"


class UpdateError(RuntimeError):
    """Raised when update checking or download fails."""


def cleanup_stale_update_dirs(max_age_seconds: int = 24 * 60 * 60) -> int:
    """Delete stale updater temp directories from previous runs.

    Returns the number of directories successfully removed.
    """
    now = time.time()
    temp_root = Path(tempfile.gettempdir())
    removed_count = 0

    for path in temp_root.glob(f"{UPDATE_TEMP_DIR_PREFIX}*"):
        if not path.is_dir():
            continue
        try:
            age_seconds = now - path.stat().st_mtime
        except OSError:
            continue
        if age_seconds < max_age_seconds:
            continue
        try:
            shutil.rmtree(path, ignore_errors=False)
            removed_count += 1
        except OSError:
            continue

    return removed_count


@dataclass(frozen=True)
class AvailableUpdate:
    version: str
    release_url: str
    installer_name: str
    installer_url: str
    checksum_url: str | None = None


def normalize_version(version: str) -> tuple[int, int, int]:
    """Convert a tag or version string into a comparable 3-part tuple."""
    parts = re.findall(r"\d+", version)
    if not parts:
        raise ValueError(f"Unsupported version string: {version!r}")

    numbers = [int(part) for part in parts[:3]]
    while len(numbers) < 3:
        numbers.append(0)

    return (numbers[0], numbers[1], numbers[2])


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


def find_checksum_asset(assets: list[dict], installer_name: str) -> dict | None:
    """Return the SHA256 sidecar asset for the given installer filename, if present."""
    expected = (installer_name + ".sha256").lower()
    return next((a for a in assets if a.get("name", "").lower() == expected), None)


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

    _validate_installer_url(download_url)

    checksum_url: str | None = None
    checksum_asset = find_checksum_asset(release.get("assets", []), name)
    if checksum_asset:
        raw_checksum_url = checksum_asset.get("browser_download_url")
        if raw_checksum_url:
            try:
                _validate_installer_url(raw_checksum_url)
                checksum_url = raw_checksum_url
            except UpdateError:
                logger.warning("Checksum asset URL failed validation; skipping verification")

    return AvailableUpdate(
        version=tag_name.lstrip("v"),
        release_url=release.get("html_url", ""),
        installer_name=name,
        installer_url=download_url,
        checksum_url=checksum_url,
    )


_ALLOWED_INSTALLER_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
    }
)


def _validate_installer_url(url: str) -> None:
    """Raise UpdateError if the installer URL is not a safe HTTPS GitHub URL."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UpdateError(f"Installer URL must use HTTPS, got: {parsed.scheme!r}")
    if parsed.hostname not in _ALLOWED_INSTALLER_HOSTS:
        raise UpdateError(f"Installer URL host {parsed.hostname!r} is not in the allowed list")


def fetch_latest_update(current_version: str) -> AvailableUpdate | None:
    """Query GitHub Releases and return the newest available installer update."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{GITHUB_REPO}-updater",
    }

    try:
        with requests.get(LATEST_RELEASE_URL, headers=headers, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            payload = response.json()
    except requests.RequestException as exc:
        raise UpdateError(f"Unable to reach GitHub Releases: {exc}") from exc
    except ValueError as exc:
        raise UpdateError("GitHub Releases returned invalid JSON") from exc

    return parse_latest_release(payload, current_version)


def download_installer(update: AvailableUpdate, destination_dir: str | Path) -> Path:
    """Download the installer for the given update and return the local file path."""
    # Validate the URL even if the caller didn't go through parse_latest_release().
    _validate_installer_url(update.installer_url)

    target_dir = Path(destination_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize to a plain filename to prevent path traversal from remote metadata.
    # Also explicitly reject backslashes — on non-Windows, Path().name does not
    # treat '\' as a separator, so "..\\evil.exe" would pass the .name check.
    installer_name = Path(update.installer_name).name
    if (
        not installer_name
        or installer_name != update.installer_name
        or "\\" in update.installer_name
    ):
        raise UpdateError(
            f"Invalid installer name received from update metadata: {update.installer_name!r}"
        )
    target_path = target_dir / installer_name

    try:
        with requests.get(update.installer_url, stream=True, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            with target_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        handle.write(chunk)
    except requests.RequestException as exc:
        raise UpdateError(f"Failed to download installer: {exc}") from exc
    except OSError as exc:
        raise UpdateError(f"Failed to save installer: {exc}") from exc

    if update.checksum_url:
        try:
            with requests.get(update.checksum_url, timeout=REQUEST_TIMEOUT) as checksum_response:
                checksum_response.raise_for_status()
                checksum_text = checksum_response.text
        except requests.RequestException as exc:
            target_path.unlink(missing_ok=True)
            raise UpdateError(f"Failed to fetch installer checksum: {exc}") from exc

        # Accept both bare hex digest and "<hash>  <filename>" shasum format.
        parts = checksum_text.split()
        if not parts:
            target_path.unlink(missing_ok=True)
            raise UpdateError("Installer checksum file is empty or invalid")
        expected_sha256 = parts[0].lower()

        # Hash in chunks to avoid loading the full installer into memory.
        sha256 = hashlib.sha256()
        with target_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                sha256.update(chunk)
        actual_sha256 = sha256.hexdigest()

        if actual_sha256 != expected_sha256:
            target_path.unlink(missing_ok=True)
            raise UpdateError(
                f"Installer checksum mismatch — the download may be corrupt or tampered with. "
                f"Expected {expected_sha256!r}, got {actual_sha256!r}"
            )

    return target_path


def launch_installer(installer_path: str | Path) -> None:
    """Launch the downloaded installer without blocking the main application."""
    path = Path(installer_path)
    try:
        os.startfile(str(path))  # Windows-only; idiomatic way to run an installer
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

            # Always emit update_checked so the UI can clear any stale update state.
            self._emit("update_checked", update)
            if update:
                self._emit("update_available", update)
            elif manual:
                self._emit("status", f"Euterpium {self.current_version} is up to date")
        except UpdateError as exc:
            logger.warning("Update check failed: %s", exc)
            # Clear stale update state so the UI doesn't keep showing an outdated
            # "Install update" item after a failed check.
            with self._lock:
                self._available_update = None
            self._emit("update_checked", None)
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
        tmp_dir = Path(tempfile.mkdtemp(prefix=UPDATE_TEMP_DIR_PREFIX))
        try:
            self._emit("status", f"Downloading Euterpium {update.version} installer...")
            installer_path = download_installer(update, tmp_dir)
            launch_installer(installer_path)
            self._emit("update_installer_launched", update, str(installer_path))
        except UpdateError as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.warning("Update install failed: %s", exc)
            self._emit("error", f"Update install failed: {exc}")
        finally:
            with self._lock:
                self._install_in_progress = False
