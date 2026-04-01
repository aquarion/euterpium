# main.py — entry point: wires tracker, tray, and window together

import logging
import os
import queue
import threading

import config
import smtc
from tracker import Tracker
from ui.notifications import notify_track
from ui.tray import TrayIcon
from ui.window import MainWindow

# Configure logging before any local imports so module-level log messages
# (e.g. winsdk availability) are captured from the start
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("smtc").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)




def main():
    # Report winsdk status now that logging is definitely active
    if smtc.WINSDK_AVAILABLE:
        logger.info("SMTC: winsdk loaded — media session detection enabled")
    else:
        logger.warning("SMTC: winsdk not available — only game audio fingerprinting will work")

    event_queue: queue.Queue = queue.Queue()

    # ── Build components ──────────────────────────────────────────────────

    def on_quit():
        tracker.stop()
        os._exit(0)

    def on_show_settings():
        # Settings window must open in the tkinter thread
        window._queue.put(("open_settings",))

    window = MainWindow(on_quit=on_quit, on_show_settings=on_show_settings)
    tray = TrayIcon(
        on_show_window=lambda: window.show(),
        on_show_settings=on_show_settings,
        on_quit=on_quit,
    )
    tracker = Tracker(event_queue=event_queue)

    # ── Event pump: moves tracker events → window + tray ─────────────────

    def pump_events():
        while True:
            try:
                msg = event_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            kind = msg[0]

            if kind == "track":
                _, track, game = msg
                tray.set_listening(False)
                window.update_track(track, game)
                tray.update_track(
                    title=track.get("title", ""),
                    artist=track.get("artist", ""),
                    game_name=game["display_name"] if game else None,
                )
                notify_track(track, game)

            elif kind == "status":
                _, message = msg
                tray.set_listening("fingerprinting" in message.lower())
                window.log_status(message, level="info")
                logger.info(message)

            elif kind == "error":
                _, message = msg
                window.log_status(message, level="error")
                logger.error(message)

    # ── Start threads ─────────────────────────────────────────────────────

    # Event pump thread
    pump_thread = threading.Thread(target=pump_events, daemon=True)
    pump_thread.start()

    # Tracker thread (daemon, started inside Tracker.start())
    tracker.start()

    # Window thread — tkinter must run in a non-main thread on Windows
    # when pystray holds the main thread
    window_thread = threading.Thread(target=window.run, daemon=True)
    window_thread.start()

    # Wait for window to be ready before showing it
    window._ready.wait(timeout=5)
    window.show()

    # On first launch (or if credentials were wiped), open Settings immediately
    if not config.is_configured():
        logger.info("Credentials not configured — opening Settings")
        window.log_status(
            "Welcome! Please enter your credentials in Settings to get started.", level="info"
        )
        on_show_settings()

    # Tray runs in main thread (required by pystray on Windows) — blocks here
    logger.info("Euterpium running — check your system tray")
    tray.run()


if __name__ == "__main__":
    main()
