# tests/test_game_detector.py — process scanning and game matching

from unittest.mock import MagicMock, patch

import psutil

import game_detector


def _proc(name):
    mock = MagicMock()
    mock.info = {"name": name}
    return mock


# ── Basic detection ───────────────────────────────────────────────────────────


def test_returns_none_when_no_known_game_running(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"ffxiv_dx11.exe": "Final Fantasy XIV"})
    with patch("psutil.process_iter", return_value=[_proc("notepad.exe"), _proc("chrome.exe")]):
        assert game_detector.get_running_game() is None


def test_detects_known_game(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"ffxiv_dx11.exe": "Final Fantasy XIV"})
    with patch("psutil.process_iter", return_value=[_proc("ffxiv_dx11.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "ffxiv_dx11.exe", "display_name": "Final Fantasy XIV"}


def test_returns_first_match_when_multiple_games_running(monkeypatch):
    monkeypatch.setattr(
        game_detector,
        "KNOWN_GAMES",
        {
            "game_a.exe": "Game A",
            "game_b.exe": "Game B",
        },
    )
    with patch("psutil.process_iter", return_value=[_proc("game_a.exe"), _proc("game_b.exe")]):
        result = game_detector.get_running_game()
    assert result["process"] == "game_a.exe"


def test_returns_none_when_process_list_is_empty(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"ffxiv_dx11.exe": "Final Fantasy XIV"})
    with patch("psutil.process_iter", return_value=[]):
        assert game_detector.get_running_game() is None


# ── Error resilience ──────────────────────────────────────────────────────────


def test_handles_no_such_process_gracefully(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "Game"})
    with patch("psutil.process_iter", side_effect=psutil.NoSuchProcess(pid=1)):
        assert game_detector.get_running_game() is None


def test_handles_access_denied_gracefully(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "Game"})
    with patch("psutil.process_iter", side_effect=psutil.AccessDenied(pid=1)):
        assert game_detector.get_running_game() is None
