# tests/test_game_detector.py — process scanning and game matching

import json
from unittest.mock import patch

import psutil

import game_detector


def _proc(name):
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.info = {"name": name}
    return mock


def _current_game_file(tmp_path, process, name, pid=None):
    """Write a current game file and return the path."""
    data = {"process": process, "name": name}
    if pid is not None:
        data["pid"] = pid
    p = tmp_path / "euterpium_current_game.json"
    p.write_text(json.dumps(data))
    return str(p)


# ── Playnite event-driven detection ──────────────────────────────────────────


def test_detects_game_from_playnite_current_game_file(monkeypatch, tmp_path):
    path = _current_game_file(tmp_path, "witcher3.exe", "The Witcher 3")
    monkeypatch.setattr("config.get_playnite_current_game_path", lambda: path)
    result = game_detector.get_running_game()
    assert result == {"process": "witcher3.exe", "display_name": "The Witcher 3"}


def test_playnite_current_game_file_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "config.get_playnite_current_game_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {})
    result = game_detector.get_running_game()
    assert result is None


def test_playnite_current_game_pid_validated_against_live_processes(monkeypatch, tmp_path):
    path = _current_game_file(tmp_path, "game.exe", "My Game", pid=99999999)
    monkeypatch.setattr("config.get_playnite_current_game_path", lambda: path)
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {})
    # PID 99999999 almost certainly doesn't exist
    with patch("psutil.pid_exists", return_value=False):
        result = game_detector.get_running_game()
    assert result is None


def test_playnite_current_game_with_valid_pid_is_returned(monkeypatch, tmp_path):
    path = _current_game_file(tmp_path, "game.exe", "My Game", pid=1234)
    monkeypatch.setattr("config.get_playnite_current_game_path", lambda: path)
    with patch("psutil.pid_exists", return_value=True):
        result = game_detector.get_running_game()
    assert result == {"process": "game.exe", "display_name": "My Game"}


def test_playnite_current_game_without_pid_is_trusted(monkeypatch, tmp_path):
    path = _current_game_file(tmp_path, "game.exe", "My Game")  # no pid
    monkeypatch.setattr("config.get_playnite_current_game_path", lambda: path)
    result = game_detector.get_running_game()
    assert result == {"process": "game.exe", "display_name": "My Game"}


def test_playnite_current_game_malformed_falls_back(monkeypatch, tmp_path):
    bad = tmp_path / "euterpium_current_game.json"
    bad.write_text("not valid json{{")
    monkeypatch.setattr("config.get_playnite_current_game_path", lambda: str(bad))
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "My Game"})
    with patch("psutil.process_iter", return_value=[_proc("game.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "game.exe", "display_name": "My Game"}


# ── Manual [games] fallback ───────────────────────────────────────────────────


def test_falls_back_to_manual_games_when_no_current_game_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "config.get_playnite_current_game_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"ffxiv_dx11.exe": "Final Fantasy XIV"})
    with patch("psutil.process_iter", return_value=[_proc("ffxiv_dx11.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "ffxiv_dx11.exe", "display_name": "Final Fantasy XIV"}


def test_playnite_takes_priority_over_manual_games(monkeypatch, tmp_path):
    path = _current_game_file(tmp_path, "bg3.exe", "Baldur's Gate 3 (Playnite)")
    monkeypatch.setattr("config.get_playnite_current_game_path", lambda: path)
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"bg3.exe": "Baldur's Gate 3 (Manual)"})
    result = game_detector.get_running_game()
    assert result["display_name"] == "Baldur's Gate 3 (Playnite)"


def test_returns_none_when_no_known_game_running(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "config.get_playnite_current_game_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"ffxiv_dx11.exe": "Final Fantasy XIV"})
    with patch("psutil.process_iter", return_value=[_proc("notepad.exe")]):
        assert game_detector.get_running_game() is None


def test_returns_none_when_no_games_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "config.get_playnite_current_game_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {})
    assert game_detector.get_running_game() is None


def test_manual_process_matching_is_case_insensitive(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "config.get_playnite_current_game_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"rocketleague.exe": "Rocket League"})
    with patch("psutil.process_iter", return_value=[_proc("RocketLeague.exe")]):
        result = game_detector.get_running_game()
    assert result == {"process": "rocketleague.exe", "display_name": "Rocket League"}


# ── Error resilience ──────────────────────────────────────────────────────────


def test_handles_no_such_process_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "config.get_playnite_current_game_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "Game"})
    with patch("psutil.process_iter", side_effect=psutil.NoSuchProcess(pid=1)):
        assert game_detector.get_running_game() is None


def test_handles_access_denied_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "config.get_playnite_current_game_path",
        lambda: str(tmp_path / "nonexistent.json"),
    )
    monkeypatch.setattr(game_detector, "KNOWN_GAMES", {"game.exe": "Game"})
    with patch("psutil.process_iter", side_effect=psutil.AccessDenied(pid=1)):
        assert game_detector.get_running_game() is None
