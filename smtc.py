# smtc.py — Windows Media Session (SMTC) detection
# Reads currently playing media from any app registered with Windows
# (Spotify, browsers, Windows Media Player, etc.)

import asyncio
import logging
import sys

logger = logging.getLogger(__name__)

try:
    from winsdk.windows.media import MediaPlaybackStatus
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    )

    WINSDK_AVAILABLE = True
    logger.info("winsdk loaded — SMTC detection enabled")
except ImportError as e:
    WINSDK_AVAILABLE = False
    logger.warning(
        f"winsdk not available ({e}) — SMTC detection disabled. Install with: pip install winsdk"
    )


def _source_app_name(app_id: str) -> str:
    raw = (app_id or "unknown").strip()
    if not raw:
        return "unknown"

    lowered = raw.lower()
    if ".exe" in lowered:
        parts = lowered.replace("!", ".").split(".")
        for part in reversed(parts):
            if part.endswith("exe"):
                return part

    cleaned = lowered.replace("!", ".")
    parts = [p for p in cleaned.split(".") if p]
    return parts[-1] if parts else lowered


async def get_smtc_track(ignored_apps: list[str] | None = None) -> dict | None:
    """
    Returns metadata for the currently playing track via Windows Media Session,
    or None if nothing is playing / winsdk is unavailable.

    ignored_apps: list of lowercase substrings — any session whose
    source_app_user_model_id contains one of these is skipped.
    """
    if not WINSDK_AVAILABLE:
        return None

    try:
        sessions = await MediaManager.request_async()
        current = sessions.get_current_session()

        if not current:
            logger.debug("SMTC: no active session")
            return None

        app_id = current.source_app_user_model_id or "unknown"
        app_name = _source_app_name(app_id)

        excluded_pattern = None
        if ignored_apps:
            app_id_lower = app_id.lower()
            for pattern in ignored_apps:
                if pattern and pattern in app_id_lower:
                    excluded_pattern = pattern
                    logger.debug(
                        f"SMTC: ignoring session from '{app_id_lower}' (matches '{pattern}')"
                    )
                    break

        info = await current.try_get_media_properties_async()
        playback = current.get_playback_info()

        # Accept PLAYING or PAUSED — some apps (notably Apple Music for Windows)
        # incorrectly report PAUSED via SMTC while audio is actively playing.
        # CLOSED / STOPPED mean nothing is queued; CHANGING is transient.
        status = playback.playback_status
        if status == MediaPlaybackStatus.STOPPED or status == MediaPlaybackStatus.CLOSED:
            logger.debug(f"SMTC: session is stopped/closed (status={status})")
            return None
        if status == MediaPlaybackStatus.PAUSED:
            logger.debug("SMTC: session reports PAUSED (Apple Music quirk — treating as playing)")

        title = info.title or ""
        raw_artist = info.artist or ""
        raw_album = info.album_title or ""

        if not title and not raw_artist:
            logger.debug("SMTC: playing but no title/artist metadata")
            return None

        # Apple Music (and some other apps) pack "Artist — Album" into the
        # artist field and leave album_title empty.  Split them apart.
        if raw_artist and not raw_album and " \u2014 " in raw_artist:
            artist, album = raw_artist.split(" \u2014 ", 1)
        else:
            artist, album = raw_artist, raw_album

        logger.debug(f"SMTC: found '{artist} — {title}' (album: {album!r}, app: {app_id})")

        if excluded_pattern is not None:
            return {
                "source": "smtc",
                "source_app": app_id,
                "source_app_name": app_name,
                "excluded": True,
                "excluded_pattern": excluded_pattern,
                "title": title,
                "artist": artist,
                "album": album,
            }

        return {
            "source": "smtc",
            "source_app": app_id,
            "source_app_name": app_name,
            "title": title,
            "artist": artist,
            "album": album,
        }

    except Exception as e:
        logger.warning(f"SMTC read failed: {e}")
        return None


def get_smtc_track_sync(ignored_apps: list[str] | None = None) -> dict | None:
    """
    Synchronous wrapper. Explicitly uses SelectorEventLoop rather than the
    Windows-default ProactorEventLoop, because ProactorEventLoop's IOCP
    conflicts with WinRT async callbacks (RPC_E_CALL_CANCELED).
    WindowsSelectorEventLoopPolicy is deprecated from Python 3.16 onwards,
    so we create the loop directly instead.
    """
    if not WINSDK_AVAILABLE:
        return None

    try:
        if sys.platform == "win32":
            loop = asyncio.SelectorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(get_smtc_track(ignored_apps=ignored_apps))
        finally:
            loop.close()
            asyncio.set_event_loop(None)
    except Exception as e:
        logger.warning(f"SMTC read failed: {e}")
        return None
