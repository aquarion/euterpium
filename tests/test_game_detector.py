# tests/test_game_detector.py — process scanning and game matching

import json
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
    monkeypatch.setattr(game_detector, "_load_playnite_games", lambda: {})
    with patch("psutil.process_iter", return_value=[_proc("notepad.exe"), _proc("chrome.exe")]):
        assert game_detector.get_running_game() is None


def test_detects_known_game(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"ffxiv_dx11.exe": "Final Fantasy XIV"})
    monkeypatch.setattr(game_detector, "_load_playnite_games", lambda: {})
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
    monkeypatch.setattr(game_detector, "_load_playnite_games", lambda: {})
    with patch("psutil.process_iter", return_value=[_proc("game_a.exe"), _proc("game_b.exe")]):
        result = game_detector.get_running_game()
    assert result["process"] == "game_a.exe"


def test_returns_none_when_process_list_is_empty(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"ffxiv_dx11.exe": "Final Fantasy XIV"})
    monkeypatch.setattr(game_detector, "_load_playnite_games", lambda: {})
    with patch("psutil.process_iter", return_value=[]):
        assert game_detector.get_running_game() is None


def test_process_name_matching_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"rocketleague.exe": "Rocket League"})
    monkeypatch.setattr(game_detector, "_load_playnite_games", lambda: {})
    with patch("psutil.process_iter", return_value=[_proc("RocketLeague.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "rocketleague.exe", "display_name": "Rocket League"}


# ── Error resilience ──────────────────────────────────────────────────────────


def test_handles_no_such_process_gracefully(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "Game"})
    monkeypatch.setattr(game_detector, "_load_playnite_games", lambda: {})
    with patch("psutil.process_iter", side_effect=psutil.NoSuchProcess(pid=1)):
        assert game_detector.get_running_game() is None


def test_handles_access_denied_gracefully(monkeypatch):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "Game"})
    monkeypatch.setattr(game_detector, "_load_playnite_games", lambda: {})
    with patch("psutil.process_iter", side_effect=psutil.AccessDenied(pid=1)):
        assert game_detector.get_running_game() is None


# ── Playnite integration ──────────────────────────────────────────────────────


def test_detects_game_from_playnite_data(monkeypatch, tmp_path):
    games_file = tmp_path / "euterpium_games.json"
    games_file.write_text(json.dumps([{"process": "bg3.exe", "name": "Baldur's Gate 3"}]))
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {})
    monkeypatch.setattr("config.get_playnite_games_path", lambda: str(games_file))
    with patch("psutil.process_iter", return_value=[_proc("bg3.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "bg3.exe", "display_name": "Baldur's Gate 3"}


def test_manual_games_override_playnite(monkeypatch, tmp_path):
    games_file = tmp_path / "euterpium_games.json"
    games_file.write_text(
        json.dumps([{"process": "bg3.exe", "name": "Baldur's Gate 3 (Playnite)"}])
    )
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"bg3.exe": "Baldur's Gate 3 (Manual)"})
    monkeypatch.setattr("config.get_playnite_games_path", lambda: str(games_file))
    with patch("psutil.process_iter", return_value=[_proc("bg3.exe")]):
        result = game_detector.get_running_game()
    assert result["display_name"] == "Baldur's Gate 3 (Manual)"


def test_missing_playnite_file_falls_back_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "My Game"})
    monkeypatch.setattr(
        "config.get_playnite_games_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    with patch("psutil.process_iter", return_value=[_proc("game.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "game.exe", "display_name": "My Game"}


def test_malformed_playnite_file_falls_back_gracefully(monkeypatch, tmp_path):
    games_file = tmp_path / "euterpium_games.json"
    games_file.write_text("not valid json{{")
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "My Game"})
    monkeypatch.setattr("config.get_playnite_games_path", lambda: str(games_file))
    with patch("psutil.process_iter", return_value=[_proc("game.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "game.exe", "display_name": "My Game"}


def test_playnite_process_matching_is_case_insensitive(monkeypatch, tmp_path):
    games_file = tmp_path / "euterpium_games.json"
    games_file.write_text(json.dumps([{"process": "BG3.exe", "name": "Baldur's Gate 3"}]))
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {})
    monkeypatch.setattr("config.get_playnite_games_path", lambda: str(games_file))
    with patch("psutil.process_iter", return_value=[_proc("bg3.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "bg3.exe", "display_name": "Baldur's Gate 3"}


def test_load_playnite_games_returns_empty_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "config.get_playnite_games_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    assert game_detector._load_playnite_games() == {}


def test_load_playnite_games_skips_entries_missing_fields(monkeypatch, tmp_path):
    games_file = tmp_path / "euterpium_games.json"
    games_file.write_text(
        json.dumps(
            [
                {"process": "good.exe", "name": "Good Game"},
                {"process": "no_name.exe"},
                {"name": "No Process"},
                {},
            ]
        )
    )
    monkeypatch.setattr("config.get_playnite_games_path", lambda: str(games_file))
    result = game_detector._load_playnite_games()
    assert result == {"good.exe": "Good Game"}
