# main.py — entry point: wires tracker, tray, and window together

import logging
import queue
import threading

import config
import smtc
from rest_api import start_server as start_rest_server
from tracker import Tracker
from ui.notifications import notify_track, notify_update_available
from ui.tray import TrayIcon
from ui.window import MainWindow
from updater import UpdateManager, cleanup_stale_update_dirs
from version import __display_version__, __version__

# Configure logging before any local imports so module-level log messages
# (e.g. winsdk availability) are captured from the start
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    logging.getLogger().setLevel(config.get_log_level())
    logger.info("Starting Euterpium %s", __version__)

    # Report winsdk status now that logging is definitely active
    if smtc.WINSDK_AVAILABLE:
        logger.info("SMTC: winsdk loaded — media session detection enabled")
    else:
        logger.warning("SMTC: winsdk not available — only game audio fingerprinting will work")

    event_queue: queue.Queue = queue.Queue()

    # ── Build components ──────────────────────────────────────────────────

    def on_quit():
        tracker.stop()
        tray.stop()

    def on_show_settings():
        # Settings window must open in the tkinter thread
        window._queue.put(("open_settings",))

    def on_fingerprint_now():
        # Trigger manual fingerprinting
        tracker.force_fingerprint()

    def on_check_for_updates():
        update_manager.check_for_updates(manual=True)

    def on_install_update():
        update_manager.install_available_update()

    window = MainWindow(
        on_quit=on_quit,
        on_show_settings=on_show_settings,
        on_fingerprint_now=on_fingerprint_now,
        on_install_update=on_install_update,
        current_version=__display_version__,
    )
    tray = TrayIcon(
        on_show_window=lambda: window.show(),
        on_show_settings=on_show_settings,
        on_quit=on_quit,
        on_check_for_updates=on_check_for_updates,
        on_install_update=on_install_update,
        current_version=__display_version__,
    )
    tracker = Tracker(event_queue=event_queue)
    update_manager = UpdateManager(event_queue=event_queue, current_version=__version__)

    removed_temp_dirs = cleanup_stale_update_dirs()
    if removed_temp_dirs:
        logger.info("Removed %s stale updater temp directories", removed_temp_dirs)

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

            elif kind == "delivery":
                _, message, level = msg
                window.log_status(message, level=level)
                window.set_delivery_status(message, level)
                if level == "error":
                    logger.error(message)
                elif level == "warn":
                    logger.warning(message)
                else:
                    logger.info(message)

            elif kind == "error":
                _, message = msg
                window.log_status(message, level="error")
                logger.error(message)

            elif kind == "update_checked":
                _, update = msg
                # Always sync tray state — clears stale "Install update" when update is None.
                tray.set_available_update(update)
                window.set_available_update(update)

            elif kind == "update_available":
                _, update = msg
                window.log_status(f"Update available: Euterpium {update.version}", level="info")
                logger.info("Update available: Euterpium %s", update.version)
                notify_update_available(update.version)

            elif kind == "update_installer_launched":
                _, update, installer_path = msg
                window.log_status(
                    f"Installer launched for Euterpium {update.version}; closing app...",
                    level="info",
                )
                logger.info("Installer launched from %s", installer_path)
                on_quit()

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
    update_manager.check_for_updates(manual=False)
    start_rest_server(tracker)
    tray.run()


if __name__ == "__main__":
    main()
