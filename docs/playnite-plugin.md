# Euterpium Exporter — Playnite Plugin

A Playnite generic plugin that tells Euterpium when a game starts and stops,
so game audio fingerprinting works automatically without manual `[games]` config.

## How it works

When a game is launched via Playnite, the plugin writes:

```
%APPDATA%\Playnite\euterpium_current_game.json
```

When the game stops, the file is deleted. Euterpium reads this file on each
detection cycle — if it exists and the process is still alive, game mode
(WASAPI loopback + ACRCloud fingerprinting) is active.

On Playnite startup, any stale file from a previous crash is cleared.

Works for all sources Playnite can launch: Steam, GOG, Epic, emulators, etc.
Games launched *outside* Playnite are still covered by manual `[games]` entries
in `euterpium.ini`.

## Building

Requires the [.NET SDK](https://aka.ms/dotnet/download) (any recent version).

```
dotnet build playnite-plugin\EuterpiumExporter.csproj
```

The build automatically deploys the plugin to:

```
%APPDATA%\Playnite\Extensions\EuterpiumExporter_a1b2c3d4-e5f6-7890-abcd-ef1234567890\
```

> **Note:** Playnite must be closed before building, as it locks the DLL.

## Installing a release build

Download `EuterpiumExporter_..._.pext` from the [latest release](https://github.com/aquarion/euterpium/releases/latest) and open it — Playnite will install it automatically.

## Auto-updates

Add the following URL once in Playnite under **Settings → For developers → Custom addon repositories**:

```
https://raw.githubusercontent.com/aquarion/euterpium/gh-pages/InstallerManifest.yaml
```

Playnite will check this manifest and prompt you when a new version is available.

## Config

By default Euterpium looks for the current game file at
`%APPDATA%\Playnite\euterpium_current_game.json`. To override the path,
add to `euterpium.ini`:

```ini
[playnite]
current_game_file = C:\path\to\euterpium_current_game.json
```

## Future: REST API

When issue [#16](https://github.com/aquarion/euterpium/issues/16) (local REST API) is implemented, the plugin will be updated to POST to `localhost:43174/api/game/start` and `/api/game/stop` instead of writing a file. The event-driven logic stays the same.
