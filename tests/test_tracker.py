# tests/test_tracker.py — Tracker logic (track deduplication)

import queue
import threading
import time
from unittest.mock import patch

import pytest

from tracker import Tracker


@pytest.fixture
def tracker():
    tracker = Tracker(queue.Queue())
    yield tracker
    # Clean up - stop tracker if running
    if tracker.is_running:
        tracker.stop()


@pytest.fixture
def running_tracker():
    tracker = Tracker(queue.Queue())
    tracker.start()
    yield tracker
    # Clean up - stop tracker
    tracker.stop()


# ── _tracks_are_same ──────────────────────────────────────────────────────────


def test_same_track_is_same(tracker):
    track = {"title": "It Overtakes Me", "artist": "The Flaming Lips"}
    assert tracker._tracks_are_same(track, track) is True


def test_identical_dicts_are_same(tracker):
    a = {"title": "Song", "artist": "Artist"}
    b = {"title": "Song", "artist": "Artist"}
    assert tracker._tracks_are_same(a, b) is True


def test_comparison_is_case_insensitive(tracker):
    a = {"title": "SONG", "artist": "ARTIST"}
    b = {"title": "song", "artist": "artist"}
    assert tracker._tracks_are_same(a, b) is True


def test_different_title_is_not_same(tracker):
    a = {"title": "Song A", "artist": "Artist"}
    b = {"title": "Song B", "artist": "Artist"}
    assert tracker._tracks_are_same(a, b) is False


def test_same_title_different_artist_is_same(tracker):
    """Different artists with same title should be considered the same track."""
    a = {"title": "Song", "artist": "Artist A"}
    b = {"title": "Song", "artist": "Artist B"}
    assert tracker._tracks_are_same(a, b) is True


def test_same_title_different_source_is_different(tracker):
    """Same title from different sources should be considered different tracks."""
    a = {"title": "Song", "source": "smtc"}
    b = {"title": "Song", "source": "acrcloud"}
    assert tracker._tracks_are_same(a, b) is False


def test_same_title_different_game_is_different(tracker):
    """Same title from different games should be considered different tracks."""
    a = {"title": "Song", "_game": {"display_name": "Game A"}}
    b = {"title": "Song", "_game": {"display_name": "Game B"}}
    assert tracker._tracks_are_same(a, b) is False


def test_same_title_one_game_missing_is_different(tracker):
    """Same title with only one having game info should be considered different track."""
    a = {"title": "Song", "_game": {"display_name": "Game A"}}
    b = {"title": "Song"}
    assert tracker._tracks_are_same(a, b) is False


def test_same_title_same_source_same_game_is_same(tracker):
    """Same title, source, and game should be considered same track."""
    a = {"title": "Song", "source": "acrcloud", "_game": {"display_name": "Game A"}}
    b = {"title": "Song", "source": "acrcloud", "_game": {"display_name": "Game A"}}
    assert tracker._tracks_are_same(a, b) is True


def test_none_first_arg_is_not_same(tracker):
    assert tracker._tracks_are_same(None, {"title": "Song", "artist": "A"}) is False


def test_none_second_arg_is_not_same(tracker):
    assert tracker._tracks_are_same({"title": "Song", "artist": "A"}, None) is False


def test_both_none_is_not_same(tracker):
    assert tracker._tracks_are_same(None, None) is False


def test_different_sources_are_not_same(tracker):
    # Tracks with identical title/artist but different source are NOT same
    a = {"title": "Song", "artist": "Artist", "source": "smtc", "album": "Album 1"}
    b = {"title": "Song", "artist": "Artist", "source": "acrcloud", "album": "Album 2"}
    assert tracker._tracks_are_same(a, b) is False


def test_smtc_excluded_state_transition_is_not_same(tracker):
    a = {"title": "Song", "source": "smtc", "source_app": "spotify.exe", "excluded": False}
    b = {"title": "Song", "source": "smtc", "source_app": "spotify.exe", "excluded": True}
    assert tracker._tracks_are_same(a, b) is False


# ── Manual Fingerprinting ────────────────────────────────────────────────────────


@patch("tracker.config.get_acrcloud_host")
@patch("tracker.config.acrcloud_is_configured")
def test_manual_fingerprint_requires_acrcloud_config(
    mock_is_configured, mock_host, running_tracker
):
    """Manual fingerprint should fail if ACRCloud is not configured."""
    # Mock missing configuration
    mock_host.return_value = None
    mock_is_configured.return_value = False

    events = []

    def capture_events():
        while not running_tracker.event_queue.empty():
            events.append(running_tracker.event_queue.get())

    running_tracker.force_fingerprint()
    time.sleep(0.1)  # Let thread run
    capture_events()

    # Should emit error about missing ACRCloud config
    error_events = [e for e in events if e[0] == "error"]
    assert len(error_events) > 0
    assert "ACRCloud not fully configured" in error_events[0][1]


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
def test_manual_fingerprint_debouncing(mock_is_configured, mock_host, running_tracker):
    """Multiple rapid manual fingerprint calls should be debounced."""
    events = []

    def capture_events():
        while not running_tracker.event_queue.empty():
            events.append(running_tracker.event_queue.get())

    # Start first fingerprint
    running_tracker.force_fingerprint()
    time.sleep(0.01)  # Small delay

    # Try to start second fingerprint (should be debounced)
    running_tracker.force_fingerprint()
    time.sleep(0.1)  # Let threads finish
    capture_events()

    # Should only see one "Manual fingerprinting requested" message
    status_events = [
        e for e in events if e[0] == "status" and "Manual fingerprinting requested" in e[1]
    ]
    assert len(status_events) == 1


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game")
@patch("tracker.get_smtc_track_sync")
def test_manual_fingerprint_smtc_fallback(
    mock_smtc, mock_game, mock_is_configured, mock_host, running_tracker
):
    """Manual fingerprint should fall back to SMTC when no game is running."""
    mock_game.return_value = None  # No game running
    mock_smtc.return_value = {"title": "SMTC Track", "source": "smtc"}

    events = []

    def capture_events():
        while not running_tracker.event_queue.empty():
            events.append(running_tracker.event_queue.get())

    running_tracker.force_fingerprint()
    time.sleep(0.1)  # Let thread run
    capture_events()

    # Should emit status about checking SMTC
    status_events = [e for e in events if e[0] == "status"]
    assert any("checking SMTC instead" in e[1] for e in status_events)


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game")
@patch("tracker.get_smtc_track_sync")
def test_manual_fingerprint_ignored_smtc_source_emits_debug_not_track(
    mock_smtc, mock_game, mock_is_configured, mock_host, running_tracker
):
    mock_game.return_value = None
    mock_smtc.return_value = {
        "source": "smtc",
        "source_app": "firefox.exe",
        "source_app_name": "firefox.exe",
        "excluded": True,
        "title": "Song",
        "artist": "Artist",
    }

    events = []

    def capture_events():
        while not running_tracker.event_queue.empty():
            events.append(running_tracker.event_queue.get())

    running_tracker.force_fingerprint()
    time.sleep(0.1)
    capture_events()

    assert not any(e[0] == "track" for e in events)
    assert any(e[0] == "status" and "Ignored source (firefox.exe)" in e[1] for e in events)
    assert any(e[0] == "delivery" and "excluded source" in e[1] for e in events)


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game")
@patch("tracker.capture_audio")
def test_manual_fingerprint_audio_capture_failure(
    mock_capture, mock_game, mock_is_configured, mock_host, running_tracker
):
    """Manual fingerprint should handle audio capture failures gracefully."""
    mock_game.return_value = {"display_name": "Test Game", "name": "test"}
    mock_capture.return_value = None  # Audio capture fails

    events = []

    def capture_events():
        while not running_tracker.event_queue.empty():
            events.append(running_tracker.event_queue.get())

    running_tracker.force_fingerprint()
    time.sleep(0.1)  # Let thread run
    capture_events()

    # Should emit error about failed audio capture
    error_events = [e for e in events if e[0] == "error"]
    assert any("Failed to capture audio" in e[1] for e in error_events)


def test_manual_fingerprint_thread_safety(tracker):
    """Manual fingerprint operations should be thread-safe."""
    # This test verifies that multiple threads can't access last_track simultaneously
    tracker.last_track = {"title": "Initial Track"}

    results = []

    def worker():
        with tracker._last_track_lock:
            current = tracker.last_track
            time.sleep(0.01)  # Simulate some work
            results.append(current)

    # Start multiple threads accessing last_track
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads should see the same initial track
    assert all(r == {"title": "Initial Track"} for r in results)
    assert len(results) == 5


def test_is_running_returns_bool_when_stopped(tracker):
    assert tracker.is_running is False
    assert isinstance(tracker.is_running, bool)


def test_emit_duplicate_track_once_per_same_track(tracker):
    track = {"source": "smtc", "title": "Song", "source_app": "spotify.exe"}

    tracker._emit_duplicate_track_once(track, game=None)
    tracker._emit_duplicate_track_once(track, game=None)

    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get())

    duplicate_events = [e for e in events if e[0] == "delivery" and "duplicate track" in e[1]]
    assert len(duplicate_events) == 1
