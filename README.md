# Euterpium

A Windows background app that detects currently playing music and posts now-playing data to a custom API. Named for Euterpe, the Greek muse of music.

## What it does

- Detects music from any app registered with Windows Media Session (SMTC): Spotify, Apple Music, browsers, Windows Media Player, etc.
- Detects game audio via WASAPI loopback + ACRCloud fingerprinting — useful for games like Final Fantasy XIV whose OSTs are on streaming platforms but don't register with SMTC.
- Posts now-playing data to a configurable API endpoint.
- Lives in the system tray with a settings UI.

## Requirements

- Windows 10/11
- Python 3.10+ (managed via Poetry)
- ACRCloud account (for game audio fingerprinting)

## Setup

```
poetry install
poetry run python main.py
```

On first launch, the settings window opens automatically. Enter your ACRCloud credentials and API endpoint.

Config is stored at `%LOCALAPPDATA%\euterpium\euterpium.ini`.

## Installer and updates

- Release builds now target a Windows installer built from PyInstaller output.
- GitHub Releases should publish both a portable zip and an installer `.exe`.
- The app can check GitHub Releases for a newer installer and offer it from the tray menu.

## Architecture

| File | Purpose |
|------|---------|
| `main.py` | Entry point — wires tracker, tray, window together |
| `tracker.py` | Background detection loop |
| `smtc.py` | Windows Media Session (SMTC) detection via winsdk |
| `fingerprint.py` | ACRCloud audio fingerprinting |
| `audio_capture.py` | WASAPI loopback capture + audio change detection |
| `game_detector.py` | Detects known game processes via psutil |
| `api_client.py` | Posts to the active API profile endpoint |
| `config.py` | INI config read/write with multi-profile API support |
| `ui/tray.py` | System tray icon (pystray) — swaps icon when fingerprinting |
| `ui/window.py` | Main tkinter window |
| `ui/settings_window.py` | Tabbed settings dialog |
| `ui/notifications.py` | Windows toast notifications (win11toast) |

### Detection flow

1. Check for known game processes (psutil).
2. **Game running** → WASAPI loopback capture → ACRCloud fingerprint.
3. **No game** → poll Windows Media Session (SMTC) every N seconds.

### Known limitations

- **Game takes priority over SMTC.** When a known game process is detected, the tracker uses WASAPI + ACRCloud exclusively — SMTC is not polled. Music playing in Spotify alongside a game will not be reported.
- **Only the current SMTC session is checked.** Windows exposes one "current" session at a time (the most recently active one). If Chrome is playing a video and Spotify is also running, only the current session is seen — the ignore list will filter Chrome out, but Spotify won't be detected as a fallback. If this matters, `smtc.py` would need to iterate `sessions.get_sessions()` instead.

### SMTC threading note

Python's default `ProactorEventLoop` (IOCP) conflicts with WinRT async callbacks, causing `RPC_E_CALL_CANCELED`. SMTC calls use `asyncio.SelectorEventLoop` explicitly.

### Apple Music quirks

Apple Music for Windows has two SMTC quirks handled in `smtc.py`:
- Reports playback status as `PAUSED` even when actively playing — treated as playing if track metadata is present.
- Packs `"Artist — Album"` into the artist field and leaves `album_title` empty — split on the em dash.

## API profiles

Euterpium supports multiple named API profiles (dev/stage/live, or any name you choose), switchable from the Settings window without editing the config file.

Profiles are stored as `[api:name]` sections in the INI file:

```ini
[api]
active = live

[api:dev]
url = http://localhost:8000/webhooks/euterpium
key =

[api:live]
url = https://example.com/webhooks/euterpium
key = your-secret-key
```

If you have an older config with a single `[api] url/key`, it is automatically migrated to `[api:dev]` on first launch.

## API payload

Euterpium POSTs JSON to the active profile's endpoint on every track change.

```json
{
    "source": "smtc",
    "title": "It Overtakes Me",
    "artist": "The Flaming Lips",
    "album": "At War with the Mystics (Deluxe Version)"
}
```

When the track is identified via ACRCloud (game audio), additional fields are included:

```json
{
    "source": "acrcloud",
    "title": "Answers",
    "artist": "Susan Calloway",
    "album": "Final Fantasy XIV: A Realm Reborn",
    "release_date": "2013-09-10",
    "acrid": "abc123",
    "streaming_links": { ... }
}
```

When a known game process is running, a `game` object is added regardless of source:

```json
{
    "source": "acrcloud",
    "title": "...",
    "game": {
        "process": "ffxiv_dx11.exe",
        "display_name": "Final Fantasy XIV"
    }
}
```

If an API key is set in the active profile, requests include an `Authorization: Bearer <key>` header.

## Tools / utilities

`smtc_debug.py` — dumps all SMTC sessions and their metadata. Useful for diagnosing detection issues:

```
poetry run python smtc_debug.py
```

## Development

```
poetry install
poetry run pytest          # run tests
poetry run ruff check .    # lint
```
