# tests/test_smtc.py — SMTC detection logic
#
# app_resolver tests were moved here historically; they live in test_app_resolver.py.
# This file covers smtc.get_smtc_track (async) and get_smtc_track_sync.
#
# winsdk is available on Windows — we patch MediaManager and MediaPlaybackStatus
# at the smtc module level rather than at import time.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import smtc as smtc_module
from smtc import get_smtc_track, get_smtc_track_sync

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_session(
    app_id="spotify.exe",
    title="Test Title",
    artist="Test Artist",
    album="Test Album",
    status=None,
):
    """Build a minimal mock SMTC session."""
    mock_info = MagicMock()
    mock_info.title = title
    mock_info.artist = artist
    mock_info.album_title = album

    mock_playback = MagicMock()
    # Default to a status value that is neither STOPPED nor CLOSED
    if status is None:
        status = object()  # unique sentinel — won't equal STOPPED or CLOSED
    mock_playback.playback_status = status

    mock_session = MagicMock()
    mock_session.source_app_user_model_id = app_id
    mock_session.try_get_media_properties_async = AsyncMock(return_value=mock_info)
    mock_session.get_playback_info = MagicMock(return_value=mock_playback)

    return mock_session


def _make_manager(session):
    """Build a mock MediaManager that returns the given session."""
    mock_sessions = MagicMock()
    mock_sessions.get_current_session = MagicMock(return_value=session)
    mock_manager = MagicMock()
    mock_manager.request_async = AsyncMock(return_value=mock_sessions)
    return mock_manager


# ── WINSDK unavailable ────────────────────────────────────────────────────────


def test_get_smtc_track_returns_none_when_winsdk_unavailable():
    with patch.object(smtc_module, "WINSDK_AVAILABLE", False):
        result = asyncio.run(get_smtc_track())
    assert result is None


def test_get_smtc_track_sync_returns_none_when_winsdk_unavailable():
    with patch.object(smtc_module, "WINSDK_AVAILABLE", False):
        result = get_smtc_track_sync()
    assert result is None


# ── No active session ─────────────────────────────────────────────────────────


def test_get_smtc_track_returns_none_when_no_session():
    mock_sessions = MagicMock()
    mock_sessions.get_current_session = MagicMock(return_value=None)
    mock_manager = MagicMock()
    mock_manager.request_async = AsyncMock(return_value=mock_sessions)

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", mock_manager),
    ):
        result = asyncio.run(get_smtc_track())
    assert result is None


# ── Playback status filtering ─────────────────────────────────────────────────


def test_get_smtc_track_returns_none_when_stopped():
    sentinel = object()
    session = _make_session(status=sentinel)
    manager = _make_manager(session)

    mock_status = MagicMock()
    mock_status.STOPPED = sentinel
    mock_status.CLOSED = object()  # different object — won't match

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
    ):
        result = asyncio.run(get_smtc_track())
    assert result is None


def test_get_smtc_track_returns_none_when_closed():
    sentinel = object()
    session = _make_session(status=sentinel)
    manager = _make_manager(session)

    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = sentinel

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
    ):
        result = asyncio.run(get_smtc_track())
    assert result is None


def test_get_smtc_track_returns_track_when_paused():
    """Paused sessions should still return a track (Apple Music quirk)."""
    paused = object()
    session = _make_session(status=paused)
    manager = _make_manager(session)

    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()
    mock_status.PAUSED = paused

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="spotify.exe"),
    ):
        result = asyncio.run(get_smtc_track())
    assert result is not None
    assert result["title"] == "Test Title"


# ── Normal track returned ─────────────────────────────────────────────────────


def test_get_smtc_track_returns_expected_fields():
    session = _make_session(app_id="spotify.exe", title="Song", artist="Artist", album="Album")
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="spotify.exe"),
    ):
        result = asyncio.run(get_smtc_track())

    assert result == {
        "source": "smtc",
        "source_app": "spotify.exe",
        "source_app_name": "spotify.exe",
        "title": "Song",
        "artist": "Artist",
        "album": "Album",
    }


def test_get_smtc_track_returns_none_when_no_title_or_artist():
    session = _make_session(title="", artist="")
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="app.exe"),
    ):
        result = asyncio.run(get_smtc_track())
    assert result is None


# ── Apple Music artist splitting ──────────────────────────────────────────────


def test_get_smtc_track_splits_apple_music_artist_album():
    """'Artist — Album' in the artist field should be split when album_title is empty."""
    session = _make_session(artist="Radiohead \u2014 OK Computer", album="")
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="applemusic.exe"),
    ):
        result = asyncio.run(get_smtc_track())

    assert result["artist"] == "Radiohead"
    assert result["album"] == "OK Computer"


def test_get_smtc_track_does_not_split_when_album_present():
    """If album_title is already populated, don't split the artist field."""
    session = _make_session(artist="Radiohead \u2014 OK Computer", album="OK Computer")
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="applemusic.exe"),
    ):
        result = asyncio.run(get_smtc_track())

    assert result["artist"] == "Radiohead \u2014 OK Computer"
    assert result["album"] == "OK Computer"


# ── ignored_apps / excluded ───────────────────────────────────────────────────


def test_get_smtc_track_marks_excluded_when_app_id_matches():
    session = _make_session(app_id="firefox.exe")
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="firefox.exe"),
    ):
        result = asyncio.run(get_smtc_track(ignored_apps=["firefox"]))

    assert result["excluded"] is True
    assert result["excluded_pattern"] == "firefox"
    assert result["source_app"] == "firefox.exe"


def test_get_smtc_track_marks_excluded_when_app_name_matches():
    """Exclusion should also trigger when the resolved app name matches."""
    session = _make_session(app_id="308046B0AF4A39CB")
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="firefox.exe"),
    ):
        result = asyncio.run(get_smtc_track(ignored_apps=["firefox"]))

    assert result["excluded"] is True


def test_get_smtc_track_not_excluded_when_no_match():
    session = _make_session(app_id="spotify.exe")
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="spotify.exe"),
    ):
        result = asyncio.run(get_smtc_track(ignored_apps=["firefox"]))

    assert "excluded" not in result


def test_get_smtc_track_ignored_apps_none_does_not_exclude():
    session = _make_session(app_id="spotify.exe")
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="spotify.exe"),
    ):
        result = asyncio.run(get_smtc_track(ignored_apps=None))

    assert "excluded" not in result


# ── Exception handling ────────────────────────────────────────────────────────


def test_get_smtc_track_returns_none_on_exception():
    mock_manager = MagicMock()
    mock_manager.request_async = AsyncMock(side_effect=RuntimeError("winsdk exploded"))

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", mock_manager),
    ):
        result = asyncio.run(get_smtc_track())
    assert result is None


# ── get_smtc_track_sync ───────────────────────────────────────────────────────


def test_get_smtc_track_sync_returns_track_on_win32():
    session = _make_session()
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="spotify.exe"),
        patch("smtc.sys.platform", "win32"),
    ):
        result = get_smtc_track_sync()

    assert result is not None
    assert result["title"] == "Test Title"


def test_get_smtc_track_sync_uses_generic_loop_on_non_win32():
    session = _make_session()
    manager = _make_manager(session)
    mock_status = MagicMock()
    mock_status.STOPPED = object()
    mock_status.CLOSED = object()

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", manager),
        patch.object(smtc_module, "MediaPlaybackStatus", mock_status),
        patch("smtc.resolve_app_name", return_value="spotify.exe"),
        patch("smtc.sys.platform", "linux"),
    ):
        result = get_smtc_track_sync()

    assert result is not None


def test_get_smtc_track_sync_returns_none_on_exception():
    mock_manager = MagicMock()
    mock_manager.request_async = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch.object(smtc_module, "WINSDK_AVAILABLE", True),
        patch.object(smtc_module, "MediaManager", mock_manager),
        patch("smtc.sys.platform", "win32"),
    ):
        result = get_smtc_track_sync()
    assert result is None
