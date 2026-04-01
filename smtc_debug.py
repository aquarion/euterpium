"""
smtc_debug.py — standalone SMTC diagnostic tool
Run with:  poetry run python smtc_debug.py
or:        python smtc_debug.py

Dumps every SMTC session Windows knows about, so we can see what's
actually registered and what state it's in.
"""

import asyncio
import sys


async def main():
    try:
        from winsdk.windows.media import MediaPlaybackStatus
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
    except ImportError as e:
        print(f"ERROR: winsdk not available: {e}")
        print("Install with:  pip install winsdk")
        sys.exit(1)

    # Build status name map dynamically — enum constant names vary by winsdk version
    STATUS_NAMES = {}
    for _name in dir(MediaPlaybackStatus):
        if not _name.startswith("_"):
            try:
                STATUS_NAMES[getattr(MediaPlaybackStatus, _name)] = _name
            except Exception:
                pass
    print(f"Known playback statuses: {STATUS_NAMES}\n")

    print("Requesting MediaManager...", flush=True)
    manager = await MediaManager.request_async()

    # Current (focus) session
    current = manager.get_current_session()
    current_id = current.source_app_user_model_id if current else None
    print(f"Current session app ID: {current_id!r}\n")

    # All sessions
    sessions = manager.get_sessions()
    print(f"Total sessions: {len(sessions)}\n")

    for i, session in enumerate(sessions):
        app_id = session.source_app_user_model_id
        is_current = (app_id == current_id)
        playback = session.get_playback_info()
        status_val = playback.playback_status
        status_name = STATUS_NAMES.get(status_val, f"UNKNOWN({status_val})")

        print(f"  [{i}] {'*** CURRENT ***  ' if is_current else ''}App: {app_id!r}")
        print(f"       Playback status : {status_name}")
        print(f"       Auto-repeat mode: {playback.auto_repeat_mode}")
        print(f"       Is shuffle active: {playback.is_shuffle_active}")

        try:
            info = await session.try_get_media_properties_async()
            title  = info.title or "(none)"
            artist = info.artist or "(none)"
            album  = info.album_title or "(none)"
            print(f"       Title  : {title}")
            print(f"       Artist : {artist}")
            print(f"       Album  : {album}")
        except Exception as e:
            print(f"       (could not read media properties: {e})")

        print()

    if not sessions:
        print("  (no sessions found — nothing is registered with Windows media controls)")


if __name__ == "__main__":
    # ProactorEventLoop (Python's Windows default) uses IOCP which conflicts
    # with WinRT async callbacks.  Create SelectorEventLoop directly;
    # WindowsSelectorEventLoopPolicy is deprecated as of Python 3.16.
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
