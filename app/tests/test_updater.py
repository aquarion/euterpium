import hashlib
import queue
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

import updater

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="os.startfile is Windows-only")


def test_normalize_version_accepts_tag_prefix():
    assert updater.normalize_version("v1.2.3") == (1, 2, 3)


def test_is_newer_version_detects_update():
    assert updater.is_newer_version("0.1.0", "v0.2.0") is True


def test_is_newer_version_ignores_same_release():
    assert updater.is_newer_version("0.2.0", "v0.2.0") is False


def test_find_installer_asset_prefers_setup_exe():
    asset = updater.find_installer_asset(
        [
            {"name": "euterpium-v0.2.0-windows.zip"},
            {"name": "euterpium-v0.2.0-setup.exe", "browser_download_url": "https://a"},
            {"name": "euterpium-v0.2.0.exe", "browser_download_url": "https://b"},
        ]
    )

    assert asset["name"] == "euterpium-v0.2.0-setup.exe"


def test_find_checksum_asset_finds_sidecar():
    assets = [
        {"name": "euterpium-v0.2.0-setup.exe", "browser_download_url": "https://a"},
        {"name": "euterpium-v0.2.0-setup.exe.sha256", "browser_download_url": "https://b"},
    ]
    asset = updater.find_checksum_asset(assets, "euterpium-v0.2.0-setup.exe")
    assert asset is not None
    assert asset["browser_download_url"] == "https://b"


def test_find_checksum_asset_returns_none_when_absent():
    assets = [{"name": "euterpium-v0.2.0-setup.exe", "browser_download_url": "https://a"}]
    assert updater.find_checksum_asset(assets, "euterpium-v0.2.0-setup.exe") is None


def test_parse_latest_release_returns_none_when_not_newer():
    release = {"tag_name": "v0.1.0", "assets": []}
    assert updater.parse_latest_release(release, "0.1.0") is None


def test_parse_latest_release_raises_without_installer():
    release = {"tag_name": "v0.2.0", "assets": [{"name": "euterpium-v0.2.0.zip"}]}

    with pytest.raises(updater.UpdateError):
        updater.parse_latest_release(release, "0.1.0")


def test_parse_latest_release_returns_available_update():
    release = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/aquarion/euterpium/releases/tag/v0.2.0",
        "assets": [
            {
                "name": "euterpium-v0.2.0-setup.exe",
                "browser_download_url": "https://github.com/download/setup.exe",
            }
        ],
    }

    update = updater.parse_latest_release(release, "0.1.0")

    assert update is not None
    assert update.version == "0.2.0"
    assert update.installer_name == "euterpium-v0.2.0-setup.exe"
    assert update.checksum_url is None


def test_parse_latest_release_includes_checksum_url():
    release = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/aquarion/euterpium/releases/tag/v0.2.0",
        "assets": [
            {
                "name": "euterpium-v0.2.0-setup.exe",
                "browser_download_url": "https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe",
            },
            {
                "name": "euterpium-v0.2.0-setup.exe.sha256",
                "browser_download_url": "https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe.sha256",
            },
        ],
    }

    update = updater.parse_latest_release(release, "0.1.0")

    assert update is not None
    assert (
        update.checksum_url
        == "https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe.sha256"
    )


def test_fetch_latest_update_uses_github_response(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "tag_name": "v0.3.0",
                "html_url": "https://example.com/release",
                "assets": [
                    {
                        "name": "euterpium-v0.3.0-setup.exe",
                        "browser_download_url": "https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.3.0/euterpium-v0.3.0-setup.exe",
                    }
                ],
            }

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: Response())

    update = updater.fetch_latest_update("0.2.0")

    assert update is not None
    assert update.version == "0.3.0"


def test_download_installer_writes_file(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield b"hello"
            yield b"world"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: Response())
    update = updater.AvailableUpdate(
        version="0.3.0",
        release_url="https://github.com/aquarion/euterpium/releases/tag/v0.3.0",
        installer_name="euterpium-v0.3.0-setup.exe",
        installer_url="https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.3.0/euterpium-v0.3.0-setup.exe",
    )

    path = updater.download_installer(update, tmp_path)

    assert path == Path(tmp_path) / "euterpium-v0.3.0-setup.exe"
    assert path.read_bytes() == b"helloworld"


def test_download_installer_verifies_correct_checksum(monkeypatch, tmp_path):
    content = b"helloworld"
    expected_hash = hashlib.sha256(content).hexdigest()

    class InstallerResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class ChecksumResponse:
        text = expected_hash

        def raise_for_status(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_get(url, **kwargs):
        return ChecksumResponse() if "sha256" in url else InstallerResponse()

    monkeypatch.setattr(updater.requests, "get", fake_get)
    update = updater.AvailableUpdate(
        version="0.3.0",
        release_url="https://github.com/aquarion/euterpium/releases/tag/v0.3.0",
        installer_name="euterpium-v0.3.0-setup.exe",
        installer_url="https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.3.0/euterpium-v0.3.0-setup.exe",
        checksum_url="https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.3.0/euterpium-v0.3.0-setup.exe.sha256",
    )

    path = updater.download_installer(update, tmp_path)
    assert path.read_bytes() == content


def test_download_installer_rejects_bad_checksum(monkeypatch, tmp_path):
    content = b"helloworld"

    class InstallerResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class ChecksumResponse:
        text = "0" * 64  # deliberately wrong hash

        def raise_for_status(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_get(url, **kwargs):
        return ChecksumResponse() if "sha256" in url else InstallerResponse()

    monkeypatch.setattr(updater.requests, "get", fake_get)
    update = updater.AvailableUpdate(
        version="0.3.0",
        release_url="https://github.com/aquarion/euterpium/releases/tag/v0.3.0",
        installer_name="euterpium-v0.3.0-setup.exe",
        installer_url="https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.3.0/euterpium-v0.3.0-setup.exe",
        checksum_url="https://objects.githubusercontent.com/aquarion/euterpium/releases/download/v0.3.0/euterpium-v0.3.0-setup.exe.sha256",
    )

    with pytest.raises(updater.UpdateError, match="checksum mismatch"):
        updater.download_installer(update, tmp_path)
    # Downloaded file must be deleted on mismatch
    assert not (tmp_path / "euterpium-v0.3.0-setup.exe").exists()


def test_validate_installer_url_accepts_github_host():
    updater._validate_installer_url(
        "https://objects.githubusercontent.com/github-production-release-asset/v0.2.0/setup.exe"
    )


def test_validate_installer_url_rejects_http():
    with pytest.raises(updater.UpdateError, match="HTTPS"):
        updater._validate_installer_url(
            "http://github.com/aquarion/euterpium/releases/download/v0.2.0/setup.exe"
        )


def test_validate_installer_url_rejects_unknown_host():
    with pytest.raises(updater.UpdateError, match="allowed list"):
        updater._validate_installer_url("https://evil.example.com/setup.exe")


def test_download_installer_rejects_path_traversal(monkeypatch, tmp_path):
    update = updater.AvailableUpdate(
        version="0.3.0",
        release_url="https://example.com/release",
        installer_name="..\\..\\evil.exe",
        installer_url="https://github.com/aquarion/euterpium/releases/download/v0.3.0/evil.exe",
    )

    with pytest.raises(updater.UpdateError, match="Invalid installer name"):
        updater.download_installer(update, tmp_path)


def test_update_manager_reports_available_update(monkeypatch):
    events = []
    event_queue = type("Queue", (), {"put": lambda self, item: events.append(item)})()
    manager = updater.UpdateManager(event_queue=event_queue, current_version="0.1.0")
    expected_update = updater.AvailableUpdate(
        version="0.2.0",
        release_url="https://example.com/release",
        installer_name="euterpium-v0.2.0-setup.exe",
        installer_url="https://example.com/setup.exe",
    )

    monkeypatch.setattr(updater, "fetch_latest_update", lambda current_version: expected_update)

    manager._check_worker(manual=True)

    assert ("update_checked", expected_update) in events
    assert ("update_available", expected_update) in events


def test_update_manager_emits_update_checked_on_error(monkeypatch):
    events = []
    event_queue = type("Queue", (), {"put": lambda self, item: events.append(item)})()
    manager = updater.UpdateManager(event_queue=event_queue, current_version="0.1.0")

    def raise_error(current_version):
        raise updater.UpdateError("network failure")

    monkeypatch.setattr(updater, "fetch_latest_update", raise_error)

    manager._check_worker(manual=False)

    # update_checked must always be emitted so the UI can clear stale state
    assert ("update_checked", None) in events
    # No update_available should be emitted on error
    assert not any(e[0] == "update_available" for e in events)


# ── cleanup_stale_update_dirs ─────────────────────────────────────────────────


def test_cleanup_removes_old_dirs(tmp_path):
    old_dir = tmp_path / f"{updater.UPDATE_TEMP_DIR_PREFIX}old"
    old_dir.mkdir()
    # Set mtime to 2 days ago
    old_time = time.time() - 2 * 24 * 60 * 60
    import os

    os.utime(old_dir, (old_time, old_time))

    with patch("updater.tempfile.gettempdir", return_value=str(tmp_path)):
        removed = updater.cleanup_stale_update_dirs(max_age_seconds=60 * 60)

    assert removed == 1
    assert not old_dir.exists()


def test_cleanup_skips_fresh_dirs(tmp_path):
    fresh_dir = tmp_path / f"{updater.UPDATE_TEMP_DIR_PREFIX}fresh"
    fresh_dir.mkdir()

    with patch("updater.tempfile.gettempdir", return_value=str(tmp_path)):
        removed = updater.cleanup_stale_update_dirs(max_age_seconds=24 * 60 * 60)

    assert removed == 0
    assert fresh_dir.exists()


def test_cleanup_skips_non_dirs(tmp_path):
    old_file = tmp_path / f"{updater.UPDATE_TEMP_DIR_PREFIX}file.txt"
    old_file.write_text("x")
    old_time = time.time() - 2 * 24 * 60 * 60
    import os

    os.utime(old_file, (old_time, old_time))

    with patch("updater.tempfile.gettempdir", return_value=str(tmp_path)):
        removed = updater.cleanup_stale_update_dirs(max_age_seconds=60 * 60)

    assert removed == 0


# ── normalize_version ─────────────────────────────────────────────────────────


def test_normalize_version_raises_on_no_digits():
    with pytest.raises(ValueError, match="Unsupported version string"):
        updater.normalize_version("no-digits-here")


def test_normalize_version_pads_short_version():
    assert updater.normalize_version("1.2") == (1, 2, 0)


# ── parse_latest_release ──────────────────────────────────────────────────────


def test_parse_latest_release_returns_none_for_draft():
    release = {
        "draft": True,
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "euterpium-v0.2.0-setup.exe",
                "browser_download_url": "https://github.com/download/setup.exe",
            }
        ],
    }
    assert updater.parse_latest_release(release, "0.1.0") is None


def test_parse_latest_release_raises_on_missing_download_url():
    release = {
        "tag_name": "v0.2.0",
        "assets": [{"name": "euterpium-v0.2.0-setup.exe"}],  # no browser_download_url
    }
    with pytest.raises(updater.UpdateError):
        updater.parse_latest_release(release, "0.1.0")


def test_parse_latest_release_skips_checksum_with_bad_url():
    release = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/aquarion/euterpium/releases/tag/v0.2.0",
        "assets": [
            {
                "name": "euterpium-v0.2.0-setup.exe",
                "browser_download_url": "https://github.com/download/setup.exe",
            },
            {
                "name": "euterpium-v0.2.0-setup.exe.sha256",
                "browser_download_url": "https://evil.example.com/checksums/setup.exe.sha256",
            },
        ],
    }
    update = updater.parse_latest_release(release, "0.1.0")
    # Bad checksum URL should be silently skipped, not raise
    assert update is not None
    assert update.checksum_url is None


# ── fetch_latest_update ───────────────────────────────────────────────────────


def test_fetch_latest_update_raises_on_invalid_json(monkeypatch):
    class BadJsonResponse:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("not json")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(updater.requests, "get", lambda *a, **kw: BadJsonResponse())

    with pytest.raises(updater.UpdateError, match="invalid JSON"):
        updater.fetch_latest_update("0.1.0")


def test_fetch_latest_update_raises_on_network_error(monkeypatch):
    def raise_exc(*a, **kw):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(updater.requests, "get", raise_exc)

    with pytest.raises(updater.UpdateError, match="Unable to reach"):
        updater.fetch_latest_update("0.1.0")


# ── download_installer error paths ───────────────────────────────────────────


def test_download_installer_raises_on_request_error(monkeypatch, tmp_path):
    def raise_exc(*a, **kw):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(updater.requests, "get", raise_exc)
    update = updater.AvailableUpdate(
        version="0.2.0",
        release_url="https://github.com/aquarion/euterpium/releases/tag/v0.2.0",
        installer_name="euterpium-v0.2.0-setup.exe",
        installer_url="https://github.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe",
    )
    with pytest.raises(updater.UpdateError, match="Failed to download"):
        updater.download_installer(update, tmp_path)


def test_download_installer_raises_on_empty_checksum(monkeypatch, tmp_path):
    class InstallerResponse:
        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=0):
            yield b"content"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class EmptyChecksumResponse:
        text = ""

        def raise_for_status(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda url, **kw: EmptyChecksumResponse() if "sha256" in url else InstallerResponse(),
    )
    update = updater.AvailableUpdate(
        version="0.2.0",
        release_url="https://github.com/aquarion/euterpium/releases/tag/v0.2.0",
        installer_name="euterpium-v0.2.0-setup.exe",
        installer_url="https://github.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe",
        checksum_url="https://github.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe.sha256",
    )
    with pytest.raises(updater.UpdateError, match="empty or invalid"):
        updater.download_installer(update, tmp_path)
    assert not (tmp_path / "euterpium-v0.2.0-setup.exe").exists()


def test_download_installer_raises_on_checksum_fetch_error(monkeypatch, tmp_path):
    class InstallerResponse:
        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=0):
            yield b"content"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_get(url, **kw):
        if "sha256" in url:
            raise requests.RequestException("checksum fetch failed")
        return InstallerResponse()

    monkeypatch.setattr(updater.requests, "get", fake_get)
    update = updater.AvailableUpdate(
        version="0.2.0",
        release_url="https://github.com/aquarion/euterpium/releases/tag/v0.2.0",
        installer_name="euterpium-v0.2.0-setup.exe",
        installer_url="https://github.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe",
        checksum_url="https://github.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe.sha256",
    )
    with pytest.raises(updater.UpdateError, match="Failed to fetch.*checksum"):
        updater.download_installer(update, tmp_path)
    assert not (tmp_path / "euterpium-v0.2.0-setup.exe").exists()


# ── launch_installer ──────────────────────────────────────────────────────────


@windows_only
def test_launch_installer_calls_startfile(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(updater.os, "startfile", lambda p: launched.append(p))
    fake_installer = tmp_path / "setup.exe"
    fake_installer.write_bytes(b"")
    updater.launch_installer(fake_installer)
    assert launched == [str(fake_installer)]


@windows_only
def test_launch_installer_raises_on_error(monkeypatch, tmp_path):
    def raise_exc(p):
        raise OSError("cannot launch")

    monkeypatch.setattr(updater.os, "startfile", raise_exc)
    with pytest.raises(updater.UpdateError, match="Failed to launch"):
        updater.launch_installer(tmp_path / "setup.exe")


# ── UpdateManager ─────────────────────────────────────────────────────────────


def _make_manager(monkeypatch=None):
    q = queue.Queue()
    return updater.UpdateManager(event_queue=q, current_version="0.1.0"), q


def test_get_available_update_initially_none():
    manager, _ = _make_manager()
    assert manager.get_available_update() is None


def test_check_for_updates_deduplicates(monkeypatch):
    manager, q = _make_manager()
    manager._check_in_progress = True
    # Should return early without starting a thread
    manager.check_for_updates(manual=True)
    assert q.get_nowait() == ("status", "Update check already in progress")


def test_check_worker_emits_status_when_up_to_date(monkeypatch):
    manager, q = _make_manager()
    monkeypatch.setattr(updater, "fetch_latest_update", lambda v: None)
    manager._check_worker(manual=True)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e[0] == "status" and "up to date" in e[1] for e in events)


def test_check_worker_emits_error_on_failure_when_manual(monkeypatch):
    manager, q = _make_manager()
    monkeypatch.setattr(
        updater, "fetch_latest_update", lambda v: (_ for _ in ()).throw(updater.UpdateError("fail"))
    )
    manager._check_worker(manual=True)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e[0] == "error" for e in events)


def test_install_available_update_returns_early_when_in_progress():
    manager, q = _make_manager()
    manager._install_in_progress = True
    manager.install_available_update()
    event = q.get_nowait()
    assert event == ("status", "Update installation already in progress")


def test_install_available_update_returns_early_when_no_update():
    manager, q = _make_manager()
    manager.install_available_update()
    event = q.get_nowait()
    assert event == ("status", "No update available")


def test_install_worker_emits_launched_on_success(monkeypatch, tmp_path):
    manager, q = _make_manager()
    update = updater.AvailableUpdate(
        version="0.2.0",
        release_url="https://github.com/aquarion/euterpium/releases/tag/v0.2.0",
        installer_name="euterpium-v0.2.0-setup.exe",
        installer_url="https://github.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe",
    )
    update_tmp = tmp_path / "update-tmp"
    update_tmp.mkdir()
    fake_path = update_tmp / "setup.exe"
    monkeypatch.setattr(updater, "download_installer", lambda u, d: fake_path)
    monkeypatch.setattr(updater, "launch_installer", lambda p: None)
    monkeypatch.setattr(updater.tempfile, "mkdtemp", lambda prefix: str(update_tmp))

    manager._install_worker(update)

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e[0] == "update_installer_launched" for e in events)


def test_install_worker_emits_error_on_failure(monkeypatch, tmp_path):
    manager, q = _make_manager()
    update = updater.AvailableUpdate(
        version="0.2.0",
        release_url="https://github.com/aquarion/euterpium/releases/tag/v0.2.0",
        installer_name="euterpium-v0.2.0-setup.exe",
        installer_url="https://github.com/aquarion/euterpium/releases/download/v0.2.0/euterpium-v0.2.0-setup.exe",
    )
    monkeypatch.setattr(
        updater,
        "download_installer",
        lambda u, d: (_ for _ in ()).throw(updater.UpdateError("download failed")),
    )
    update_tmp = tmp_path / "update-tmp"
    update_tmp.mkdir()
    monkeypatch.setattr(updater.tempfile, "mkdtemp", lambda prefix: str(update_tmp))

    manager._install_worker(update)

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e[0] == "error" for e in events)
