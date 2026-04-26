# ACRCloud Language Preference

**Date:** 2026-04-26
**Status:** Approved

## Problem

ACRCloud responses contain two distinct language-selection challenges:

1. **`langs` field** — some fields carry a `langs` array of localized alternatives (e.g. a Chinese song whose primary `title` is English with a `zh-Hans` translation in `langs`). The current code always uses the primary value.
2. **`music[]` entry language** — ACRCloud returns multiple database entries for the same track. Different entries may have the same audio fingerprint but different primary languages for artist names (e.g. `"祖堅正慶"` vs `"Masayoshi Soken"`). The current code always picks `[0]`, which may be in the wrong script for the user.

## Goal

Return track title, artist, and album names in the user's preferred language. Default to auto-detecting from Windows locale, with an INI override for power users.

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

In practice, `langs` on artist/album is less common; the more frequent case is multiple `music[]` entries with different primary-language artist names.

## Components

### `config.get_acrcloud_language() -> str`

1. Read `[acrcloud] language` from INI. If non-empty, return it.
2. Lazy-import `winreg` (startup.py pattern — Windows-only module).
3. Read `HKCU\Control Panel\International\LocaleName`.
4. Return the registry value, or `"en"` on any failure.

### `fingerprint._pick_lang(primary: str, langs: list[dict], preferred: str) -> str`

Selects the best available name using the `langs` array:

1. Return `primary` immediately if `langs` is empty or `preferred` is empty.
2. Try exact match: find entry where `code == preferred`.
3. Progressively strip the trailing subtag and retry: `en-GB` → `en`, `zh-Hans-CN` → `zh-Hans` → `zh`.
4. Return the matched `name`, or `primary` if nothing matched.

### `fingerprint._dominant_script(text: str) -> str`

Detects the dominant Unicode script of a string using character range counting. Returns one of `"latin"`, `"cjk"`, `"hangul"`, `"cyrillic"`, or `"unknown"`.

Unicode ranges checked:
- **Latin**: U+0041–U+024F (Basic Latin + Latin Extended A/B)
- **CJK**: U+3040–U+30FF (Hiragana/Katakana) + U+3400–U+4DBF (CJK Ext A) + U+4E00–U+9FFF (CJK Unified)
- **Hangul**: U+1100–U+11FF + U+AC00–U+D7AF
- **Cyrillic**: U+0400–U+04FF

Returns the script with the highest character count. Returns `"unknown"` if no script characters are found (e.g. punctuation-only strings).

### `fingerprint._preferred_script(lang_code: str) -> str`

Maps a BCP-47 language code to the expected script:

| Script | Language codes (prefix-matched) |
|---|---|
| `"cjk"` | `ja`, `zh` |
| `"hangul"` | `ko` |
| `"cyrillic"` | `ru`, `uk`, `bg`, `sr`, `be` |
| `"latin"` | everything else (default) |

Prefix matching: `zh-Hans`, `zh-Hant`, `zh-Hans-CN` all map to `"cjk"` via the `zh` prefix.

### `fingerprint._pick_field(entries: list[dict], field_fn, preferred_script: str) -> str`

Scans a list of `music[]` entries for a field value in the preferred script:

1. For each entry in order, extract the candidate value via `field_fn(entry)`.
2. If `_dominant_script(candidate) == preferred_script`, return it.
3. If no entry matches, return `field_fn(entries[0])` as fallback.

`field_fn` is a callable that extracts a string from a music entry (e.g. `lambda e: e.get("title", "")`).

### `fingerprint.identify_audio` — updated

Call `config.get_acrcloud_language()` and `_preferred_script()` once per invocation.

For each of title, artist names, and album name — two-pass selection:

1. **`langs` pass**: apply `_pick_lang` to the `music[0]` field + its `langs` array.
2. **Script pass**: if the result's dominant script does not match the preferred script, use `_pick_field` to scan all `music[]` entries for one in the preferred script.

The `langs` pass takes priority — if it finds a match, the script scan is skipped for that field.

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
- `music[]` has only one entry: `_pick_field` returns that entry's value directly.
- Unrecognised language code in INI: treated as a literal; `_pick_lang` falls back to primary, `_preferred_script` falls back to `"latin"`. No validation or warning.
- Punctuation-only or very short strings where `_dominant_script` returns `"unknown"`: treated as not matching any preferred script, so the scan continues to the next entry; falls back to `music[0]` value.

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

### `test_fingerprint.py` — `_dominant_script`

| Input | Expected |
|---|---|
| `"Masayoshi Soken"` | `"latin"` |
| `"祖堅正慶"` | `"cjk"` |
| `"마마무"` | `"hangul"` |
| `"Земфира"` | `"cyrillic"` |
| `"!!!"` | `"unknown"` |

### `test_fingerprint.py` — `_preferred_script`

| Input | Expected |
|---|---|
| `"en"` | `"latin"` |
| `"en-GB"` | `"latin"` |
| `"ja"` | `"cjk"` |
| `"zh-Hans"` | `"cjk"` |
| `"ko"` | `"hangul"` |
| `"ru"` | `"cyrillic"` |

### `test_fingerprint.py` — `identify_audio` integration

- **`langs` takes priority**: fixture with `langs` match on title; assert localized title returned without script scan.
- **Script scan for artist**: fixture with two `music[]` entries — `[0]` has Japanese artist, `[1]` has English artist; preferred language `en`; assert English artist returned.
- **Script scan fallback**: fixture where no entry matches preferred script; assert `music[0]` artist returned.
- **Script scan + `langs` together**: fixture where title has a `langs` match but artist requires script scan; assert both resolved correctly.

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
- Script detection for Arabic, Hebrew, Devanagari, or other scripts beyond Latin, CJK, Hangul, and Cyrillic.
