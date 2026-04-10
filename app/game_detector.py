# game_detector.py — detects known running game processes

import json
import logging
import threading

import psutil

import config
from config import KNOWN_GAMES

logger = logging.getLogger(__name__)

_current_game_logged_missing = False

# In-memory game state set via the REST API (takes priority over file detection)
_api_current_game: dict | None = None
_api_game_lock = threading.Lock()


def set_current_game(process: str, name: str, pid: int | None = None) -> None:
    """Set the current game from the REST API, replacing the file-based transport."""
    global _api_current_game
    entry: dict = {"process": process.strip().lower(), "display_name": name.strip()}
    if pid is not None:
        entry["pid"] = pid
    with _api_game_lock:
        _api_current_game = entry
    logger.info("Game started (API): %s (%s)", name, process)


def clear_current_game() -> None:
    """Clear the current game set by the REST API."""
    global _api_current_game
    with _api_game_lock:
        prev = _api_current_game
        _api_current_game = None
    if prev is not None:
        logger.info("Game stopped (API): %s", prev.get("display_name", "?"))


def _get_playnite_current_game() -> dict | None:
    """
    Reads the file the Playnite plugin writes when a game starts.
    Validates the PID is still alive to guard against stale files.
    Returns a game dict or None.
    """
    global _current_game_logged_missing
    path = config.get_playnite_current_game_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        pid = data.get("pid")
        if pid is not None and not psutil.pid_exists(pid):
            logger.debug("Playnite current game file has stale PID %d — ignoring", pid)
            return None

        process_name = str(data["process"]).strip().lower()
        _current_game_logged_missing = False
        return {"process": process_name, "display_name": data["name"]}

    except FileNotFoundError:
        if not _current_game_logged_missing:
            logger.info("Playnite current game file not found: %s", path)
            _current_game_logged_missing = True
        return None
    except Exception as e:
        logger.debug("Could not read Playnite current game from %s: %s", path, e)
        return None


def get_running_game() -> dict | None:
    """
    Returns the currently running game as a dict, or None.

    Checks in order:
    1. In-memory game set via the REST API (POST /api/game/start) — highest priority.
    2. Playnite event-driven file (euterpium_current_game.json) — legacy file transport.
    3. Manual [games] entries from euterpium.ini — covers games launched outside Playnite.
    """
    global _api_current_game
    with _api_game_lock:
        api_game = _api_current_game
        if api_game is not None:
            pid = api_game.get("pid")
            if pid is not None and not psutil.pid_exists(pid):
                logger.debug("API current game has stale PID %d — clearing", pid)
                _api_current_game = None
                api_game = None

    if api_game is not None:
        return {"process": api_game["process"], "display_name": api_game["display_name"]}

    game = _get_playnite_current_game()
    if game:
        return game

    if not KNOWN_GAMES:
        return None

    try:
        for proc in psutil.process_iter(["name"]):
            proc_name = (proc.info.get("name", "") or "").lower()
            if proc_name in KNOWN_GAMES:
                return {"process": proc_name, "display_name": KNOWN_GAMES[proc_name]}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    except Exception as e:
        logger.debug("Process scan error: %s", e)

    return None
