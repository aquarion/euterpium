# ui/notifications.py — Windows toast notifications via win11toast

import logging
import os

logger = logging.getLogger(__name__)

try:
    from win11toast import notify as _notify
    WIN11TOAST_AVAILABLE = True
except ImportError:
    WIN11TOAST_AVAILABLE = False
    logger.warning("win11toast not available — notifications disabled. Install with: pip install win11toast")

_ICON_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "icon.png")
)


def notify_track(track: dict, game: dict | None = None):
    """
    Fires a Windows toast notification for a newly detected track.
    Silently does nothing if win11toast isn't installed.
    """
    if not WIN11TOAST_AVAILABLE:
        return

    title  = track.get("title", "")
    artist = track.get("artist", "")
    source = track.get("source", "")

    if source == "game_only":
        # Unrecognised game track — notify with just the game name
        if not game:
            return
        heading = game["display_name"]
        body    = "Playing unrecognised track"
    elif not title:
        return
    else:
        heading = title
        body    = artist
        if game:
            body = f"{artist}  ·  {game['display_name']}" if artist else game["display_name"]

    icon = _ICON_PATH if os.path.exists(_ICON_PATH) else None

    try:
        kwargs = dict(title=heading, body=body)
        if icon:
            kwargs["icon"] = icon
        _notify(**kwargs)
    except Exception as e:
        # Notifications are best-effort — never crash the main loop
        logger.debug(f"Notification failed: {e}")
