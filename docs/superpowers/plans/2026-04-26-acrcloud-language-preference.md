# ACRCloud Language Preference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return track title, artist, and album names from ACRCloud in the user's preferred language, auto-detected from the Windows locale with an INI override.

**Architecture:** Two selection mechanisms are layered: (1) `_pick_lang` checks a field's `langs` array for a BCP-47 match; (2) if the result is still in the wrong script, `_pick_field` scans all `music[]` entries for one whose primary field is in the preferred script. Language preference is read from config (INI → Windows registry → `"en"`).

**Tech Stack:** Python, `winreg` (lazy import, Windows-only), `configparser`, `pytest`

---

## File Map

| File | Change |
|---|---|
| `app/config.py` | Add `get_acrcloud_language()` after `get_acrcloud_access_secret()` |
| `app/fingerprint.py` | Add `_SCRIPT_PREFIXES`, `_dominant_script()`, `_preferred_script()`, `_pick_lang()`, `_pick_field()` between `_build_signature` and `identify_audio`; replace `identify_audio()` body |
| `app/euterpium.ini` | Add commented `language` key to `[acrcloud]` section |
| `app/tests/test_config.py` | Add tests for `get_acrcloud_language()` |
| `app/tests/test_fingerprint.py` | Add tests for all new helpers + 4 integration tests |

---

### Task 1: `config.get_acrcloud_language()`

**Files:**
- Modify: `app/config.py` (after `get_acrcloud_access_secret()`)
- Modify: `app/tests/test_config.py` (append new tests)

- [ ] **Step 1: Write the failing tests**

Add to the top of `app/tests/test_config.py` (after existing imports):

```python
import sys
import types
```

Append to `app/tests/test_config.py`:

```python
# ── ACRCloud language ──────────────────────────────────────────────────────────


def test_get_acrcloud_language_explicit_ini(tmp_config):
    config.save({"acrcloud": {"language": "ja"}})
    assert config.get_acrcloud_language() == "ja"


def test_get_acrcloud_language_from_registry(tmp_config, monkeypatch):
    fake_winreg = types.ModuleType("winreg")
    fake_winreg.HKEY_CURRENT_USER = 0

    class _FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    fake_winreg.OpenKey = lambda *a: _FakeKey()
    fake_winreg.QueryValueEx = lambda key, name: ("en-GB", 1)
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert config.get_acrcloud_language() == "en-GB"


def test_get_acrcloud_language_registry_error_returns_en(tmp_config, monkeypatch):
    fake_winreg = types.ModuleType("winreg")
    fake_winreg.HKEY_CURRENT_USER = 0

    def _raise(*a):
        raise OSError("no registry")

    fake_winreg.OpenKey = _raise
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert config.get_acrcloud_language() == "en"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd app && poetry run pytest tests/test_config.py -k "acrcloud_language" -v
```

Expected: 3 FAILs with `AttributeError: module 'config' has no attribute 'get_acrcloud_language'`

- [ ] **Step 3: Implement `get_acrcloud_language()`**

Add to `app/config.py` after `get_acrcloud_access_secret()`:

```python
def get_acrcloud_language() -> str:
    """Returns the preferred language code for ACRCloud results.

    Priority: [acrcloud] language in INI → Windows locale → 'en'.
    """
    explicit = _cfg().get("acrcloud", "language", fallback="").strip()
    if explicit:
        return explicit
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\International") as key:
            value, _ = winreg.QueryValueEx(key, "LocaleName")
            if not isinstance(value, str):
                return "en"
            stripped = value.strip()
            return stripped if stripped else "en"
    except (ImportError, OSError):
        return "en"
```

The narrow `(ImportError, OSError)` catch is consistent with the rest of `config.py` (specific exceptions, not bare `except Exception`). The `isinstance(value, str)` guard handles the realistic non-string failure mode (e.g. registry returns `None`) without re-broadening the catch.

- [ ] **Step 4: Run tests to verify they pass**

```
cd app && poetry run pytest tests/test_config.py -k "acrcloud_language" -v
```

Expected: 3 PASSes

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/tests/test_config.py
git commit -m "feat: add config.get_acrcloud_language() with Windows locale detection"
```

---

### Task 2: `fingerprint._dominant_script()`

**Files:**
- Modify: `app/fingerprint.py` (add before `identify_audio`)
- Modify: `app/tests/test_fingerprint.py` (append new tests + update import)

- [ ] **Step 1: Write the failing tests**

Update the import line at the top of `app/tests/test_fingerprint.py` from:

```python
from fingerprint import _build_signature
```

to:

```python
from fingerprint import _build_signature, _dominant_script
```

Append to `app/tests/test_fingerprint.py`:

```python
# ── _dominant_script ──────────────────────────────────────────────────────────


def test_dominant_script_latin():
    assert _dominant_script("Masayoshi Soken") == "latin"


def test_dominant_script_cjk_kanji():
    assert _dominant_script("祖堅正慶") == "cjk"


def test_dominant_script_cjk_hiragana():
    assert _dominant_script("あいうえお") == "cjk"


def test_dominant_script_hangul():
    assert _dominant_script("마마무") == "hangul"


def test_dominant_script_cyrillic():
    assert _dominant_script("Земфира") == "cyrillic"


def test_dominant_script_unknown_for_punctuation():
    assert _dominant_script("!!!") == "unknown"


def test_dominant_script_empty_string():
    assert _dominant_script("") == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "dominant_script" -v
```

Expected: 7 FAILs with `ImportError: cannot import name '_dominant_script'`

- [ ] **Step 3: Add `_dominant_script()` to `fingerprint.py`**

Insert after the `_build_signature` function (before `identify_audio`) in `app/fingerprint.py`:

```python
def _dominant_script(text: str) -> str:
    counts: dict[str, int] = {"latin": 0, "cjk": 0, "hangul": 0, "cyrillic": 0}
    for ch in text:
        cp = ord(ch)
        if 0x0041 <= cp <= 0x024F:
            counts["latin"] += 1
        elif 0x3040 <= cp <= 0x30FF or 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF:
            counts["cjk"] += 1
        elif 0x1100 <= cp <= 0x11FF or 0xAC00 <= cp <= 0xD7AF:
            counts["hangul"] += 1
        elif 0x0400 <= cp <= 0x04FF:
            counts["cyrillic"] += 1
    if not any(counts.values()):
        return "unknown"
    return max(counts, key=counts.get)
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "dominant_script" -v
```

Expected: 7 PASSes

- [ ] **Step 5: Commit**

```bash
git add app/fingerprint.py app/tests/test_fingerprint.py
git commit -m "feat: add fingerprint._dominant_script() for Unicode script detection"
```

---

### Task 3: `fingerprint._preferred_script()`

**Files:**
- Modify: `app/fingerprint.py` (add after `_dominant_script`)
- Modify: `app/tests/test_fingerprint.py` (append tests + update import)

- [ ] **Step 1: Write the failing tests**

Update import in `app/tests/test_fingerprint.py`:

```python
from fingerprint import _build_signature, _dominant_script, _preferred_script
```

Append to `app/tests/test_fingerprint.py`:

```python
# ── _preferred_script ─────────────────────────────────────────────────────────


def test_preferred_script_en_is_latin():
    assert _preferred_script("en") == "latin"


def test_preferred_script_en_gb_is_latin():
    assert _preferred_script("en-GB") == "latin"


def test_preferred_script_ja_is_cjk():
    assert _preferred_script("ja") == "cjk"


def test_preferred_script_zh_hans_is_cjk():
    assert _preferred_script("zh-Hans") == "cjk"


def test_preferred_script_zh_hans_cn_is_cjk():
    assert _preferred_script("zh-Hans-CN") == "cjk"


def test_preferred_script_ko_is_hangul():
    assert _preferred_script("ko") == "hangul"


def test_preferred_script_ru_is_cyrillic():
    assert _preferred_script("ru") == "cyrillic"


def test_preferred_script_unknown_code_defaults_to_latin():
    assert _preferred_script("xx-Unknown") == "latin"


def test_preferred_script_empty_string_defaults_to_latin():
    assert _preferred_script("") == "latin"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "preferred_script" -v
```

Expected: 9 FAILs with `ImportError: cannot import name '_preferred_script'`

- [ ] **Step 3: Add `_SCRIPT_PREFIXES` and `_preferred_script()` to `fingerprint.py`**

Insert after `_dominant_script()` in `app/fingerprint.py`:

```python
_SCRIPT_PREFIXES: dict[str, tuple[str, ...]] = {
    "cjk": ("ja", "zh"),
    "hangul": ("ko",),
    "cyrillic": ("ru", "uk", "bg", "sr", "be"),
}


def _preferred_script(lang_code: str) -> str:
    lower = lang_code.lower()
    for script, prefixes in _SCRIPT_PREFIXES.items():
        if any(lower == p or lower.startswith(p + "-") for p in prefixes):
            return script
    return "latin"
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "preferred_script" -v
```

Expected: 9 PASSes

- [ ] **Step 5: Commit**

```bash
git add app/fingerprint.py app/tests/test_fingerprint.py
git commit -m "feat: add fingerprint._preferred_script() mapping BCP-47 codes to scripts"
```

---

### Task 4: `fingerprint._pick_lang()`

**Files:**
- Modify: `app/fingerprint.py` (add after `_preferred_script`)
- Modify: `app/tests/test_fingerprint.py` (append tests + update import)

- [ ] **Step 1: Write the failing tests**

Update import in `app/tests/test_fingerprint.py`:

```python
from fingerprint import _build_signature, _dominant_script, _preferred_script, _pick_lang
```

Append to `app/tests/test_fingerprint.py`:

```python
# ── _pick_lang ────────────────────────────────────────────────────────────────


def test_pick_lang_exact_match():
    langs = [{"code": "zh-Hans", "name": "你好"}]
    assert _pick_lang("Hello", langs, "zh-Hans") == ("你好", True)


def test_pick_lang_prefix_match_strips_region():
    langs = [{"code": "en", "name": "Hello"}]
    assert _pick_lang("Hola", langs, "en-GB") == ("Hello", True)


def test_pick_lang_multi_level_strip():
    langs = [{"code": "zh-Hans", "name": "你好"}]
    assert _pick_lang("Hello", langs, "zh-Hans-CN") == ("你好", True)


def test_pick_lang_no_match_returns_primary():
    langs = [{"code": "ja", "name": "こんにちは"}]
    assert _pick_lang("Hello", langs, "en") == ("Hello", False)


def test_pick_lang_empty_langs_returns_primary():
    assert _pick_lang("Hello", [], "en") == ("Hello", False)


def test_pick_lang_empty_preferred_returns_primary():
    langs = [{"code": "en", "name": "Hello"}]
    assert _pick_lang("Hola", langs, "") == ("Hola", False)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "pick_lang" -v
```

Expected: 6 FAILs with `ImportError: cannot import name '_pick_lang'`

- [ ] **Step 3: Add `_pick_lang()` to `fingerprint.py`**

Insert after `_preferred_script()` in `app/fingerprint.py`:

```python
def _pick_lang(primary: str, langs: list[dict], preferred: str) -> tuple[str, bool]:
    if not langs or not preferred:
        return primary, False
    candidate = preferred
    while candidate:
        for entry in langs:
            if entry.get("code", "").lower() == candidate.lower():
                name = entry.get("name")
                if name:
                    return name, True
        if "-" not in candidate:
            break
        candidate = candidate.rsplit("-", 1)[0]
    return primary, False
```

The `(value, matched)` tuple lets callers preserve langs-pass priority: when `matched` is True they should skip the script-scan fallback regardless of what script the localized name happens to be in.

- [ ] **Step 4: Run tests to verify they pass**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "pick_lang" -v
```

Expected: 6 PASSes

- [ ] **Step 5: Commit**

```bash
git add app/fingerprint.py app/tests/test_fingerprint.py
git commit -m "feat: add fingerprint._pick_lang() for langs-array language selection"
```

---

### Task 5: `fingerprint._pick_field()`

**Files:**
- Modify: `app/fingerprint.py` (add after `_pick_lang`)
- Modify: `app/tests/test_fingerprint.py` (append tests + update import)

- [ ] **Step 1: Write the failing tests**

Update import in `app/tests/test_fingerprint.py`:

```python
from fingerprint import _build_signature, _dominant_script, _preferred_script, _pick_lang, _pick_field
```

Append to `app/tests/test_fingerprint.py`:

```python
# ── _pick_field ───────────────────────────────────────────────────────────────


def test_pick_field_returns_entry_in_preferred_script():
    entries = [
        {"title": "祖堅正慶"},
        {"title": "Masayoshi Soken"},
    ]
    assert _pick_field(entries, lambda e: e["title"], "latin") == "Masayoshi Soken"


def test_pick_field_falls_back_to_first_when_no_match():
    entries = [
        {"title": "祖堅正慶"},
        {"title": "最終幻想"},
    ]
    assert _pick_field(entries, lambda e: e["title"], "latin") == "祖堅正慶"


def test_pick_field_returns_first_when_it_already_matches():
    entries = [
        {"title": "Masayoshi Soken"},
        {"title": "祖堅正慶"},
    ]
    assert _pick_field(entries, lambda e: e["title"], "latin") == "Masayoshi Soken"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "pick_field" -v
```

Expected: 3 FAILs with `ImportError: cannot import name '_pick_field'`

- [ ] **Step 3: Add `_pick_field()` to `fingerprint.py`**

Insert after `_pick_lang()` in `app/fingerprint.py`:

```python
def _pick_field(entries: list[dict], field_fn, preferred_script: str) -> str:
    for entry in entries:
        value = field_fn(entry)
        if value and _dominant_script(value) == preferred_script:
            return value
    return field_fn(entries[0])
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "pick_field" -v
```

Expected: 3 PASSes

- [ ] **Step 5: Commit**

```bash
git add app/fingerprint.py app/tests/test_fingerprint.py
git commit -m "feat: add fingerprint._pick_field() for script-based music[] entry scanning"
```

---

### Task 6: Update `identify_audio()`

**Files:**
- Modify: `app/fingerprint.py` (replace `identify_audio` body)
- Modify: `app/tests/test_fingerprint.py` (append integration tests)

- [ ] **Step 1: Write the failing integration tests**

Append to `app/tests/test_fingerprint.py`:

```python
# ── identify_audio — language selection ──────────────────────────────────────


def test_identify_audio_picks_title_from_langs(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "你好",
                        "langs": [{"code": "en", "name": "Hello"}],
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album"},
                        "release_date": "",
                        "acrid": "abc",
                        "external_metadata": {},
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_language", lambda: "en")

    result = fingerprint.identify_audio(b"audio")
    assert result["title"] == "Hello"


def test_identify_audio_picks_artist_by_script_scan(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "The Aetherial Sea",
                        "artists": [{"name": "祖堅正慶"}],
                        "album": {"name": "ENDWALKER: FINAL FANTASY XIV Original Soundtrack"},
                        "release_date": "2022-02-23",
                        "acrid": "abc1",
                        "external_metadata": {},
                    },
                    {
                        "title": "The Aetherial Sea",
                        "artists": [{"name": "Masayoshi Soken"}],
                        "album": {"name": "ENDWALKER: FINAL FANTASY XIV Original Soundtrack"},
                        "release_date": "2022-02-23",
                        "acrid": "abc2",
                        "external_metadata": {},
                    },
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_language", lambda: "en")

    result = fingerprint.identify_audio(b"audio")
    assert result["artist"] == "Masayoshi Soken"


def test_identify_audio_script_scan_falls_back_to_first_entry(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "曲名",
                        "artists": [{"name": "アーティスト"}],
                        "album": {"name": "アルバム"},
                        "release_date": "",
                        "acrid": "abc",
                        "external_metadata": {},
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_language", lambda: "en")

    result = fingerprint.identify_audio(b"audio")
    assert result["artist"] == "アーティスト"


def test_identify_audio_langs_title_and_script_scan_artist(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "你好",
                        "langs": [{"code": "en", "name": "Hello"}],
                        "artists": [{"name": "祖堅正慶"}],
                        "album": {"name": "Album"},
                        "release_date": "",
                        "acrid": "abc1",
                        "external_metadata": {},
                    },
                    {
                        "title": "你好",
                        "artists": [{"name": "Masayoshi Soken"}],
                        "album": {"name": "Album"},
                        "release_date": "",
                        "acrid": "abc2",
                        "external_metadata": {},
                    },
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_language", lambda: "en")

    result = fingerprint.identify_audio(b"audio")
    assert result["title"] == "Hello"
    assert result["artist"] == "Masayoshi Soken"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd app && poetry run pytest tests/test_fingerprint.py -k "identify_audio and (langs or script_scan)" -v
```

Expected: 4 FAILs — `identify_audio` still returns `music[0]` primary values without language selection

- [ ] **Step 3: Replace `identify_audio()` body in `fingerprint.py`**

Replace the entire `identify_audio` function with:

```python
def identify_audio(wav_bytes: bytes) -> dict | None:
    """
    Sends WAV audio bytes to ACRCloud for identification.
    Returns a normalised result dict on success, or None if unrecognised / error.

    Result dict keys:
        title, artist, album, release_date, acrid, streaming_links

    ``streaming_links`` contains the raw ACRCloud ``external_metadata`` object
    verbatim — a dict keyed by platform (e.g. ``spotify``, ``deezer``,
    ``youtube``, ``musicbrainz``) whose values are platform-specific nested
    dicts/lists.  The exact shape depends on what ACRCloud returns for the
    matched track.
    """
    # Read credentials fresh each call so settings changes take effect immediately
    access_key = config.get_acrcloud_access_key()
    access_secret = config.get_acrcloud_access_secret()
    host = config.get_acrcloud_host()

    if not access_key or not access_secret:
        logger.warning("ACRCloud credentials not configured — skipping fingerprint")
        return None

    acrcloud_url = f"https://{host}/v1/identify"
    timestamp = str(int(time.time()))
    signature = _build_signature(timestamp, access_key, access_secret)

    files = {
        "sample": ("sample.wav", wav_bytes, "audio/wav"),
    }
    data = {
        "access_key": access_key,
        "sample_bytes": str(len(wav_bytes)),
        "timestamp": timestamp,
        "signature": signature,
        "data_type": "audio",
        "signature_version": "1",
    }

    try:
        response = requests.post(acrcloud_url, files=files, data=data, timeout=15)
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as e:
        logger.error(f"ACRCloud request failed: {e}")
        return None

    status = result.get("status", {})
    if status.get("code") != 0:
        msg = status.get("msg", "Unknown")
        if status.get("code") == 1001:
            logger.debug("ACRCloud: no result found")
        else:
            logger.warning(f"ACRCloud error {status.get('code')}: {msg}")
        return None

    try:
        music_list = result["metadata"]["music"]
        music = music_list[0]

        preferred_lang = config.get_acrcloud_language()
        preferred_script = _preferred_script(preferred_lang)

        def _artist_str(entry: dict) -> str:
            return ", ".join(
                name for a in entry.get("artists", []) if (name := a.get("name", ""))
            )

        title, title_matched = _pick_lang(
            music.get("title", ""), music.get("langs", []), preferred_lang
        )
        if not title_matched and _dominant_script(title) != preferred_script:
            title = _pick_field(music_list, lambda e: e.get("title", ""), preferred_script)

        artist_results = [
            _pick_lang(a.get("name", ""), a.get("langs", []), preferred_lang)
            for a in music.get("artists", [])
        ]
        artist = ", ".join(value for value, _ in artist_results if value)
        any_artist_matched = any(matched for _, matched in artist_results)
        if not any_artist_matched and _dominant_script(artist) != preferred_script:
            artist = _pick_field(music_list, _artist_str, preferred_script)

        album_info = music.get("album", {})
        album, album_matched = _pick_lang(
            album_info.get("name", ""), album_info.get("langs", []), preferred_lang
        )
        if not album_matched and _dominant_script(album) != preferred_script:
            album = _pick_field(
                music_list, lambda e: e.get("album", {}).get("name", ""), preferred_script
            )

        return {
            "source": "acrcloud",
            "title": title,
            "artist": artist,
            "album": album,
            "release_date": music.get("release_date", ""),
            "acrid": music.get("acrid", ""),
            "streaming_links": music.get("external_metadata", {}),
        }

    except (KeyError, IndexError) as e:
        logger.error(f"ACRCloud response parse error: {e}")
        return None
```

- [ ] **Step 4: Run the full fingerprint test suite**

```
cd app && poetry run pytest tests/test_fingerprint.py -v
```

Expected: all tests pass, including the 4 existing `identify_audio` tests and 4 new integration tests.

- [ ] **Step 5: Commit**

```bash
git add app/fingerprint.py app/tests/test_fingerprint.py
git commit -m "feat: apply language preference in identify_audio via langs + script scanning"
```

---

### Task 7: Update `euterpium.ini` and final check

**Files:**
- Modify: `app/euterpium.ini`

- [ ] **Step 1: Add the commented language key to `[acrcloud]`**

In `app/euterpium.ini`, update the `[acrcloud]` section from:

```ini
[acrcloud]
host        = identify-eu-west-1.acrcloud.com
access_key  =
access_secret =
```

to:

```ini
[acrcloud]
host          = identify-eu-west-1.acrcloud.com
access_key    =
access_secret =
; Preferred language for track/artist/album names returned by ACRCloud.
; Leave blank to auto-detect from Windows locale. Examples: en, ja, zh-Hans
; language =
```

- [ ] **Step 2: Run the full test suite**

```
cd app && poetry run pytest tests/ -q
```

Expected: all tests pass, no regressions.

- [ ] **Step 3: Commit**

```bash
git add app/euterpium.ini
git commit -m "docs: document acrcloud language preference key in bundled euterpium.ini"
```
