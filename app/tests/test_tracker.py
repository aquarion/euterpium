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
    """Tracker with background loop replaced by a no-op so tests don't touch live OS APIs."""
    tracker = Tracker(queue.Queue())
    tracker._run = lambda: tracker._stop_event.wait()
    tracker.start()
    yield tracker
    tracker.stop()


def _wait_for_manual_fingerprint(tracker, timeout=2.0):
    """Wait for an in-progress manual fingerprint to finish, then drain the event queue."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with tracker._last_track_lock:
            if not tracker._manual_fingerprint_running:
                break
        time.sleep(0.005)
    else:
        pytest.fail("Manual fingerprint did not complete within timeout")
    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get_nowait())
    return events


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

    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

    # Should emit error about missing ACRCloud config
    error_events = [e for e in events if e[0] == "error"]
    assert len(error_events) > 0
    assert "ACRCloud not fully configured" in error_events[0][1]


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game", return_value=None)
@patch("tracker.get_smtc_track_sync", return_value=None)
def test_manual_fingerprint_debouncing(
    mock_smtc, mock_game, mock_is_configured, mock_host, running_tracker
):
    """Multiple rapid manual fingerprint calls should be debounced."""
    # flag is set synchronously in force_fingerprint, so second call sees it immediately
    running_tracker.force_fingerprint()
    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

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

    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

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

    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

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

    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

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


@patch("tracker.config.api_is_configured", return_value=False)
@patch("tracker.post_now_playing")
def test_post_now_playing_with_status_not_configured_emits_warn(
    mock_post, mock_api_configured, tracker
):
    tracker._post_now_playing_with_status({"source": "smtc", "title": "Song"}, game=None)

    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get())

    assert any(e[0] == "delivery" and "not configured" in e[1] and e[2] == "warn" for e in events)


# ── Public controls (additional) ─────────────────────────────────────────────


def test_start_when_already_running_is_noop(running_tracker):
    running_tracker.start()  # second call — thread already alive
    events = []
    while not running_tracker.event_queue.empty():
        events.append(running_tracker.event_queue.get_nowait())
    started = [e for e in events if e[0] == "status" and e[1] == "Tracker started"]
    assert len(started) == 1


def test_pause_emits_status(running_tracker):
    running_tracker.pause()
    events = []
    while not running_tracker.event_queue.empty():
        events.append(running_tracker.event_queue.get_nowait())
    assert any(e[0] == "status" and "paused" in e[1] for e in events)
    assert running_tracker._paused is True


def test_resume_emits_status(running_tracker):
    running_tracker.pause()
    running_tracker.resume()
    events = []
    while not running_tracker.event_queue.empty():
        events.append(running_tracker.event_queue.get_nowait())
    assert any(e[0] == "status" and "resumed" in e[1] for e in events)
    assert running_tracker._paused is False


def test_force_fingerprint_when_not_running_emits_error(tracker):
    tracker.force_fingerprint()
    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get_nowait())
    assert any(e[0] == "error" and "Tracker not running" in e[1] for e in events)


# ── _manual_fingerprint (game paths) ─────────────────────────────────────────


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game", return_value=None)
@patch("tracker.get_smtc_track_sync")
def test_manual_fingerprint_smtc_duplicate_track(
    mock_smtc, mock_game, mock_is_configured, mock_host, running_tracker
):
    """When the SMTC track matches last_track, emit 'Same track detected'."""
    track = {"title": "Same Track", "source": "smtc"}
    mock_smtc.return_value = track
    running_tracker.last_track = dict(track)

    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

    assert any(e[0] == "status" and "Same track detected" in e[1] for e in events)


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game", return_value={"display_name": "Test Game", "name": "test"})
@patch("tracker.capture_audio", return_value=b"audio")
@patch("tracker.audio_to_wav_bytes", return_value=b"wav")
@patch(
    "tracker.identify_audio",
    return_value={"title": "Found Track", "artist": "Artist", "source": "acrcloud"},
)
@patch("tracker.config.api_is_configured", return_value=False)
def test_manual_fingerprint_identifies_track_with_game(
    mock_api,
    mock_identify,
    mock_wav,
    mock_capture,
    mock_game,
    mock_is_conf,
    mock_host,
    running_tracker,
):
    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

    assert any(e[0] == "track" for e in events)
    assert any(e[0] == "status" and "Identified:" in e[1] for e in events)


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game", return_value={"display_name": "Test Game", "name": "test"})
@patch("tracker.capture_audio", return_value=b"audio")
@patch("tracker.audio_to_wav_bytes", return_value=b"wav")
@patch(
    "tracker.identify_audio",
    return_value={"title": "Same Track", "source": "acrcloud"},
)
@patch("tracker.config.api_is_configured", return_value=False)
def test_manual_fingerprint_duplicate_track_with_game(
    mock_api,
    mock_identify,
    mock_wav,
    mock_capture,
    mock_game,
    mock_is_conf,
    mock_host,
    running_tracker,
):
    """When identified track matches last_track for the same game, emit duplicate."""
    game = {"display_name": "Test Game", "name": "test"}
    running_tracker.last_track = {"title": "Same Track", "source": "acrcloud", "_game": game}

    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

    assert any(e[0] == "status" and "Same track detected" in e[1] for e in events)


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game", return_value={"display_name": "Test Game", "name": "test"})
@patch("tracker.capture_audio", return_value=b"audio")
@patch("tracker.audio_to_wav_bytes", return_value=b"wav")
@patch("tracker.identify_audio", return_value=None)
def test_manual_fingerprint_no_match_with_game(
    mock_identify, mock_wav, mock_capture, mock_game, mock_is_conf, mock_host, running_tracker
):
    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

    assert any(e[0] == "status" and "No match found" in e[1] for e in events)


@patch("tracker.config.get_acrcloud_host", return_value="host")
@patch("tracker.config.acrcloud_is_configured", return_value=True)
@patch("tracker.get_running_game", return_value={"display_name": "Test Game", "name": "test"})
@patch("tracker.capture_audio", side_effect=RuntimeError("boom"))
def test_manual_fingerprint_exception(
    mock_capture, mock_game, mock_is_conf, mock_host, running_tracker
):
    running_tracker.force_fingerprint()
    events = _wait_for_manual_fingerprint(running_tracker)

    assert any(e[0] == "error" and "Fingerprint failed" in e[1] for e in events)


# ── Helper methods ────────────────────────────────────────────────────────────


def test_track_key_uses_game_name_as_fallback(tracker):
    key = tracker._track_key({"source": "smtc", "title": "Song"}, game={"name": "my_game"})
    assert key[3] == "my_game"


@patch("tracker.config.api_is_configured", return_value=True)
@patch("tracker.post_now_playing", return_value=True)
def test_post_now_playing_webhook_sent(mock_post, mock_api, tracker):
    tracker._post_now_playing_with_status({"title": "Song"}, game=None)
    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get_nowait())
    assert any(e[0] == "delivery" and "Webhook sent" in e[1] for e in events)


@patch("tracker.config.api_is_configured", return_value=True)
@patch("tracker.post_now_playing", return_value=False)
def test_post_now_playing_webhook_failed(mock_post, mock_api, tracker):
    tracker._post_now_playing_with_status({"title": "Song"}, game=None)
    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get_nowait())
    assert any(e[0] == "delivery" and "Webhook failed" in e[1] for e in events)


@patch("tracker.config.api_is_configured")
@patch("tracker.post_now_playing", return_value=False)
def test_post_now_playing_rechecks_config_on_failure(mock_post, mock_api, tracker):
    """When post fails and config has since become unconfigured, emit not-configured warning."""
    mock_api.side_effect = [True, False]
    tracker._post_now_playing_with_status({"title": "Song"}, game=None)
    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get_nowait())
    assert any(e[0] == "delivery" and "not configured" in e[1] for e in events)


def test_emit_excluded_smtc_artist_only(tracker):
    tracker._emit_excluded_smtc({"source_app": "spotify.exe", "artist": "The Artist"})
    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get_nowait())
    assert any(e[0] == "status" and "The Artist" in e[1] for e in events)


def test_emit_excluded_smtc_title_only(tracker):
    tracker._emit_excluded_smtc({"source_app": "spotify.exe", "title": "The Title"})
    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get_nowait())
    assert any(e[0] == "status" and "The Title" in e[1] for e in events)


def test_emit_excluded_smtc_no_artist_or_title(tracker):
    tracker._emit_excluded_smtc({"source_app": "unknown.exe"})
    events = []
    while not tracker.event_queue.empty():
        events.append(tracker.event_queue.get_nowait())
    assert any(e[0] == "status" and e[1] == "Ignored source (unknown.exe)" for e in events)


def test_tracks_are_same_smtc_source_app_mismatch(tracker):
    a = {"title": "Song", "source": "smtc", "source_app": "spotify.exe"}
    b = {"title": "Song", "source": "smtc", "source_app": "browser.exe"}
    assert tracker._tracks_are_same(a, b) is False


def test_tracks_are_same_smtc_excluded_pattern_mismatch(tracker):
    a = {"title": "Song", "source": "smtc", "source_app": "x.exe", "excluded_pattern": "pat1"}
    b = {"title": "Song", "source": "smtc", "source_app": "x.exe", "excluded_pattern": "pat2"}
    assert tracker._tracks_are_same(a, b) is False


# ── _run loop ─────────────────────────────────────────────────────────────────


@pytest.fixture
def loop_tracker():
    """Fresh tracker for _run loop tests — _run is NOT patched."""
    trk = Tracker(queue.Queue())
    yield trk
    trk._stop_event.set()
    if trk._thread:
        trk._thread.join(timeout=1.0)


def _join_and_drain(trk, timeout=2.0):
    """Wait for the _run thread to finish, then return all queued events."""
    trk._thread.join(timeout=timeout)
    events = []
    while not trk.event_queue.empty():
        events.append(trk.event_queue.get_nowait())
    return events


@patch("tracker.time.sleep")
@patch("tracker.config.api_is_configured", return_value=False)
@patch("tracker.get_smtc_track_sync")
@patch("tracker.get_running_game", return_value=None)
def test_run_smtc_new_track(mock_game, mock_smtc, mock_api, mock_sleep, loop_tracker):
    track_data = {"title": "New Track", "source": "smtc"}

    def smtc_stop(**kwargs):
        loop_tracker._stop_event.set()
        return track_data

    mock_smtc.side_effect = smtc_stop
    loop_tracker.start()
    events = _join_and_drain(loop_tracker)

    assert any(e[0] == "track" and e[1]["title"] == "New Track" for e in events)


@patch("tracker.time.sleep")
@patch("tracker.config.api_is_configured", return_value=False)
@patch("tracker.get_smtc_track_sync")
@patch("tracker.get_running_game", return_value=None)
def test_run_smtc_duplicate_track(mock_game, mock_smtc, mock_api, mock_sleep, loop_tracker):
    track_data = {"title": "Same Track", "source": "smtc"}
    loop_tracker.last_track = dict(track_data)

    def smtc_stop(**kwargs):
        loop_tracker._stop_event.set()
        return track_data

    mock_smtc.side_effect = smtc_stop
    loop_tracker.start()
    events = _join_and_drain(loop_tracker)

    assert any(e[0] == "delivery" and "duplicate track" in e[1] for e in events)


@patch("tracker.time.sleep")
@patch("tracker.get_smtc_track_sync")
@patch("tracker.get_running_game", return_value=None)
def test_run_smtc_excluded_track(mock_game, mock_smtc, mock_sleep, loop_tracker):
    track_data = {
        "title": "Song",
        "source": "smtc",
        "excluded": True,
        "source_app": "browser.exe",
        "source_app_name": "Browser",
    }

    def smtc_stop(**kwargs):
        loop_tracker._stop_event.set()
        return track_data

    mock_smtc.side_effect = smtc_stop
    loop_tracker.start()
    events = _join_and_drain(loop_tracker)

    assert any(e[0] == "status" and "Ignored source" in e[1] for e in events)


@patch("tracker.time.sleep")
@patch("tracker.get_smtc_track_sync", return_value=None)
@patch("tracker.get_running_game")
def test_run_smtc_playback_stopped(mock_game, mock_smtc, mock_sleep, loop_tracker):
    loop_tracker.last_track = {"title": "Previous Track", "source": "smtc"}

    def game_stop():
        loop_tracker._stop_event.set()
        return None

    mock_game.side_effect = game_stop
    loop_tracker.start()
    events = _join_and_drain(loop_tracker)

    assert any(e[0] == "status" and "Playback stopped" in e[1] for e in events)


@patch("tracker.time.sleep")
@patch("tracker.get_running_game")
def test_run_paused(mock_game, mock_sleep, loop_tracker):
    loop_tracker._paused = True

    def sleep_stop(duration):
        loop_tracker._stop_event.set()

    mock_sleep.side_effect = sleep_stop
    loop_tracker.start()
    _join_and_drain(loop_tracker)

    mock_game.assert_not_called()


@patch("tracker.time.sleep")
@patch("tracker.config.api_is_configured", return_value=False)
@patch("tracker.identify_audio")
@patch("tracker.audio_to_wav_bytes", return_value=b"wav")
@patch("tracker.capture_audio", return_value=b"audio")
@patch("tracker.AudioChangeDetector")
@patch("tracker.get_running_game", return_value={"display_name": "Game", "name": "game"})
def test_run_game_audio_change_identifies_track(
    mock_game,
    mock_detector_class,
    mock_capture,
    mock_wav,
    mock_identify,
    mock_api,
    mock_sleep,
    loop_tracker,
):
    mock_detector_class.return_value.check.return_value = True

    def identify_stop(wav):
        loop_tracker._stop_event.set()
        return {"title": "Loop Track", "artist": "Art", "source": "acrcloud"}

    mock_identify.side_effect = identify_stop
    loop_tracker.start()
    events = _join_and_drain(loop_tracker)

    assert any(e[0] == "track" and e[1]["title"] == "Loop Track" for e in events)


@patch("tracker.time.sleep")
@patch("tracker.AudioChangeDetector")
@patch("tracker.get_running_game", return_value={"display_name": "Game", "name": "game"})
def test_run_game_no_audio_change(mock_game, mock_detector_class, mock_sleep, loop_tracker):
    def check_stop():
        loop_tracker._stop_event.set()
        return False

    mock_detector_class.return_value.check.side_effect = check_stop
    loop_tracker.start()
    events = _join_and_drain(loop_tracker)

    assert not any(e[0] == "track" for e in events)


@patch("tracker.time.sleep")
@patch("tracker.identify_audio")
@patch("tracker.audio_to_wav_bytes", return_value=b"wav")
@patch("tracker.capture_audio", return_value=b"audio")
@patch("tracker.AudioChangeDetector")
@patch("tracker.get_running_game", return_value={"display_name": "Game", "name": "game"})
def test_run_game_audio_no_match_emits_fallback(
    mock_game, mock_detector_class, mock_capture, mock_wav, mock_identify, mock_sleep, loop_tracker
):
    mock_detector_class.return_value.check.return_value = True

    def identify_stop(wav):
        loop_tracker._stop_event.set()
        return None

    mock_identify.side_effect = identify_stop
    loop_tracker.start()
    events = _join_and_drain(loop_tracker)

    assert any(e[0] == "track" and e[1].get("source") == "game_only" for e in events)


@patch("tracker.time.sleep")
@patch("tracker.get_running_game")
def test_run_exception_handling(mock_game, mock_sleep, loop_tracker):
    def game_raise():
        loop_tracker._stop_event.set()
        raise RuntimeError("scanner broken")

    mock_game.side_effect = game_raise
    loop_tracker.start()
    events = _join_and_drain(loop_tracker)

    assert any(e[0] == "error" and "scanner broken" in e[1] for e in events)
