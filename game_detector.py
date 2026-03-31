# game_detector.py — detects known running game processes

import logging
import psutil
from config import KNOWN_GAMES

logger = logging.getLogger(__name__)


def get_running_game() -> dict | None:
    """
    Checks running processes against the KNOWN_GAMES list.
    Returns the first match as a dict, or None if no known game is running.
    """
    try:
        for proc in psutil.process_iter(["name"]):
            proc_name = proc.info.get("name", "") or ""
            if proc_name in KNOWN_GAMES:
                return {
                    "process": proc_name,
                    "display_name": KNOWN_GAMES[proc_name],
                }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    except Exception as e:
        logger.debug(f"Process scan error: {e}")

    return None
