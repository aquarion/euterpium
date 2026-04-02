from pathlib import Path

import pytest

import updater


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
