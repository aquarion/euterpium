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


def identify_audio(wav_bytes: bytes) -> dict | None:
    """
    Sends WAV audio bytes to ACRCloud for identification.
    Returns a normalised result dict on success, or None if unrecognised / error.

    Result dict keys:
        title, artist, album, release_date, acrid, streaming_links
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
        music = result["metadata"]["music"][0]
        artists = ", ".join(a["name"] for a in music.get("artists", []))
        album_info = music.get("album", {})

        # Extract streaming links if available
        streaming = {}
        for platform, info in music.get("external_metadata", {}).items():
            track_id = info.get("track", {}).get("id")
            if track_id:
                streaming[platform] = track_id

        return {
            "source": "acrcloud",
            "title": music.get("title", ""),
            "artist": artists,
            "album": album_info.get("name", ""),
            "release_date": music.get("release_date", ""),
            "acrid": music.get("acrid", ""),
            "streaming_links": streaming,
        }

    except (KeyError, IndexError) as e:
        logger.error(f"ACRCloud response parse error: {e}")
        return None
