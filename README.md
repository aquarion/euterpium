# Euterpium

A Windows background app that detects currently playing music and posts now-playing data to a custom API. Named for Euterpe, the Greek muse of music.

It's loosely tied to [Stream Delta](https://github.com/aquarion/stream-delta), my Stream Management & overlay application.

## What it does

- Detects music from any app registered with Windows Media Session (SMTC): Spotify, Apple Music, browsers, Windows Media Player, etc.
- Detects game audio via WASAPI loopback + [ACRCloud](https://www.acrcloud.com/) fingerprinting — useful for games like Final Fantasy XIV whose OSTs are on streaming platforms but don't register with SMTC.
- Posts now-playing data to a configurable API endpoint.
- Lives in the system tray with a settings UI.

## Requirements

- Windows 10/11
- Python 3.10+ (managed via Poetry)
- ACRCloud account (for game audio fingerprinting)

## Setup

```bash
cd app
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
| `app/main.py` | Entry point — wires tracker, tray, window together |
| `app/tracker.py` | Background detection loop |
| `app/smtc.py` | Windows Media Session (SMTC) detection via winsdk |
| `app/fingerprint.py` | ACRCloud audio fingerprinting |
| `app/audio_capture.py` | WASAPI loopback capture + audio change detection |
| `app/game_detector.py` | Detects known game processes via psutil |
| `app/api_client.py` | Posts to the active API profile endpoint |
| `app/config.py` | INI config read/write with multi-profile API support |
| `app/ui/tray.py` | System tray icon (pystray) — swaps icon when fingerprinting |
| `app/ui/window.py` | Main tkinter window |
| `app/ui/settings_window.py` | Tabbed settings dialog |
| `app/ui/notifications.py` | Windows toast notifications (win11toast) |

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

## Playnite integration

Euterpium includes a Playnite generic plugin that automatically tells Euterpium when a game starts and stops. When a game is launched via Playnite, the plugin writes a small JSON file; Euterpium picks it up on the next poll cycle and switches to game audio fingerprinting mode. Works for Steam, GOG, Epic, emulators — any source Playnite can launch.

See [docs/playnite-plugin.md](docs/playnite-plugin.md) for build, install, and auto-update instructions.

## Development

```bash
cd app
poetry install
poetry run pytest          # run tests
poetry run ruff check .    # lint
```
