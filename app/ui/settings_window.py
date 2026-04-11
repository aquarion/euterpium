# ui/settings_window.py — Settings dialog (tabbed: Credentials / Audio / Games)

import logging
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import config
import startup

logger = logging.getLogger(__name__)

# Colour palette (matches window.py)
BG = "#1e1e2e"
BG_CARD = "#2a2a3e"
BG_INPUT = "#313145"
ACCENT = "#cba6f7"
TEXT = "#cdd6f4"
TEXT_DIM = "#6c7086"
TEXT_RED = "#f38ba8"
TEXT_GREEN = "#a6e3a1"


def _styled_label(parent, text, dim=False, **kwargs):
    return tk.Label(
        parent, text=text, bg=BG_CARD, fg=TEXT_DIM if dim else TEXT, font=("Segoe UI", 9), **kwargs
    )


def _styled_entry(parent, textvariable, show=None, width=38):
    return tk.Entry(
        parent,
        textvariable=textvariable,
        bg=BG_INPUT,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        bd=4,
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
        win.resizable(True, True)
        win.minsize(460, 400)
        win.grab_set()  # modal
        self._win = win

        # ── Save / Cancel (packed first so they're always visible at bottom) ──
        btn_row = tk.Frame(win, bg=BG, pady=8)
        btn_row.pack(fill="x", padx=12, side="bottom")

        tk.Button(
            btn_row,
            text="Save",
            width=10,
            bg=ACCENT,
            fg=BG,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
            activebackground=ACCENT,
            command=self._save,
        ).pack(side="right", padx=(6, 0))

        tk.Button(
            btn_row,
            text="Cancel",
            width=10,
            bg=BG_CARD,
            fg=TEXT_DIM,
            font=("Segoe UI", 9),
            relief="flat",
            bd=0,
            cursor="hand2",
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
            bg=BG,
            fg=TEXT_DIM,
            anchor="w",
        ).pack(side="left")

        tk.Button(
            footer,
            text="Open folder",
            font=("Segoe UI", 8),
            bg=BG,
            fg=TEXT_DIM,
            relief="flat",
            bd=0,
            cursor="hand2",
            activebackground=BG,
            activeforeground=ACCENT,
            command=self._open_config_folder,
        ).pack(side="left", padx=(8, 0))

        # ── Notebook (tabs — fills remaining space) ───────────────────────
        style = ttk.Style(win)
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=BG_CARD,
            foreground=TEXT_DIM,
            padding=[12, 6],
            font=("Segoe UI", 9),
        )
        style.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", ACCENT)])
        style.configure("TFrame", background=BG_CARD)

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        general_tab = ttk.Frame(nb, padding=16)
        creds_tab = ttk.Frame(nb, padding=16)
        audio_tab = ttk.Frame(nb, padding=16)
        media_tab = ttk.Frame(nb, padding=16)
        games_tab = ttk.Frame(nb, padding=16)
        server_tab = ttk.Frame(nb, padding=16)

        nb.add(general_tab, text="General")
        nb.add(creds_tab, text="Credentials")
        nb.add(audio_tab, text="Audio")
        nb.add(media_tab, text="Media")
        nb.add(games_tab, text="Games")
        nb.add(server_tab, text="Server")

        self._build_general(general_tab)
        self._build_credentials(creds_tab)
        self._build_audio(audio_tab)
        self._build_media(media_tab)
        self._build_games(games_tab)
        self._build_server(server_tab)

    # ── General tab ───────────────────────────────────────────────────────────

    def _build_general(self, parent):
        self._launch_on_startup = tk.BooleanVar(value=startup.is_enabled())

        if sys.platform == "win32":
            tk.Checkbutton(
                parent,
                text="Launch on startup",
                variable=self._launch_on_startup,
                bg=BG_CARD,
                fg=TEXT,
                selectcolor=BG_INPUT,
                activebackground=BG_CARD,
                activeforeground=TEXT,
                font=("Segoe UI", 10),
                relief="flat",
                bd=0,
                cursor="hand2",
            ).pack(anchor="w", pady=(4, 2))

            _styled_label(
                parent,
                "Start Euterpium automatically when you log in to Windows.",
                dim=True,
            ).pack(anchor="w", padx=(24, 0))

    # ── Credentials tab ───────────────────────────────────────────────────────

    def _build_credentials(self, parent):
        self._acr_host = tk.StringVar(value=config.get_acrcloud_host())
        self._acr_key = tk.StringVar(value=config.get_acrcloud_access_key())
        self._acr_secret = tk.StringVar(value=config.get_acrcloud_access_secret())

        # ACRCloud section
        tk.Label(
            parent, text="ACRCLOUD", bg=BG_CARD, fg=TEXT_DIM, font=("Segoe UI", 8, "bold")
        ).pack(anchor="w", pady=(10, 2))
        for label, var, secret in [
            ("Host", self._acr_host, False),
            ("Access Key", self._acr_key, False),
            ("Access Secret", self._acr_secret, True),
        ]:
            _styled_label(parent, label).pack(anchor="w", pady=(6, 1))
            _styled_entry(parent, var, show="•" if secret else None).pack(anchor="w")

        # API profiles section
        tk.Label(
            parent, text="YOUR API", bg=BG_CARD, fg=TEXT_DIM, font=("Segoe UI", 8, "bold")
        ).pack(anchor="w", pady=(16, 2))

        # State: {name: {url: StringVar, key: StringVar}}
        self._api_profiles: dict[str, dict[str, tk.StringVar]] = {}
        self._active_profile = tk.StringVar(value=config.get_active_profile())

        for name, vals in config.get_api_profiles().items():
            self._api_profiles[name] = {
                "url": tk.StringVar(value=vals["url"]),
                "key": tk.StringVar(value=vals["key"]),
            }

        # Left column: profile list + controls
        cols = tk.Frame(parent, bg=BG_CARD)
        cols.pack(fill="both", expand=True, pady=(4, 0))

        list_col = tk.Frame(cols, bg=BG_CARD)
        list_col.pack(side="left", fill="y", padx=(0, 10))

        self._profile_listbox = tk.Listbox(
            list_col,
            bg=BG_INPUT,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=BG,
            font=("Segoe UI", 10),
            relief="flat",
            bd=4,
            width=12,
            height=6,
            exportselection=False,
        )
        self._profile_listbox.pack(fill="x")
        self._profile_listbox.bind("<<ListboxSelect>>", self._on_profile_select)

        # Right column: URL + key for selected profile
        detail_col = tk.Frame(cols, bg=BG_CARD)
        detail_col.pack(side="left", fill="both", expand=True)

        self._profile_name_label = tk.Label(
            detail_col,
            text="",
            bg=BG_CARD,
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
        )
        self._profile_name_label.pack(anchor="w")

        self._detail_url_var = tk.StringVar()
        self._detail_key_var = tk.StringVar()

        _styled_label(detail_col, "Endpoint URL").pack(anchor="w", pady=(6, 1))
        self._detail_url_entry = _styled_entry(detail_col, self._detail_url_var, width=30)
        self._detail_url_entry.pack(anchor="w")

        _styled_label(detail_col, "API Key").pack(anchor="w", pady=(6, 1))
        self._detail_key_entry = _styled_entry(detail_col, self._detail_key_var, show="•", width=30)
        self._detail_key_entry.pack(anchor="w")

        self._detail_url_var.trace_add("write", self._sync_detail_to_profile)
        self._detail_key_var.trace_add("write", self._sync_detail_to_profile)

        self._active_label = _styled_label(detail_col, "", dim=True)
        self._active_label.pack(anchor="w", pady=(6, 0))

        # Profile action buttons — horizontal row below both columns
        btn_row = tk.Frame(parent, bg=BG_CARD)
        btn_row.pack(fill="x", pady=(4, 0))

        for text, cmd in [
            ("+ Add", self._add_profile),
            ("Rename", self._rename_profile),
            ("− Remove", self._remove_profile),
            ("Set Active", self._set_active_profile),
        ]:
            tk.Button(
                btn_row,
                text=text,
                bg=BG_CARD,
                fg=TEXT_DIM,
                font=("Segoe UI", 8),
                relief="flat",
                bd=0,
                cursor="hand2",
                activebackground=BG_CARD,
                activeforeground=ACCENT,
                command=cmd,
            ).pack(side="left", padx=(0, 8))

        self._selected_profile: str | None = None
        self._detail_syncing = False

        self._refresh_profile_list()

    def _refresh_profile_list(self):
        self._profile_listbox.delete(0, "end")
        active = self._active_profile.get()
        for name in self._api_profiles:
            display = f"{name} ✓" if name == active else name
            self._profile_listbox.insert("end", display)

        # Re-select the previously selected item
        if self._selected_profile and self._selected_profile in self._api_profiles:
            idx = list(self._api_profiles.keys()).index(self._selected_profile)
            self._profile_listbox.selection_set(idx)
            self._show_profile(self._selected_profile)
        elif self._api_profiles:
            self._profile_listbox.selection_set(0)
            self._show_profile(next(iter(self._api_profiles)))

    def _on_profile_select(self, _event=None):
        sel = self._profile_listbox.curselection()
        if not sel:
            return
        name = list(self._api_profiles.keys())[sel[0]]
        self._show_profile(name)

    def _show_profile(self, name: str):
        self._selected_profile = name
        vars_ = self._api_profiles[name]
        self._detail_syncing = True
        self._detail_url_var.set(vars_["url"].get())
        self._detail_key_var.set(vars_["key"].get())
        self._detail_syncing = False
        active = self._active_profile.get()
        self._profile_name_label.config(text=name)
        self._active_label.config(text="(active)" if name == active else "")

    def _sync_detail_to_profile(self, *_):
        if self._detail_syncing or not self._selected_profile:
            return
        if self._selected_profile in self._api_profiles:
            self._api_profiles[self._selected_profile]["url"].set(self._detail_url_var.get())
            self._api_profiles[self._selected_profile]["key"].set(self._detail_key_var.get())

    def _add_profile(self):
        dialog = tk.Toplevel(self._win)
        dialog.title("Add Profile")
        dialog.configure(bg=BG)
        dialog.geometry("260x100")
        dialog.resizable(False, False)
        dialog.grab_set()

        name_var = tk.StringVar()
        _styled_label(dialog, "Profile name:", dim=False).pack(anchor="w", padx=12, pady=(12, 2))
        entry = _styled_entry(dialog, name_var, width=28)
        entry.pack(anchor="w", padx=12)
        entry.focus_set()

        def confirm():
            name = name_var.get().strip()
            if not name or name in self._api_profiles:
                return
            self._api_profiles[name] = {"url": tk.StringVar(), "key": tk.StringVar()}
            self._refresh_profile_list()
            dialog.destroy()

        entry.bind("<Return>", lambda _: confirm())
        tk.Button(
            dialog,
            text="Add",
            bg=ACCENT,
            fg=BG,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
            activebackground=ACCENT,
            command=confirm,
        ).pack(anchor="e", padx=12, pady=8)

    def _rename_profile(self):
        if not self._selected_profile:
            return
        old_name = self._selected_profile

        dialog = tk.Toplevel(self._win)
        dialog.title("Rename Profile")
        dialog.configure(bg=BG)
        dialog.geometry("260x100")
        dialog.resizable(False, False)
        dialog.grab_set()

        name_var = tk.StringVar(value=old_name)
        _styled_label(dialog, "New name:", dim=False).pack(anchor="w", padx=12, pady=(12, 2))
        entry = _styled_entry(dialog, name_var, width=28)
        entry.pack(anchor="w", padx=12)
        entry.selection_range(0, "end")
        entry.focus_set()

        def confirm():
            new_name = name_var.get().strip()
            if not new_name or new_name == old_name:
                dialog.destroy()
                return
            if new_name in self._api_profiles:
                return
            # Rebuild dict preserving order
            self._api_profiles = {
                (new_name if k == old_name else k): v for k, v in self._api_profiles.items()
            }
            if self._active_profile.get() == old_name:
                self._active_profile.set(new_name)
            self._selected_profile = new_name
            self._refresh_profile_list()
            dialog.destroy()

        entry.bind("<Return>", lambda _: confirm())
        tk.Button(
            dialog,
            text="Rename",
            bg=ACCENT,
            fg=BG,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
            activebackground=ACCENT,
            command=confirm,
        ).pack(anchor="e", padx=12, pady=8)

    def _remove_profile(self):
        if not self._selected_profile:
            return
        if self._selected_profile == self._active_profile.get():
            messagebox.showwarning(
                "Cannot remove", "Cannot remove the active profile.", parent=self._win
            )
            return
        del self._api_profiles[self._selected_profile]
        self._selected_profile = None
        self._refresh_profile_list()

    def _set_active_profile(self):
        if self._selected_profile:
            self._active_profile.set(self._selected_profile)
            self._refresh_profile_list()

    # ── Audio tab ─────────────────────────────────────────────────────────────

    def _build_audio(self, parent):
        self._poll_interval = tk.StringVar(value=str(config.get_poll_interval()))
        self._capture_secs = tk.StringVar(value=str(config.get_capture_seconds()))
        self._threshold = tk.StringVar(value=str(config.get_change_threshold()))
        self._min_silence = tk.StringVar(value=str(config.get_min_silence_before_change()))

        fields = [
            (
                "Poll interval (seconds)",
                self._poll_interval,
                "How often to sample audio energy when a game is running",
            ),
            (
                "Capture length (seconds)",
                self._capture_secs,
                "Length of audio sent to ACRCloud for fingerprinting",
            ),
            (
                "Change threshold (0.0 – 1.0)",
                self._threshold,
                "RMS energy delta that triggers a new recognition — raise if too sensitive",
            ),
            (
                "Min quiet checks before change",
                self._min_silence,
                "Consecutive silent samples before treating silence as a track change",
            ),
        ]

        for label, var, hint in fields:
            _styled_label(parent, label).pack(anchor="w", pady=(10, 1))
            _styled_entry(parent, var, width=12).pack(anchor="w")
            _styled_label(parent, hint, dim=True).pack(anchor="w")

    # ── Media tab ─────────────────────────────────────────────────────────────

    def _build_media(self, parent):
        _styled_label(
            parent,
            "Ignored media apps — one name per line",
            dim=False,
        ).pack(anchor="w", pady=(0, 2))
        _styled_label(
            parent,
            "Any Windows media session whose app ID contains this text is skipped (case-insensitive).",
            dim=True,
        ).pack(anchor="w", pady=(0, 6))

        frame = tk.Frame(parent, bg=BG_CARD)
        frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self._media_ignore_text = tk.Text(
            frame,
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            font=("Consolas", 10),
            relief="flat",
            bd=4,
            yscrollcommand=scrollbar.set,
            wrap="none",
        )
        self._media_ignore_text.pack(fill="both", expand=True)
        scrollbar.config(command=self._media_ignore_text.yview)

        for entry in config.get_smtc_ignored_apps():
            self._media_ignore_text.insert("end", f"{entry}\n")

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
            bg=BG_INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            font=("Consolas", 10),
            relief="flat",
            bd=4,
            yscrollcommand=scrollbar.set,
            wrap="none",
        )
        self._games_text.pack(fill="both", expand=True)
        scrollbar.config(command=self._games_text.yview)

        # Populate from current config
        games = config.get_known_games()
        for proc, name in games.items():
            self._games_text.insert("end", f"{proc} = {name}\n")

    # ── Server tab ────────────────────────────────────────────────────────────

    def _build_server(self, parent):
        self._rest_api_enabled = tk.BooleanVar(value=config.get_rest_api_enabled())
        self._rest_api_port = tk.StringVar(value=str(config.get_rest_api_port()))

        tk.Label(
            parent, text="REST API", bg=BG_CARD, fg=TEXT_DIM, font=("Segoe UI", 8, "bold")
        ).pack(anchor="w", pady=(10, 6))

        tk.Checkbutton(
            parent,
            text="Enable local REST API server",
            variable=self._rest_api_enabled,
            bg=BG_CARD,
            fg=TEXT,
            selectcolor=BG_INPUT,
            activebackground=BG_CARD,
            activeforeground=TEXT,
            font=("Segoe UI", 9),
            relief="flat",
            bd=0,
        ).pack(anchor="w")

        _styled_label(
            parent,
            "Used by the Playnite plugin and other integrations. Listens on 127.0.0.1 only.",
            dim=True,
        ).pack(anchor="w", pady=(2, 12))

        _styled_label(parent, "Port").pack(anchor="w", pady=(0, 1))
        _styled_entry(parent, self._rest_api_port, width=8).pack(anchor="w")
        _styled_label(parent, "Default: 43174. Changes take effect on restart.", dim=True).pack(
            anchor="w", pady=(2, 0)
        )

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self):
        try:
            # Validate numeric fields
            poll = float(self._poll_interval.get())
            capture = float(self._capture_secs.get())
            thresh = float(self._threshold.get())
            silence = int(self._min_silence.get())

            if not (0 < poll <= 60):
                raise ValueError("Poll interval must be between 0 and 60")
            if not (1 <= capture <= 30):
                raise ValueError("Capture length must be between 1 and 30")
            if not (0.0 <= thresh <= 1.0):
                raise ValueError("Change threshold must be between 0.0 and 1.0")

            # Only validate the REST API port when the server is enabled; when disabled
            # an invalid/empty port field should not block saving other settings.
            if self._rest_api_enabled.get():
                rest_port = int(self._rest_api_port.get())
                if not (1024 <= rest_port <= 65535):
                    raise ValueError("REST API port must be between 1024 and 65535")
            else:
                try:
                    rest_port = int(self._rest_api_port.get())
                except ValueError:
                    rest_port = config.get_rest_api_port()

        except ValueError as e:
            messagebox.showerror("Invalid settings", str(e), parent=self._win)
            return

        # Parse media ignore list
        ignored = [
            line.strip().lower()
            for line in self._media_ignore_text.get("1.0", "end").splitlines()
            if line.strip() and not line.strip().startswith(";")
        ]

        # Parse games text box
        games = {}
        for line in self._games_text.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if "=" in line:
                proc, _, name = line.partition("=")
                games[proc.strip()] = name.strip()

        api_sections = {"api": {"active": self._active_profile.get()}}
        for name, vars_ in self._api_profiles.items():
            api_sections[f"api:{name}"] = {
                "url": vars_["url"].get().strip(),
                "key": vars_["key"].get().strip(),
            }

        ok = config.save(
            {
                "acrcloud": {
                    "host": self._acr_host.get().strip(),
                    "access_key": self._acr_key.get().strip(),
                    "access_secret": self._acr_secret.get().strip(),
                },
                **api_sections,
                "audio": {
                    "poll_interval": str(poll),
                    "capture_seconds": str(capture),
                    "change_threshold": str(thresh),
                    "min_silence_before_change": str(silence),
                },
                "smtc": {"ignore": ", ".join(ignored)},
                "games": games,
                "rest_api": {
                    "enabled": "true" if self._rest_api_enabled.get() else "false",
                    "port": str(rest_port),
                },
            }
        )

        if not ok:
            messagebox.showerror(
                "Save failed",
                f"Could not write to:\n{config.config_path()}\n\n"
                "Check that the file is not read-only and that you have write permission to the folder.",
                parent=self._win,
            )
            return

        if self._launch_on_startup.get():
            startup_ok = startup.enable()
        else:
            startup_ok = startup.disable()

        if not startup_ok:
            messagebox.showerror(
                "Startup setting failed",
                "The configuration was saved, but the Launch on startup setting could not be changed.\n\n"
                "This can happen if Windows prevents registry changes or you do not have permission "
                "to modify startup settings.",
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
