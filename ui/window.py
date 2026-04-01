# ui/window.py — tkinter detail window

import os
import queue
import tkinter as tk
from tkinter import ttk
import threading
import logging
from datetime import datetime

from ui.settings_window import SettingsWindow

logger = logging.getLogger(__name__)

# Colour palette
BG         = "#1e1e2e"
BG_CARD    = "#2a2a3e"
ACCENT     = "#cba6f7"   # soft purple
TEXT_MAIN  = "#cdd6f4"
TEXT_DIM   = "#6c7086"
TEXT_GREEN = "#a6e3a1"
TEXT_RED   = "#f38ba8"
TEXT_GOLD  = "#f9e2af"


class MainWindow:
    """
    Tkinter window showing current track and recent history.
    Designed to be shown/hidden rather than destroyed.
    Thread-safe: call update_track() and log_status() from any thread.
    """

    def __init__(self, on_quit, on_show_settings=None):
        self.on_quit = on_quit
        self.on_show_settings = on_show_settings
        self._root: tk.Tk | None = None
        self._visible = False
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()

    # ── Public API (thread-safe) ───────────────────────────────────────────

    def update_track(self, track: dict, game: dict | None):
        self._queue.put(("track", track, game))

    def log_status(self, message: str, level: str = "info"):
        self._queue.put(("status", message, level))

    def show(self):
        self._queue.put(("show",))

    def hide(self):
        self._queue.put(("hide",))

    # ── Main loop (must run in main thread) ───────────────────────────────

    def run(self):
        self._root = tk.Tk()
        self._build_ui()
        self._settings_window = SettingsWindow(self._root, on_saved=self._on_settings_saved)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._ready.set()
        self._poll_queue()
        self._root.mainloop()

    def _poll_queue(self):
        """Drain the cross-thread queue on every tkinter tick."""
        try:
            while True:
                msg = self._queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        self._root.after(100, self._poll_queue)

    def _handle_message(self, msg):
        kind = msg[0]
        if kind == "track":
            _, track, game = msg
            self._set_track(track, game)
        elif kind == "status":
            _, text, level = msg
            self._append_log(text, level)
        elif kind == "show":
            self._show()
        elif kind == "hide":
            self._hide()
        elif kind == "open_settings":
            self._settings_window.show()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        root = self._root
        root.title("Euterpium")
        root.configure(bg=BG)
        root.geometry("520x480")

        icon_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "icons", "app_icon.png"))
        if os.path.exists(icon_path):
            try:
                icon_img = tk.PhotoImage(file=icon_path)
                root.iconphoto(True, icon_img)
            except Exception:
                pass
        root.resizable(True, True)
        root.minsize(400, 360)

        # ── Now playing card ──────────────────────────────────────────────
        card = tk.Frame(root, bg=BG_CARD, padx=20, pady=16)
        card.pack(fill="x", padx=16, pady=(16, 8))

        tk.Label(card, text="NOW PLAYING", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=TEXT_DIM).pack(anchor="w")

        self._lbl_title = tk.Label(
            card, text="—", font=("Segoe UI", 18, "bold"),
            bg=BG_CARD, fg=TEXT_MAIN, wraplength=460, justify="left"
        )
        self._lbl_title.pack(anchor="w", pady=(4, 0))

        self._lbl_artist = tk.Label(
            card, text="", font=("Segoe UI", 12),
            bg=BG_CARD, fg=ACCENT
        )
        self._lbl_artist.pack(anchor="w")

        self._lbl_album = tk.Label(
            card, text="", font=("Segoe UI", 10),
            bg=BG_CARD, fg=TEXT_DIM
        )
        self._lbl_album.pack(anchor="w")

        self._lbl_source = tk.Label(
            card, text="", font=("Segoe UI", 9),
            bg=BG_CARD, fg=TEXT_DIM
        )
        self._lbl_source.pack(anchor="w", pady=(6, 0))

        # ── Status bar (packed before list so it's always visible) ──────────
        status_bar = tk.Frame(root, bg=BG_CARD, pady=6)
        status_bar.pack(fill="x", side="bottom")

        # ── Recent tracks ─────────────────────────────────────────────────
        tk.Label(root, text="RECENT TRACKS", font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=TEXT_DIM).pack(anchor="w", padx=16, pady=(4, 2))

        list_frame = tk.Frame(root, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self._history_box = tk.Text(
            list_frame,
            bg=BG_CARD, fg=TEXT_MAIN,
            font=("Segoe UI", 10),
            relief="flat", bd=0,
            state="disabled",
            yscrollcommand=scrollbar.set,
            cursor="arrow",
            wrap="word",
        )
        self._history_box.pack(fill="both", expand=True)
        scrollbar.config(command=self._history_box.yview)

        # Tag colours for log levels
        self._history_box.tag_config("track",  foreground=TEXT_MAIN)
        self._history_box.tag_config("game",   foreground=TEXT_GOLD)
        self._history_box.tag_config("info",   foreground=TEXT_DIM)
        self._history_box.tag_config("error",  foreground=TEXT_RED)
        self._history_box.tag_config("dim",    foreground=TEXT_DIM)

        self._lbl_status = tk.Label(
            status_bar, text="Running", font=("Segoe UI", 9),
            bg=BG_CARD, fg=TEXT_GREEN
        )
        self._lbl_status.pack(side="left", padx=12)

        tk.Button(
            status_bar, text="Quit",
            font=("Segoe UI", 9),
            bg=BG_CARD, fg=TEXT_DIM,
            relief="flat", bd=0, cursor="hand2",
            activebackground=BG_CARD, activeforeground=TEXT_RED,
            command=self._do_quit,
        ).pack(side="right", padx=12)

        tk.Button(
            status_bar, text="Settings",
            font=("Segoe UI", 9),
            bg=BG_CARD, fg=TEXT_DIM,
            relief="flat", bd=0, cursor="hand2",
            activebackground=BG_CARD, activeforeground=ACCENT,
            command=self._open_settings,
        ).pack(side="right", padx=4)

    # ── Update methods (run in tkinter thread via queue) ──────────────────

    def _set_track(self, track: dict, game: dict | None):
        title  = track.get("title", "") or "Unknown title"
        artist = track.get("artist", "") or ""
        album  = track.get("album", "") or ""
        source = track.get("source", "")

        # Source label
        source_parts = []
        if game:
            source_parts.append(f"🎮 {game['display_name']}")
        if source == "smtc":
            source_parts.append("via Windows Media Session")
        elif source == "acrcloud":
            source_parts.append("via ACRCloud")
        elif source == "game_only":
            title = "Unrecognised track"
            source_parts.append("not on streaming platforms")

        self._lbl_title.config(text=title)
        self._lbl_artist.config(text=artist)
        self._lbl_album.config(text=album)
        self._lbl_source.config(text="  ·  ".join(source_parts))

        # Add to history
        ts = datetime.now().strftime("%H:%M")
        tag = "game" if game else "track"

        self._history_box.config(state="normal")
        if self._history_box.index("end-1c") != "1.0":
            self._history_box.insert("end", "\n")
        self._history_box.insert("end", f"{ts}  ", "dim")
        if title != "Unrecognised track":
            entry = f"{artist} — {title}" if artist else title
        else:
            entry = f"{game['display_name']} — unrecognised"
        self._history_box.insert("end", entry, tag)
        self._history_box.see("end")
        self._history_box.config(state="disabled")

    def _append_log(self, message: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._history_box.config(state="normal")
        if self._history_box.index("end-1c") != "1.0":
            self._history_box.insert("end", "\n")
        self._history_box.insert("end", f"{ts}  {message}", level)
        self._history_box.see("end")
        self._history_box.config(state="disabled")
        self._lbl_status.config(text=message, fg=TEXT_RED if level == "error" else TEXT_DIM)

    def _show(self):
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._visible = True

    def _hide(self):
        self._root.withdraw()
        self._visible = False

    def _on_close(self):
        """Hide to tray instead of closing."""
        self._hide()

    def _on_settings_saved(self):
        import config
        if config.is_configured():
            self._append_log("Credentials saved — tracker is running.", "info")
            self._lbl_status.config(text="Running", fg=TEXT_GREEN)
        else:
            self._append_log("Settings saved.", "info")

    def _open_settings(self):
        if self.on_show_settings:
            self.on_show_settings()

    def _do_quit(self):
        self._root.destroy()
        self.on_quit()
