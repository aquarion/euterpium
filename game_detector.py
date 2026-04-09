# game_detector.py — detects known running game processes

import json
import logging
import os

import psutil

import config
from config import KNOWN_GAMES

logger = logging.getLogger(__name__)

# Playnite JSON cache: (mtime, parsed_dict)
_playnite_cache: tuple[float, dict[str, str]] | None = None


def _load_playnite_games() -> dict[str, str]:
    """
    Reads the Playnite-exported JSON and returns {process_lower: display_name}.
    Result is cached and only reloaded when the file's mtime changes.
    Returns {} silently if the file is missing or malformed.
    """
    global _playnite_cache
    path = config.get_playnite_games_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}

    if _playnite_cache is not None and _playnite_cache[0] == mtime:
        return _playnite_cache[1]

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        games = {
            entry["process"].lower(): entry["name"]
            for entry in data
            if "process" in entry and "name" in entry
        }
        logger.debug("Loaded %d game(s) from Playnite (%s)", len(games), path)
        _playnite_cache = (mtime, games)
        return games
    except Exception as e:
        logger.debug("Could not load Playnite games from %s: %s", path, e)
        return {}


def get_running_game() -> dict | None:
    """
    Checks running processes against the known games list (manual config merged
    with Playnite data). Manual [games] entries take precedence over Playnite.
    Returns the first match as a dict, or None if no known game is running.
    """
    playnite_games = _load_playnite_games()
    known_games = {**playnite_games, **KNOWN_GAMES}

    try:
        for proc in psutil.process_iter(["name"]):
            proc_name = (proc.info.get("name", "") or "").lower()
            if proc_name in known_games:
                return {
                    "process": proc_name,
                    "display_name": known_games[proc_name],
                }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    except Exception as e:
        logger.debug(f"Process scan error: {e}")

    return None
