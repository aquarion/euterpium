# fingerprint.py — ACRCloud audio fingerprinting integration

import base64
import hashlib
import hmac
import logging
import time

import requests

import config

logger = logging.getLogger(__name__)


def _build_signature(timestamp: str, access_key: str, access_secret: str) -> str:
    """Builds the HMAC-SHA1 signature required by ACRCloud."""
    string_to_sign = "\n".join(
        [
            "POST",
            "/v1/identify",
            access_key,
            "audio",
            "1",
            timestamp,
        ]
    )
    secret_bytes = access_secret.encode("utf-8")
    signature = hmac.new(secret_bytes, string_to_sign.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(signature.digest()).decode("utf-8")


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


def _pick_field(entries: list[dict], field_fn, preferred_script: str) -> str:
    for entry in entries:
        value = field_fn(entry)
        if value and _dominant_script(value) == preferred_script:
            return value
    return field_fn(entries[0])


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
            return ", ".join(a.get("name", "") for a in entry.get("artists", []))

        title, title_matched = _pick_lang(
            music.get("title", ""), music.get("langs", []), preferred_lang
        )
        if not title_matched and _dominant_script(title) != preferred_script:
            title = _pick_field(music_list, lambda e: e.get("title", ""), preferred_script)

        artist_results = [
            _pick_lang(a.get("name", ""), a.get("langs", []), preferred_lang)
            for a in music.get("artists", [])
        ]
        artist = ", ".join(value for value, _ in artist_results)
        all_artists_matched = bool(artist_results) and all(matched for _, matched in artist_results)
        if not all_artists_matched and _dominant_script(artist) != preferred_script:
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
