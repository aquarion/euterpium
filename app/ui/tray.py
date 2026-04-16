# ui/tray.py — system tray icon using pystray

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from updater import AvailableUpdate

logger = logging.getLogger(__name__)

try:
    import pystray

    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    logger.warning("pystray not available — tray icon disabled. Install with: pip install pystray")


def _load_named_icon(filename: str) -> Image.Image | None:
    path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "icons", filename))
    if os.path.exists(path):
        img = Image.open(path).convert("RGBA")
        return img.resize((64, 64), Image.LANCZOS)
    return None


def _load_icon_image() -> Image.Image:
    """
    Loads the app icon.
    Falls back to a generated icon if the file isn't found.
    """
    img = _load_named_icon("app_icon.png")
    if img:
        return img

    # Fallback: generate the delta-in-circle icon programmatically
    logger.warning("icons/app_icon.png not found — using generated fallback icon")
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    cx, cy, r = size // 2, size // 2, size // 2 - 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 150, 0, 255), width=3)
    draw.polygon(
        [(cx, cy - r + 8), (cx - r + 8, cy + r - 8), (cx + r - 8, cy + r - 8)],
        outline=(0, 150, 0, 255),
        width=3,
    )
    return img


class TrayIcon:
    """
    Manages the system tray icon.
    Must be run in the main thread on Windows.

    Callbacks:
        on_show_window()  — called when user clicks Show Window
        on_quit()         — called when user clicks Quit
    """

    def __init__(
        self,
        on_show_window,
        on_show_settings,
        on_quit,
        on_check_for_updates=None,
        on_install_update=None,
        current_version: str = "",
    ):
        self.on_show_window = on_show_window
        self.on_show_settings = on_show_settings
        self.on_quit = on_quit
        self.on_check_for_updates = on_check_for_updates
        self.on_install_update = on_install_update
        self._icon: pystray.Icon | None = None
        self._current_track_label = "Nothing playing"
        self._icon_default: Image.Image | None = None
        self._icon_listening: Image.Image | None = None
        self._current_version = current_version
        self._available_update: AvailableUpdate | None = None
        self._stop_requested = threading.Event()

    def update_track(self, title: str, artist: str, game_name: str | None = None):
        """Updates the tray tooltip with the current track."""
        if title and artist:
            label = f"{artist} — {title}"
        elif game_name:
            label = f"🎮 {game_name} (unrecognised track)"
        else:
            label = "Nothing playing"

        if game_name and title:
            label = f"🎮 {game_name}: {label}"

        self._current_track_label = label[:63]  # Windows tooltip limit

        if self._icon:
            self._icon.title = self._current_track_label
            self._update_menu()

    def _update_menu(self):
        if self._icon:
            self._icon.menu = self._build_menu()

    def set_available_update(self, update: AvailableUpdate | None):
        self._available_update = update
        self._update_menu()

    def _build_menu(self) -> pystray.Menu:
        items = [
            pystray.MenuItem(self._current_track_label, None, enabled=False),
        ]

        if self._current_version:
            items.extend(
                [
                    pystray.MenuItem(f"Euterpium {self._current_version}", None, enabled=False),
                ]
            )

        if self._available_update is not None and self.on_install_update:
            items.extend(
                [
                    pystray.MenuItem(
                        f"Install update {self._available_update.version}",
                        lambda: self.on_install_update(),
                    ),
                ]
            )

        update_items = []
        if self.on_check_for_updates:
            update_items.append(
                pystray.MenuItem("Check for updates", lambda: self.on_check_for_updates())
            )

        items.extend(
            [
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Show window", lambda: self.on_show_window(), default=True),
                pystray.MenuItem("Settings", lambda: self.on_show_settings()),
                *update_items,
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda: self._quit()),
            ]
        )

        return pystray.Menu(*items)

    def _quit(self):
        self.stop()
        self.on_quit()

    def stop(self):
        self._stop_requested.set()
        if self._icon:
            self._icon.stop()

    def set_listening(self, listening: bool):
        """Swaps the tray icon to indicate active audio fingerprinting."""
        if not self._icon:
            return
        if listening and self._icon_listening:
            self._icon.icon = self._icon_listening
        else:
            self._icon.icon = self._icon_default

    def run(self):
        """Starts the tray icon. Blocks until stopped — run in main thread."""
        if not PYSTRAY_AVAILABLE:
            logger.warning("pystray unavailable — running without tray icon")
            # Keep main thread alive without tray
            import time

            while not self._stop_requested.is_set():
                time.sleep(1)
            return

        self._icon_default = _load_icon_image()
        self._icon_listening = _load_named_icon("app_listening.png")
        self._icon = pystray.Icon(
            name="euterpium",
            icon=self._icon_default,
            title="Euterpium — Nothing playing",
            menu=self._build_menu(),
        )
        self._icon.run()
