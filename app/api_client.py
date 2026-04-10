# api_client.py — posts now-playing data to your API

import logging

import requests

import config

logger = logging.getLogger(__name__)


def post_now_playing(track: dict, game: dict | None = None) -> bool:
    """
    Posts a now-playing event to your API.
    Returns False (and skips the request) if the API URL is not configured.

    Payload structure:
    {
        "source": "smtc" | "acrcloud",
        "title": "...",
        "artist": "...",
        "album": "...",
        "game": {                      # only present when playing via a game
            "process": "ffxiv_dx11.exe",
            "display_name": "Final Fantasy XIV"
        },
        "release_date": "...",         # ACRCloud only
        "acrid": "...",                # ACRCloud only
        "streaming_links": { ... },    # ACRCloud only
    }
    """
    # Read live from config so changes take effect without a restart
    api_url = config.get_api_url()
    api_key = config.get_api_key()

    if not config.api_is_configured():
        logger.debug("API URL not configured — skipping post")
        return False

    payload = {**track}
    if game:
        payload["game"] = game

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(f"Posted: {track.get('artist', '?')} - {track.get('title', '?')}")
        return True
    except requests.RequestException as e:
        logger.error(f"API post failed: {e}")
        return False
