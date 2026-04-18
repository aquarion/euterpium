# ui/window.py — tkinter detail window

import logging
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import TYPE_CHECKING

import config
from audio_capture import CheckResult
from ui.settings_window import SettingsWindow

if TYPE_CHECKING:
    from updater import AvailableUpdate

logger = logging.getLogger(__name__)

# Colour palette
BG = "#1e1e2e"
BG_CARD = "#2a2a3e"
ACCENT = "#cba6f7"  # soft purple
TEXT_MAIN = "#cdd6f4"
TEXT_DIM = "#6c7086"
TEXT_GREEN = "#a6e3a1"
TEXT_RED = "#f38ba8"
TEXT_GOLD = "#f9e2af"

METER_H = 10  # canvas height in pixels


class MainWindow:
    """
    Tkinter window showing current track and recent history.
    Designed to be shown/hidden rather than destroyed.
    Thread-safe: call update_track(), log_status(), and
    set_delivery_status() from any thread.
    """

    def __init__(
        self,
        on_quit,
        on_show_settings=None,
        on_fingerprint_now=None,
        on_install_update=None,
        current_version: str = "",
    ):
        self.on_quit = on_quit
        self.on_show_settings = on_show_settings
        self.on_fingerprint_now = on_fingerprint_now
        self.on_install_update = on_install_update
        self._current_version = current_version
        self._root: tk.Tk | None = None
        self._visible = False
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()

    # ── Public API (thread-safe) ───────────────────────────────────────────

    def update_track(self, track: dict, game: dict | None):
        self._queue.put(("track", track, game))

    def log_status(self, message: str, level: str = "info"):
        self._queue.put(("status", message, level))

    def set_delivery_status(self, message: str, level: str = "info"):
        self._queue.put(("delivery", message, level))

    def set_available_update(self, update_info: "AvailableUpdate | None"):
        self._queue.put(("update_state", update_info))

    def update_metrics(self, result: "CheckResult"):
        self._queue.put(("metrics", result))

    def hide_meters(self):
        self._queue.put(("game_stopped",))

    def show(self):
        self._queue.put(("show",))

    def hide(self):
        self._queue.put(("hide",))

    # ── Main loop (must run in main thread) ───────────────────────────────

    def run(self):
        self._root = tk.Tk()
        self._root.withdraw()  # hidden until show() is called
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
        elif kind == "delivery":
            _, text, level = msg
            self._set_delivery_status(text, level)
        elif kind == "update_state":
            _, update_info = msg
            self._set_available_update(update_info)
        elif kind == "metrics":
            _, result = msg
            self._update_meters(result)
        elif kind == "game_stopped":
            self._last_metrics = None
            self._meters_frame.pack_forget()
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

        icon_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "icons", "app_icon.png")
        )
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

        tk.Label(
            card, text="NOW PLAYING", font=("Segoe UI", 8, "bold"), bg=BG_CARD, fg=TEXT_DIM
        ).pack(anchor="w")

        self._lbl_title = tk.Label(
            card,
            text="—",
            font=("Segoe UI", 18, "bold"),
            bg=BG_CARD,
            fg=TEXT_MAIN,
            wraplength=460,
            justify="left",
        )
        self._lbl_title.pack(anchor="w", pady=(4, 0))

        self._lbl_artist = tk.Label(card, text="", font=("Segoe UI", 12), bg=BG_CARD, fg=ACCENT)
        self._lbl_artist.pack(anchor="w")

        self._lbl_album = tk.Label(card, text="", font=("Segoe UI", 10), bg=BG_CARD, fg=TEXT_DIM)
        self._lbl_album.pack(anchor="w")

        self._lbl_source = tk.Label(card, text="", font=("Segoe UI", 9), bg=BG_CARD, fg=TEXT_DIM)
        self._lbl_source.pack(anchor="w", pady=(6, 0))

        self._lbl_delivery = tk.Label(
            card, text="Webhook: —", font=("Segoe UI", 9), bg=BG_CARD, fg=TEXT_DIM
        )
        self._lbl_delivery.pack(anchor="w", pady=(4, 0))

        self._build_meters()

        # ── Bottom rows (status + controls) ───────────────────────────────
        bottom_bar = tk.Frame(root, bg=BG_CARD)
        bottom_bar.pack(fill="x", side="bottom")

        status_row = tk.Frame(bottom_bar, bg=BG_CARD, pady=4)
        status_row.pack(fill="x")

        controls_row = tk.Frame(bottom_bar, bg=BG_CARD, pady=6)
        controls_row.pack(fill="x")

        # ── Recent tracks ─────────────────────────────────────────────────
        self._recent_tracks_label = tk.Label(
            root, text="RECENT TRACKS", font=("Segoe UI", 8, "bold"), bg=BG, fg=TEXT_DIM
        )
        self._recent_tracks_label.pack(anchor="w", padx=16, pady=(4, 2))

        list_frame = tk.Frame(root, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self._history_box = tk.Text(
            list_frame,
            bg=BG_CARD,
            fg=TEXT_MAIN,
            font=("Segoe UI", 10),
            relief="flat",
            bd=0,
            state="disabled",
            yscrollcommand=scrollbar.set,
            cursor="arrow",
            wrap="word",
        )
        self._history_box.pack(fill="both", expand=True)
        scrollbar.config(command=self._history_box.yview)

        # Tag colours for log levels
        self._history_box.tag_config("track", foreground=TEXT_MAIN)
        self._history_box.tag_config("game", foreground=TEXT_GOLD)
        self._history_box.tag_config("info", foreground=TEXT_DIM)
        self._history_box.tag_config("error", foreground=TEXT_RED)
        self._history_box.tag_config("dim", foreground=TEXT_DIM)

        self._lbl_status = tk.Label(
            status_row, text="Running", font=("Segoe UI", 9), bg=BG_CARD, fg=TEXT_GREEN
        )
        self._lbl_status.pack(side="left", padx=12)

        if self._current_version:
            self._lbl_version = tk.Label(
                controls_row,
                text=f"{self._current_version}",
                font=("Segoe UI", 9),
                bg=BG_CARD,
                fg=TEXT_DIM,
            )
            self._lbl_version.pack(side="left", padx=12)

        # Update button (initially hidden)
        self._btn_update = tk.Button(
            controls_row,
            text="Install Update",
            font=("Segoe UI", 9),
            bg=ACCENT,
            fg=BG,
            relief="flat",
            bd=0,
            cursor="hand2",
            activebackground=ACCENT,
            activeforeground=BG,
            command=self._install_update,
        )
        self._btn_update.pack_forget()  # Initially hidden

        tk.Button(
            controls_row,
            text="Quit",
            font=("Segoe UI", 9),
            bg=BG_CARD,
            fg=TEXT_DIM,
            relief="flat",
            bd=0,
            cursor="hand2",
            activebackground=BG_CARD,
            activeforeground=TEXT_RED,
            command=self._do_quit,
        ).pack(side="right", padx=12)

        tk.Button(
            controls_row,
            text="Settings",
            font=("Segoe UI", 9),
            bg=BG_CARD,
            fg=TEXT_DIM,
            relief="flat",
            bd=0,
            cursor="hand2",
            activebackground=BG_CARD,
            activeforeground=ACCENT,
            command=self._open_settings,
        ).pack(side="right", padx=4)

        tk.Button(
            controls_row,
            text="Fingerprint Now",
            font=("Segoe UI", 9),
            bg=BG_CARD,
            fg=TEXT_DIM,
            relief="flat",
            bd=0,
            cursor="hand2",
            activebackground=BG_CARD,
            activeforeground=TEXT_GOLD,
            command=self._trigger_fingerprint,
        ).pack(side="right", padx=4)

    def _build_meters(self):
        """Build the spectral metrics strip (flatness + hamming distance gauges)."""
        self._meters_frame = tk.Frame(self._root, bg=BG_CARD, padx=20, pady=6)

        tk.Label(
            self._meters_frame,
            text="AUDIO ANALYSIS",
            font=("Segoe UI", 7, "bold"),
            bg=BG_CARD,
            fg=TEXT_DIM,
        ).pack(anchor="w")

        flat_row = tk.Frame(self._meters_frame, bg=BG_CARD)
        flat_row.pack(fill="x", pady=(3, 0))
        tk.Label(
            flat_row,
            text="Music",
            font=("Segoe UI", 8),
            bg=BG_CARD,
            fg=TEXT_DIM,
            width=5,
            anchor="e",
        ).pack(side="left")
        self._flatness_canvas = tk.Canvas(flat_row, height=METER_H, bg=BG, highlightthickness=0)
        self._flatness_canvas.pack(side="left", fill="x", expand=True, padx=(4, 4))
        tk.Label(
            flat_row,
            text="Noise",
            font=("Segoe UI", 8),
            bg=BG_CARD,
            fg=TEXT_DIM,
            width=5,
            anchor="w",
        ).pack(side="left")

        change_row = tk.Frame(self._meters_frame, bg=BG_CARD)
        change_row.pack(fill="x", pady=(3, 0))
        tk.Label(
            change_row,
            text="Same",
            font=("Segoe UI", 8),
            bg=BG_CARD,
            fg=TEXT_DIM,
            width=5,
            anchor="e",
        ).pack(side="left")
        self._hamming_canvas = tk.Canvas(change_row, height=METER_H, bg=BG, highlightthickness=0)
        self._hamming_canvas.pack(side="left", fill="x", expand=True, padx=(4, 4))
        tk.Label(
            change_row,
            text="Diff",
            font=("Segoe UI", 8),
            bg=BG_CARD,
            fg=TEXT_DIM,
            width=5,
            anchor="w",
        ).pack(side="left")

        self._flatness_canvas.bind("<Configure>", lambda e: self._redraw_meters())
        self._hamming_canvas.bind("<Configure>", lambda e: self._redraw_meters())

        self._last_metrics: CheckResult | None = None
        # Hidden until metrics arrive (i.e. a game is running)

    def _update_meters(self, result: CheckResult):
        self._last_metrics = result
        if not self._meters_frame.winfo_ismapped():
            self._meters_frame.pack(
                fill="x", padx=16, pady=(0, 4), before=self._recent_tracks_label
            )
        self._redraw_meters()

    def _redraw_meters(self):
        if self._last_metrics is None:
            return
        result = self._last_metrics
        flatness_threshold = config.get_spectral_flatness_threshold()
        change_threshold = config.get_fingerprint_change_threshold()

        for canvas in (self._flatness_canvas, self._hamming_canvas):
            canvas.delete("all")

        w_flat = self._flatness_canvas.winfo_width()
        w_ham = self._hamming_canvas.winfo_width()
        h = METER_H

        if w_flat <= 1:
            return

        # ── Flatness bar ───────────────────────────────────────────────────
        if result.flatness is None:
            self._flatness_canvas.create_rectangle(0, 0, w_flat, h, fill=TEXT_DIM, outline="")
        else:
            fill_w = max(1, int(w_flat * result.flatness))
            color = TEXT_GREEN if result.flatness <= flatness_threshold else TEXT_RED
            self._flatness_canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline="")
            tick_x = int(w_flat * flatness_threshold)
            self._flatness_canvas.create_line(tick_x, 0, tick_x, h, fill=TEXT_MAIN, width=1)

        # ── Hamming / change bar ───────────────────────────────────────────
        if w_ham <= 1:
            return

        if result.hamming_ratio is None:
            self._hamming_canvas.create_rectangle(0, 0, w_ham, h, fill=TEXT_DIM, outline="")
        else:
            fill_w = max(1, int(w_ham * result.hamming_ratio))
            color = TEXT_GREEN if result.hamming_ratio <= change_threshold else TEXT_RED
            self._hamming_canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline="")
            tick_x = int(w_ham * change_threshold)
            self._hamming_canvas.create_line(tick_x, 0, tick_x, h, fill=TEXT_MAIN, width=1)

    # ── Update methods (run in tkinter thread via queue) ──────────────────

    def _set_track(self, track: dict, game: dict | None):
        if not game:
            self._last_metrics = None
            self._meters_frame.pack_forget()
        title = track.get("title", "") or "Unknown title"
        artist = track.get("artist", "") or ""
        album = track.get("album", "") or ""
        source = track.get("source", "")

        # Source label
        source_parts = []
        if game:
            source_parts.append(f"🎮 {game['display_name']}")
        if source == "smtc":
            source_name = track.get("source_app_name") or track.get("source_app")
            if source_name:
                source_parts.append(f"via Windows Media Session ({source_name})")
            else:
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

        tag = "game" if game else "track"
        if title != "Unrecognised track":
            entry = f"{artist} — {title}" if artist else title
        else:
            entry = f"{game['display_name']} — unrecognised"
        self._append_history_entry(entry, tag)

    def _append_log(self, message: str, level: str = "info"):
        history_tag = "error" if level == "error" else "dim"

        status_color = TEXT_DIM
        if level == "success":
            status_color = TEXT_GREEN
        elif level == "warn":
            status_color = TEXT_GOLD
        elif level == "error":
            status_color = TEXT_RED

        self._append_history_entry(message, history_tag)
        self._lbl_status.config(text=message, fg=status_color)

    def _history_timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _append_history_entry(self, message: str, tag: str):
        ts = self._history_timestamp()
        self._history_box.config(state="normal")
        if self._history_box.index("end-1c") != "1.0":
            self._history_box.insert("end", "\n")
        self._history_box.insert("end", f"{ts}  ", "dim")
        self._history_box.insert("end", message, tag)
        self._history_box.see("end")
        self._history_box.config(state="disabled")

    def _set_delivery_status(self, message: str, level: str = "info"):
        color = TEXT_DIM
        if level == "success":
            color = TEXT_GREEN
        elif level == "warn":
            color = TEXT_GOLD
        elif level == "error":
            color = TEXT_RED
        self._lbl_delivery.config(text=f"Webhook: {message}", fg=color)

    def _set_available_update(self, update_info: "AvailableUpdate | None"):
        """Show or hide the update button based on update availability."""
        if update_info and self.on_install_update:
            # Show update button next to version only when it can be used
            self._btn_update.config(state="normal")
            self._btn_update.pack(side="left", padx=(4, 12))
        else:
            # Hide update button when no update is available or no handler exists
            self._btn_update.config(state="disabled")
            self._btn_update.pack_forget()

    def _install_update(self):
        """Handle update button click."""
        if self.on_install_update:
            self.on_install_update()

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

    def _trigger_fingerprint(self):
        if self.on_fingerprint_now:
            self.on_fingerprint_now()

    def _do_quit(self):
        self._root.destroy()
        self.on_quit()
