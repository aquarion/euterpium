# tests/test_game_detector_api.py — tests for REST-API-driven game state

from unittest.mock import patch

import game_detector


def _clear():
    game_detector.clear_current_game()


# ── set_current_game / clear_current_game ─────────────────────────────────────


def test_set_current_game_stores_game():
    _clear()
    game_detector.set_current_game("witcher3.exe", "The Witcher 3")
    game = game_detector.get_running_game()
    assert game == {"process": "witcher3.exe", "display_name": "The Witcher 3"}


def test_set_current_game_normalises_process_to_lower():
    _clear()
    game_detector.set_current_game("  WITCHER3.EXE  ", "The Witcher 3")
    game = game_detector.get_running_game()
    assert game["process"] == "witcher3.exe"


def test_set_current_game_with_valid_pid_is_returned():
    _clear()
    with patch("psutil.pid_exists", return_value=True):
        game_detector.set_current_game("bg3.exe", "Baldur's Gate 3", pid=1234)
        game = game_detector.get_running_game()
    assert game == {"process": "bg3.exe", "display_name": "Baldur's Gate 3"}


def test_set_current_game_with_stale_pid_is_cleared():
    _clear()
    game_detector.set_current_game("bg3.exe", "Baldur's Gate 3", pid=99999999)
    with patch("psutil.pid_exists", return_value=False):
        game = game_detector.get_running_game()
    assert game is None


def test_clear_current_game_removes_game():
    game_detector.set_current_game("game.exe", "Game")
    game_detector.clear_current_game()
    assert game_detector._api_current_game is None


def test_clear_current_game_is_idempotent():
    _clear()
    game_detector.clear_current_game()  # should not raise
    assert game_detector._api_current_game is None


def test_overwrite_replaces_previous_game():
    _clear()
    game_detector.set_current_game("game1.exe", "Game One")
    game_detector.set_current_game("game2.exe", "Game Two")
    game = game_detector.get_running_game()
    assert game["display_name"] == "Game Two"


# ── Priority: API > file > process scan ──────────────────────────────────────


def test_api_game_takes_priority_over_playnite_file(monkeypatch, tmp_path):
    """In-memory API game should be returned even when the file exists."""
    import json

    path = tmp_path / "euterpium_current_game.json"
    path.write_text(json.dumps({"process": "file_game.exe", "name": "File Game"}))
    monkeypatch.setattr("config.get_playnite_current_game_path", lambda: str(path))

    game_detector.set_current_game("api_game.exe", "API Game")
    try:
        game = game_detector.get_running_game()
        assert game["display_name"] == "API Game"
    finally:
        _clear()


def test_falls_back_to_playnite_file_when_no_api_game(monkeypatch, tmp_path):
    """When no API game is set, fall through to the file-based detection."""
    import json

    _clear()
    path = tmp_path / "euterpium_current_game.json"
    path.write_text(json.dumps({"process": "file_game.exe", "name": "File Game"}))
    monkeypatch.setattr("config.get_playnite_current_game_path", lambda: str(path))

    game = game_detector.get_running_game()
    assert game == {"process": "file_game.exe", "display_name": "File Game"}
