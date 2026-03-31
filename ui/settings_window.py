# ui/settings_window.py — Settings dialog (tabbed: Credentials / Audio / Games)

import logging
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

import config

logger = logging.getLogger(__name__)

# Colour palette (matches window.py)
BG       = "#1e1e2e"
BG_CARD  = "#2a2a3e"
BG_INPUT = "#313145"
ACCENT   = "#cba6f7"
TEXT     = "#cdd6f4"
TEXT_DIM = "#6c7086"
TEXT_RED = "#f38ba8"
TEXT_GREEN = "#a6e3a1"


def _styled_label(parent, text, dim=False, **kwargs):
    return tk.Label(
        parent, text=text,
        bg=BG_CARD,
        fg=TEXT_DIM if dim else TEXT,
        font=("Segoe UI", 9),
        **kwargs
    )


def _styled_entry(parent, textvariable, show=None, width=38):
    return tk.Entry(
        parent,
        textvariable=textvariable,
        bg=BG_INPUT, fg=TEXT,
        insertbackground=TEXT,
        relief="flat", bd=4,
        font=("Segoe UI", 10),
        show=show,
        width=width,
    )


class SettingsWindow:
    """
    Modal-ish settings dialog. Created once and shown/hidden as needed.
    Calls on_saved() after a successful save so the app can reload config.
    """

    def __init__(self, parent: tk.Tk, on_saved=None):
        self._parent = parent
        self._on_saved = on_saved
        self._win: tk.Toplevel | None = None

    def show(self):
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._build()

    def _build(self):
        win = tk.Toplevel(self._parent)
        win.title("Euterpium — Settings")
        win.configure(bg=BG)
        win.geometry("520x520")
        win.resizable(True, True)
        win.minsize(460, 460)
        win.grab_set()  # modal
        self._win = win

        # ── Save / Cancel (packed first so they're always visible at bottom) ──
        btn_row = tk.Frame(win, bg=BG, pady=8)
        btn_row.pack(fill="x", padx=12, side="bottom")

        tk.Button(
            btn_row, text="Save", width=10,
            bg=ACCENT, fg=BG,
            font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, cursor="hand2",
            activebackground=ACCENT,
            command=self._save,
        ).pack(side="right", padx=(6, 0))

        tk.Button(
            btn_row, text="Cancel", width=10,
            bg=BG_CARD, fg=TEXT_DIM,
            font=("Segoe UI", 9),
            relief="flat", bd=0, cursor="hand2",
            activebackground=BG_CARD,
            command=win.destroy,
        ).pack(side="right")

        # ── Config path footer (also anchored to bottom) ──────────────────
        footer = tk.Frame(win, bg=BG)
        footer.pack(fill="x", padx=12, pady=(0, 2), side="bottom")

        tk.Label(
            footer,
            text=f"Config: {config.config_path()}",
            font=("Segoe UI", 8),
            bg=BG, fg=TEXT_DIM,
            anchor="w",
        ).pack(side="left")

        tk.Button(
            footer, text="Open folder",
            font=("Segoe UI", 8),
            bg=BG, fg=TEXT_DIM,
            relief="flat", bd=0, cursor="hand2",
            activebackground=BG, activeforeground=ACCENT,
            command=self._open_config_folder,
        ).pack(side="left", padx=(8, 0))

        # ── Notebook (tabs — fills remaining space) ───────────────────────
        style = ttk.Style(win)
        style.theme_use("default")
        style.configure("TNotebook",       background=BG,      borderwidth=0)
        style.configure("TNotebook.Tab",   background=BG_CARD, foreground=TEXT_DIM,
                        padding=[12, 6],   font=("Segoe UI", 9))
        style.map("TNotebook.Tab",
                  background=[("selected", BG)],
                  foreground=[("selected", ACCENT)])
        style.configure("TFrame", background=BG_CARD)

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        creds_tab  = ttk.Frame(nb, padding=16)
        audio_tab  = ttk.Frame(nb, padding=16)
        games_tab  = ttk.Frame(nb, padding=16)

        nb.add(creds_tab, text="Credentials")
        nb.add(audio_tab, text="Audio")
        nb.add(games_tab, text="Games")

        self._build_credentials(creds_tab)
        self._build_audio(audio_tab)
        self._build_games(games_tab)

    # ── Credentials tab ───────────────────────────────────────────────────────

    def _build_credentials(self, parent):
        self._acr_host   = tk.StringVar(value=config.get_acrcloud_host())
        self._acr_key    = tk.StringVar(value=config.get_acrcloud_access_key())
        self._acr_secret = tk.StringVar(value=config.get_acrcloud_access_secret())
        self._api_url    = tk.StringVar(value=config.get_api_url())
        self._api_key    = tk.StringVar(value=config.get_api_key())

        fields = [
            ("ACRCloud", None,            None),
            ("Host",          self._acr_host,   False),
            ("Access Key",    self._acr_key,    False),
            ("Access Secret", self._acr_secret, True),
            (None,            None,             None),
            ("Your API",      None,             None),
            ("Endpoint URL",  self._api_url,    False),
            ("API Key",       self._api_key,    True),
        ]

        for label, var, secret in fields:
            if var is None:
                # Section heading or spacer
                if label:
                    tk.Label(parent, text=label.upper(), bg=BG_CARD,
                             fg=TEXT_DIM, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(10, 2))
                continue

            _styled_label(parent, label).pack(anchor="w", pady=(6, 1))
            _styled_entry(parent, var, show="•" if secret else None).pack(anchor="w")

    # ── Audio tab ─────────────────────────────────────────────────────────────

    def _build_audio(self, parent):
        self._poll_interval  = tk.StringVar(value=str(config.get_poll_interval()))
        self._capture_secs   = tk.StringVar(value=str(config.get_capture_seconds()))
        self._threshold      = tk.StringVar(value=str(config.get_change_threshold()))
        self._min_silence    = tk.StringVar(value=str(config.get_min_silence_before_change()))

        fields = [
            ("Poll interval (seconds)",
             self._poll_interval,
             "How often to sample audio energy when a game is running"),
            ("Capture length (seconds)",
             self._capture_secs,
             "Length of audio sent to ACRCloud for fingerprinting"),
            ("Change threshold (0.0 – 1.0)",
             self._threshold,
             "RMS energy delta that triggers a new recognition — raise if too sensitive"),
            ("Min quiet checks before change",
             self._min_silence,
             "Consecutive silent samples before treating silence as a track change"),
        ]

        for label, var, hint in fields:
            _styled_label(parent, label).pack(anchor="w", pady=(10, 1))
            _styled_entry(parent, var, width=12).pack(anchor="w")
            _styled_label(parent, hint, dim=True).pack(anchor="w")

    # ── Games tab ─────────────────────────────────────────────────────────────

    def _build_games(self, parent):
        _styled_label(
            parent,
            "One game per line:  process_name.exe = Display Name",
            dim=True,
        ).pack(anchor="w", pady=(0, 6))

        frame = tk.Frame(parent, bg=BG_CARD)
        frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self._games_text = tk.Text(
            frame,
            bg=BG_INPUT, fg=TEXT,
            insertbackground=TEXT,
            font=("Consolas", 10),
            relief="flat", bd=4,
            yscrollcommand=scrollbar.set,
            wrap="none",
        )
        self._games_text.pack(fill="both", expand=True)
        scrollbar.config(command=self._games_text.yview)

        # Populate from current config
        games = config.get_known_games()
        for proc, name in games.items():
            self._games_text.insert("end", f"{proc} = {name}\n")

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self):
        try:
            # Validate numeric fields
            poll     = float(self._poll_interval.get())
            capture  = float(self._capture_secs.get())
            thresh   = float(self._threshold.get())
            silence  = int(self._min_silence.get())

            if not (0 < poll <= 60):
                raise ValueError("Poll interval must be between 0 and 60")
            if not (1 <= capture <= 30):
                raise ValueError("Capture length must be between 1 and 30")
            if not (0.0 <= thresh <= 1.0):
                raise ValueError("Change threshold must be between 0.0 and 1.0")

        except ValueError as e:
            messagebox.showerror("Invalid settings", str(e), parent=self._win)
            return

        # Parse games text box
        games = {}
        for line in self._games_text.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if "=" in line:
                proc, _, name = line.partition("=")
                games[proc.strip()] = name.strip()

        ok = config.save({
            "acrcloud": {
                "host":          self._acr_host.get().strip(),
                "access_key":    self._acr_key.get().strip(),
                "access_secret": self._acr_secret.get().strip(),
            },
            "api": {
                "url": self._api_url.get().strip(),
                "key": self._api_key.get().strip(),
            },
            "audio": {
                "poll_interval":             str(poll),
                "capture_seconds":           str(capture),
                "change_threshold":          str(thresh),
                "min_silence_before_change": str(silence),
            },
            "games": games,
        })

        if not ok:
            messagebox.showerror(
                "Save failed",
                f"Could not write to:\n{config.config_path()}\n\n"
                "Check that the file is not read-only and that you have write permission to the folder.",
                parent=self._win,
            )
            return

        if self._on_saved:
            self._on_saved()

        self._win.destroy()

    def _open_config_folder(self):
        """Opens the config directory in the OS file manager."""
        folder = os.path.dirname(config.config_path())
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            logger.warning(f"Could not open config folder: {e}")
