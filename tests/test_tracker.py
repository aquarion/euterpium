# tests/test_tracker.py — Tracker logic (track deduplication)

import queue

import pytest

from tracker import Tracker


@pytest.fixture
def tracker():
    return Tracker(queue.Queue())


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


def test_different_artist_is_not_same(tracker):
    a = {"title": "Song", "artist": "Artist A"}
    b = {"title": "Song", "artist": "Artist B"}
    assert tracker._tracks_are_same(a, b) is False


def test_none_first_arg_is_not_same(tracker):
    assert tracker._tracks_are_same(None, {"title": "Song", "artist": "A"}) is False


def test_none_second_arg_is_not_same(tracker):
    assert tracker._tracks_are_same({"title": "Song", "artist": "A"}, None) is False


def test_both_none_is_not_same(tracker):
    assert tracker._tracks_are_same(None, None) is False


def test_extra_fields_do_not_affect_comparison(tracker):
    # Tracks with identical title/artist but different source/album are still "same"
    a = {"title": "Song", "artist": "Artist", "source": "smtc", "album": "Album 1"}
    b = {"title": "Song", "artist": "Artist", "source": "acrcloud", "album": "Album 2"}
    assert tracker._tracks_are_same(a, b) is True
