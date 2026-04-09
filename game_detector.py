# game_detector.py — detects known running game processes

import json
import logging

import psutil

import config
from config import KNOWN_GAMES

logger = logging.getLogger(__name__)

_current_game_logged_missing = False


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

        _current_game_logged_missing = False
        return {"process": data["process"], "display_name": data["name"]}

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
    1. Playnite event-driven file (euterpium_current_game.json) — covers all
       games launched via Playnite regardless of platform.
    2. Manual [games] entries from euterpium.ini — covers games launched
       outside Playnite.
    """
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
