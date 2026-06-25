# tests/test_api_client.py — post_now_playing behaviour

from unittest.mock import MagicMock, patch

import pytest
import requests

import api_client
import config


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch, tmp_config):
    """Default config state: API configured with a URL and no key."""
    monkeypatch.setattr(config, "api_is_configured", lambda: True)
    monkeypatch.setattr(config, "get_api_url", lambda: "http://example.com/api")
    monkeypatch.setattr(config, "get_api_key", lambda: "")


def _ok_response():
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    return mock


# ── Skipping when not configured ─────────────────────────────────────────────


def test_skips_post_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "api_is_configured", lambda: False)
    with patch("requests.post") as mock_post:
        result = api_client.post_now_playing({"source": "smtc", "title": "T", "artist": "A"})
    assert result is False
    mock_post.assert_not_called()


# ── Successful post ───────────────────────────────────────────────────────────


def test_returns_true_on_success():
    with patch("requests.post", return_value=_ok_response()):
        result = api_client.post_now_playing(
            {"source": "smtc", "title": "Song", "artist": "Artist"}
        )
    assert result is True


def test_posts_track_fields():
    track = {"source": "smtc", "title": "It Overtakes Me", "artist": "The Flaming Lips"}
    with patch("requests.post", return_value=_ok_response()) as mock_post:
        api_client.post_now_playing(track)
    payload = mock_post.call_args.kwargs["json"]
    assert payload["title"] == "It Overtakes Me"
    assert payload["artist"] == "The Flaming Lips"
    assert payload["source"] == "smtc"


def test_includes_game_in_payload():
    game = {"process": "ffxiv_dx11.exe", "display_name": "Final Fantasy XIV"}
    with patch("requests.post", return_value=_ok_response()) as mock_post:
        api_client.post_now_playing({"source": "acrcloud", "title": "Answers"}, game=game)
    payload = mock_post.call_args.kwargs["json"]
    assert payload["game"] == game


def test_no_game_key_when_game_is_none():
    with patch("requests.post", return_value=_ok_response()) as mock_post:
        api_client.post_now_playing({"source": "smtc", "title": "T", "artist": "A"}, game=None)
    payload = mock_post.call_args.kwargs["json"]
    assert "game" not in payload


# ── Auth header ───────────────────────────────────────────────────────────────


def test_includes_auth_header_when_key_set(monkeypatch):
    monkeypatch.setattr(config, "get_api_key", lambda: "my-secret-key")
    with patch("requests.post", return_value=_ok_response()) as mock_post:
        api_client.post_now_playing({"source": "smtc", "title": "T", "artist": "A"})
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer my-secret-key"


def test_no_auth_header_when_key_empty():
    with patch("requests.post", return_value=_ok_response()) as mock_post:
        api_client.post_now_playing({"source": "smtc", "title": "T", "artist": "A"})
    headers = mock_post.call_args.kwargs["headers"]
    assert "Authorization" not in headers


# ── Error handling ────────────────────────────────────────────────────────────


def test_returns_false_on_connection_error():
    with patch("requests.post", side_effect=requests.RequestException("timeout")):
        result = api_client.post_now_playing({"source": "smtc", "title": "T", "artist": "A"})
    assert result is False


def test_returns_false_on_http_error():
    mock = MagicMock()
    mock.raise_for_status.side_effect = requests.HTTPError("403")
    with patch("requests.post", return_value=mock):
        result = api_client.post_now_playing({"source": "smtc", "title": "T", "artist": "A"})
    assert result is False


# ── get_streaming_status ───────────────────────────────────────────────────────


def _status_response(is_live):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"is_live": is_live}
    return mock


def test_streaming_status_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "api_is_configured", lambda: False)
    with patch("requests.get") as mock_get:
        result = api_client.get_streaming_status()
    assert result is None
    mock_get.assert_not_called()


def test_streaming_status_returns_true_when_live():
    with patch("requests.get", return_value=_status_response(True)) as mock_get:
        result = api_client.get_streaming_status()
    assert result is True
    assert mock_get.call_args.args[0] == "http://example.com/api/streaming-status"


def test_streaming_status_returns_false_when_not_live():
    with patch("requests.get", return_value=_status_response(False)):
        result = api_client.get_streaming_status()
    assert result is False


def test_streaming_status_includes_auth_header_when_key_set(monkeypatch):
    monkeypatch.setattr(config, "get_api_key", lambda: "my-secret-key")
    with patch("requests.get", return_value=_status_response(True)) as mock_get:
        api_client.get_streaming_status()
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer my-secret-key"


def test_streaming_status_returns_none_on_connection_error():
    with patch("requests.get", side_effect=requests.RequestException("timeout")):
        result = api_client.get_streaming_status()
    assert result is None


def test_streaming_status_returns_none_on_http_error():
    mock = MagicMock()
    mock.raise_for_status.side_effect = requests.HTTPError("500")
    with patch("requests.get", return_value=mock):
        result = api_client.get_streaming_status()
    assert result is None
