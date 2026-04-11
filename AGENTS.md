# Euterpium — agent context

This file is written for AI coding agents. It captures project conventions,
gotchas, and design decisions discovered during earlier sessions, so you don't
have to rediscover them.

---

## What Euterpium is

A Windows desktop app that detects music playing through a running game and
posts "now playing" events to an external webhook API. It also reads Windows
SMTC (System Media Transport Controls) for non-game playback. The UI lives in
the system tray; a small Playnite plugin reports game lifecycle events over a
local REST API.

---

## Repo layout

```text
app/                Python application source + tests
  main.py           Entry point — wires Tracker, TrayIcon, MainWindow, REST server
  tracker.py        Detection loop (background daemon thread)
  game_detector.py  Game detection (API state > Playnite file > process scan)
  rest_api.py       Flask-RESTX server on http://127.0.0.1:43174/api/
  api_client.py     Posts now-playing payload to external webhook
  config.py         Reads/writes euterpium.ini from platform config dir
  smtc.py           Windows SMTC detection (winsdk, Windows-only)
  version.py        Version constants
  ui/               TrayIcon, MainWindow, notifications
  tests/            pytest test suite (one file per module)
playnite-plugin/    C# Playnite extension (posts game start/stop to REST API)
docs/               Developer docs
icons/              Bundled PNG icons (referenced in euterpium.spec)
euterpium.spec      PyInstaller build spec
euterpium.iss       Inno Setup installer script
```

---

## How to run tests and lint

All commands run from `app/` via Poetry:

```bash
unset VIRTUAL_ENV   # VS Code injects VIRTUAL_ENV pointing at a wrong interpreter;
                    # unset it first or Poetry will use it instead of its own venv.
poetry run pytest tests/ -q                        # run all tests
poetry run pytest tests/test_rest_api.py -v        # single file
poetry run ruff check .                            # lint
poetry run ruff format .                           # auto-format
```

Tests use `pytest` ≥ 8.0 and `unittest.mock` (stdlib). There is no `pytest-mock`
dependency; all mocking uses `unittest.mock.patch` / `MagicMock` directly.
`conftest.py` in `tests/` handles shared fixtures.

Non-Windows: `winsdk` / `win11toast` are platform-conditional deps. SMTC tests are
skipped on non-Windows via `pytestmark = pytest.mark.skipif(...)`. Windows-only
modules that need to be tested cross-platform (e.g. `startup.py`) use the lazy
import pattern — `import winreg` inside the function body — so tests can inject a
mock via `patch.dict(sys.modules, {"winreg": mock})`.

### Test conventions (`tests/conftest.py`)

- `conftest.py` inserts `app/` onto `sys.path` at collection time, so test
  files can do bare `import config`, `import tracker`, etc. without any
  package installation.
- The `tmp_config` fixture redirects `_CONFIG_PATH` and `_CONFIG_DIR` to a
  fresh `tmp_path` via `monkeypatch`, so tests never touch the real user config
  file. Use it in any test that reads or writes config.

---

## Config (`config.py`)

- Config file location:
  - Windows: `%LOCALAPPDATA%\euterpium\euterpium.ini`
  - Linux/macOS: `~/.config/euterpium/euterpium.ini`
- On import, `config.py` seeds the user config from the bundled `euterpium.ini`
  (next to the source file) if no user config exists yet.
- **Module-level constants** (`KNOWN_GAMES`, `SAMPLE_RATE`, etc.) are evaluated
  once at import time. Use the `get_*()` functions if you need live values after
  a settings save.
- All `get_*()` functions call `_cfg()` which loads fresh from disk every time,
  so changes to the config file are reflected without restarting the app.
- `config.api_is_configured()` returns False for empty URL and for the
  placeholder URL `https://your-api.com/now-playing`.

---

## Game detection (`game_detector.py`)

Detection priority (highest → lowest):

1. **In-memory API state** — set via `POST /api/game/start`, cleared via
   `POST /api/game/stop`. Protected by `_api_game_lock`.
2. **Playnite file** — `euterpium_current_game.json` (legacy file-based
   transport, still supported for backward compat). Path from
   `config.get_playnite_current_game_path()`.
3. **Process scan** — iterates running processes against the `[games]` section
   in `euterpium.ini`.

For both (1) and (2), if a `pid` is recorded, `psutil.pid_exists(pid)` is
checked on every read to detect stale entries.

---

## REST API (`rest_api.py`)

- Port **43174**, bound to `127.0.0.1` only (loopback).
- Flask-RESTX, Swagger UI at `/api/`.
- Endpoints: `GET /api/status`, `GET /api/now-playing`,
  `POST /api/fingerprint/now`, `POST /api/game/start`, `POST /api/game/stop`.
- `POST /api/game/start` payload: `{"process": "game.exe", "name": "My Game", "pid": 1234}`.
  - `process` and `name` are `required=True, pattern=r'\S+'` in the model
    (validated by schema, not by hand in the handler).
- Started in `main.py` as a daemon thread just before `tray.run()`.

### Dependency gotcha: jsonschema lower bound

`flask-restx>=1.3` with `validate=True` on `@ns.expect()` passes a
`referencing.Registry` object to jsonschema validators using the `registry=`
kwarg — introduced in **jsonschema 4.18.0**. flask-restx itself declares no
minimum jsonschema version, so pip may install an older version and silently
break validation. The explicit lower bound `jsonschema>=4.18.0` in
`pyproject.toml` is load-bearing; do not remove it.

---

## Tracker (`tracker.py`)

- `Tracker.start()` spawns a daemon thread running `_run()`.
- `Tracker.stop()` sets `_stop_event` and emits a status event but **does not
  join** the thread. If you need a clean shutdown you must join `_thread`
  separately.
- `Tracker.is_running` is `thread.is_alive() and not _stop_event.is_set()`.
- `last_track` is protected by `_last_track_lock`. It stores the full track
  dict plus an optional `_game` key (stripped before sending to the external
  API or the REST `/api/now-playing` endpoint).

---

## api_client (`api_client.py`)

- `post_now_playing()` returns `False` immediately (skips the HTTP request) if
  `config.api_is_configured()` is False.
- Reads config live on every call, so credential changes take effect without a
  restart.

---

## SMTC (`smtc.py`)

- Tries `from winsdk.windows.media import ...` at module level.
- On failure (non-Windows, winsdk not installed) sets `WINSDK_AVAILABLE = False`
  and does **not** define `MediaManager` / `MediaPlaybackStatus` names. Code
  that references those names must be gated on `WINSDK_AVAILABLE`.

---

## Versioning (`version.py`)

- `__version__` must remain a quoted string literal (`__version__ = "x.y.z"`).
  The release workflow patches it with a `sed`/regex replace.
- `DEV_VERSION = "0.1.0"` is the sentinel; if `__version__ == DEV_VERSION` at
  runtime, `__display_version__` shows the current git branch name (or "dev").
- `__display_version__` is used by the UI and tray; `__version__` is used for
  logging and update checks.

---

## Release workflow

`.github/workflows/release.yml`:

1. Patches `version.py` `__version__` from the tag / workflow input.
2. Runs PyInstaller (`euterpium.spec`) to produce the `dist/` bundle.
3. Runs Inno Setup (`euterpium.iss`) to produce the installer.
4. Uploads zip + installer + `.sha256` checksum to the GitHub Release.

---

## Validation principle

**Express constraints in the schema/model, not in handler code.**

A `required=True` model field only enforces key *presence*; an empty string
`""` or whitespace-only `"   "` satisfies it. Use `pattern=r'\S+'` (at least
one non-whitespace character) on string fields that must be non-empty. That way:

- The constraint is declared where it belongs (the schema).
- It appears correctly in the Swagger UI.
- The handler code stays clean.

This applies to any flask-restx model and to any similar schema-first framework.

---

## Playnite plugin (`playnite-plugin/`)

- C#, targets .NET Framework 4.6.2 (Playnite's runtime).
- On `OnGameStarted` / `OnGameStopped` posts to the Euterpium REST API.
- `HttpClient` is a singleton field; do not create per-request.
- Async `PostAsync` is called via `Task.Run(() => ...).GetAwaiter().GetResult()`
  to avoid STA-thread deadlocks on .NET Framework (`GetAwaiter().GetResult()`
  directly on `PostAsync` can deadlock when there is an ambient
  `SynchronizationContext`).
