# Euterpium Exporter — Playnite Plugin

A Playnite generic plugin that automatically exports your game library to a JSON file so Euterpium can detect running games without manual configuration.

## How it works

On startup (and whenever games are added, removed, or edited), the plugin writes:

```
%APPDATA%\Playnite\euterpium_games.json
```

Euterpium reads this file on each detection cycle and merges it with any manual `[games]` entries in `euterpium.ini`. Manual entries take precedence over Playnite-detected ones.

Only games with a `File`-type play action are exported — the plugin resolves `{InstallDir}` and similar variables to extract the actual `.exe` filename.

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

By default Euterpium reads the JSON from `%APPDATA%\Playnite\euterpium_games.json`. To override the path, add to `euterpium.ini`:

```ini
[playnite]
games_file = C:\path\to\euterpium_games.json
```
