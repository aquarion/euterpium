# ACRCloud Language Preference

**Date:** 2026-04-26
**Status:** Approved

## Problem

ACRCloud can return track title, artist name, and album name in multiple languages via a `langs` array on each field. The current code always uses the primary (top-level) value. Users whose Windows locale differs from the primary language get whichever language ACRCloud happens to return first.

## Goal

Pick the user's preferred language from the `langs` array when available, falling back to the primary value if no match is found. Default to auto-detecting the preferred language from Windows, with an INI override for power users.

## Approach — Auto-detect with INI override

- Default: read the preferred language from `HKCU\Control Panel\International\LocaleName` (returns BCP-47, e.g. `en-GB`, `zh-Hans-CN`, `ja-JP`).
- Override: if `[acrcloud] language` is set in `euterpium.ini`, use that value instead.
- Final fallback: `en` if the registry read fails or returns empty.

No settings UI change required.

## ACRCloud Response Shape

The `langs` field may appear on `music[].title` (as a top-level key alongside `title`), `music[].artists[].name`, and `music[].album.name`. Each entry is `{"code": "<BCP-47>", "name": "<localized string>"}`. Example:

```json
{
  "title": "Hello",
  "langs": [{"code": "zh-Hans", "name": "你好"}],
  "artists": [{"name": "Artist", "langs": [{"code": "zh-Hans", "name": "艺术家"}]}],
  "album": {"name": "Album", "langs": [{"code": "zh-Hans", "name": "专辑"}]}
}
```

## Components

### `config.get_acrcloud_language() -> str`

1. Read `[acrcloud] language` from INI. If non-empty, return it.
2. Lazy-import `winreg` (startup.py pattern — Windows-only module).
3. Read `HKCU\Control Panel\International\LocaleName`.
4. Return the registry value, or `"en"` on any failure.

### `fingerprint._pick_lang(primary: str, langs: list[dict], preferred: str) -> str`

Selects the best available name for a single field:

1. Return `primary` immediately if `langs` is empty or `preferred` is empty.
2. Try exact match: find entry where `code == preferred`.
3. Progressively strip the trailing subtag and retry: `en-GB` → `en`, `zh-Hans-CN` → `zh-Hans` → `zh`.
4. Return the matched `name`, or `primary` if nothing matched.

### `fingerprint.identify_audio` — updated

Call `config.get_acrcloud_language()` once per invocation, then apply `_pick_lang` to:

- `music["title"]` + `music.get("langs", [])`
- Each `artist["name"]` + `artist.get("langs", [])`
- `album["name"]` + `album.get("langs", [])`

### `euterpium.ini` — bundled default

Add a commented-out key to the `[acrcloud]` section:

```ini
; Preferred language for track/artist/album names returned by ACRCloud.
; Leave blank to auto-detect from Windows. Examples: en, ja, zh-Hans
; language =
```

## Error Handling

- Registry unavailable (non-Windows, permission error): silently fall back to `"en"`.
- `langs` field absent on a music entry: `_pick_lang` receives an empty list and returns `primary` — no change from current behaviour.
- Unrecognised language code in INI: treated as a literal and matched against `langs` entries; if no match, falls back to primary. No validation or warning.

## Testing

### `test_fingerprint.py` — `_pick_lang`

| Scenario | Expected |
|---|---|
| Exact match (`zh-Hans`) | Returns localized name |
| Prefix match (`en-GB` → finds `en`) | Returns localized name |
| Multi-level strip (`zh-Hans-CN` → finds `zh-Hans`) | Returns localized name |
| No match in `langs` | Returns `primary` |
| `langs` is empty list | Returns `primary` |
| `preferred` is empty string | Returns `primary` |

### `test_fingerprint.py` — `identify_audio`

Extend the existing success fixture to include `langs` on title, artist, and album. Assert the preferred language name is returned for each field.

### `test_config.py` — `get_acrcloud_language`

| Scenario | Expected |
|---|---|
| INI has explicit value | Returns INI value (no registry read) |
| INI empty, registry returns `en-GB` | Returns `en-GB` |
| INI empty, registry raises `OSError` | Returns `"en"` |

## Out of Scope

- Settings UI control for language preference.
- Language preference for the `streaming_links` / `external_metadata` payload (passed through verbatim).
- Validation or enumeration of supported ACRCloud language codes.
