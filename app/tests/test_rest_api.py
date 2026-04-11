# tests/test_rest_api.py — REST API endpoint tests

import threading
from unittest.mock import MagicMock, patch

import pytest

import config
import game_detector
from rest_api import create_app

_TEST_KEY = "not-a-real-key"  # noqa: S105 — not a secret, just a test fixture value


@pytest.fixture(autouse=True)
def reset_api_game():
    """Ensure the in-memory game state is cleared between tests."""
    game_detector.clear_current_game()
    yield
    game_detector.clear_current_game()


@pytest.fixture(autouse=True)
def no_auth(monkeypatch):
    """Disable bearer-token auth for all tests that don't specifically test it."""
    monkeypatch.setattr(config, "get_rest_api_key", lambda: "")


def _make_tracker(is_running=True, last_track=None):
    tracker = MagicMock()
    tracker.is_running = is_running
    tracker.last_track = last_track
    # Use a real Lock so the context manager in _build_now_playing_payload behaves
    # correctly — MagicMock.__exit__ is truthy and would suppress exceptions.
    tracker._last_track_lock = threading.Lock()
    return tracker


@pytest.fixture
def client(request):
    """Return a Flask test client.  Accepts an optional tracker via indirect."""
    tracker = getattr(request, "param", None) or _make_tracker()
    app = create_app(tracker)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── GET /api/status ───────────────────────────────────────────────────────────


def test_status_running_no_track(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["listening"] is True
    assert data["last_track"] is None


@pytest.fixture
def client_with_track():
    tracker = _make_tracker(
        is_running=True,
        last_track={
            "source": "acrcloud",
            "title": "Freebird",
            "artist": "Lynyrd Skynyrd",
            "_game": {"process": "game.exe", "display_name": "My Game"},
        },
    )
    app = create_app(tracker)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_status_includes_last_track(client_with_track):
    resp = client_with_track.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["listening"] is True
    track = data["last_track"]
    assert track["title"] == "Freebird"
    assert track["artist"] == "Lynyrd Skynyrd"
    assert track["game"] == {"process": "game.exe", "display_name": "My Game"}
    assert "_game" not in track


def test_status_not_running():
    tracker = _make_tracker(is_running=False)
    app = create_app(tracker)
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/api/status")
    assert resp.status_code == 200
    assert resp.get_json()["listening"] is False


# ── GET /api/now-playing ──────────────────────────────────────────────────────


def test_now_playing_nothing_playing(client):
    resp = client.get("/api/now-playing")
    assert resp.status_code == 200
    assert resp.get_json()["payload"] is None


def test_now_playing_returns_payload(client_with_track):
    resp = client_with_track.get("/api/now-playing")
    assert resp.status_code == 200
    payload = resp.get_json()["payload"]
    assert payload["title"] == "Freebird"
    assert payload["game"]["display_name"] == "My Game"
    assert "_game" not in payload


def test_now_playing_no_game_in_payload():
    tracker = _make_tracker(
        last_track={"source": "smtc", "title": "Changes", "artist": "David Bowie"}
    )
    app = create_app(tracker)
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/api/now-playing")
    assert resp.status_code == 200
    payload = resp.get_json()["payload"]
    assert payload["title"] == "Changes"
    assert "game" not in payload


# ── POST /api/fingerprint/now ─────────────────────────────────────────────────


def test_fingerprint_now_triggers_force_fingerprint(client):
    resp = client.post("/api/fingerprint/now")
    assert resp.status_code == 202


def test_fingerprint_now_calls_tracker(client):
    tracker = _make_tracker()
    app = create_app(tracker)
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.post("/api/fingerprint/now")
    tracker.force_fingerprint.assert_called_once()


def test_fingerprint_now_returns_message(client):
    data = client.post("/api/fingerprint/now").get_json()
    assert "message" in data


# ── POST /api/game/start ──────────────────────────────────────────────────────


def test_game_start_sets_current_game(client):
    resp = client.post(
        "/api/game/start",
        json={"process": "witcher3.exe", "name": "The Witcher 3"},
    )
    assert resp.status_code == 200
    game = game_detector.get_running_game()
    assert game is not None
    assert game["process"] == "witcher3.exe"
    assert game["display_name"] == "The Witcher 3"


def test_game_start_accepts_pid(client):
    with patch("psutil.pid_exists", return_value=True):
        resp = client.post(
            "/api/game/start",
            json={"process": "bg3.exe", "name": "Baldur's Gate 3", "pid": 9999},
        )
        assert resp.status_code == 200
        game = game_detector.get_running_game()
    assert game["process"] == "bg3.exe"


def test_game_start_normalises_process_name(client):
    client.post(
        "/api/game/start",
        json={"process": "  GameEXE.EXE  ", "name": "Game"},
    )
    game = game_detector.get_running_game()
    assert game["process"] == "gameexe.exe"


def test_game_start_missing_process_returns_400(client):
    resp = client.post("/api/game/start", json={"name": "The Witcher 3"})
    assert resp.status_code == 400


def test_game_start_missing_name_returns_400(client):
    resp = client.post("/api/game/start", json={"process": "witcher3.exe"})
    assert resp.status_code == 400


def test_game_start_empty_process_returns_400(client):
    resp = client.post("/api/game/start", json={"process": "", "name": "Game"})
    assert resp.status_code == 400


def test_game_start_whitespace_only_process_returns_400(client):
    resp = client.post("/api/game/start", json={"process": "   ", "name": "Game"})
    assert resp.status_code == 400


def test_game_start_whitespace_only_name_returns_400(client):
    resp = client.post("/api/game/start", json={"process": "game.exe", "name": "   "})
    assert resp.status_code == 400


# ── POST /api/game/stop ───────────────────────────────────────────────────────


def test_game_stop_clears_current_game(client):
    game_detector.set_current_game("witcher3.exe", "The Witcher 3")
    resp = client.post("/api/game/stop")
    assert resp.status_code == 200
    assert game_detector.get_running_game() is None


def test_game_stop_when_no_game_is_ok(client):
    resp = client.post("/api/game/stop")
    assert resp.status_code == 200


def test_game_stop_returns_message(client):
    data = client.post("/api/game/stop").get_json()
    assert "message" in data


# ── Swagger / docs ────────────────────────────────────────────────────────────


def test_swagger_ui_available(client):
    resp = client.get("/api/")
    assert resp.status_code == 200
    assert b"swagger" in resp.data.lower()


def test_swagger_json_available(client):
    resp = client.get("/api/swagger.json")
    assert resp.status_code == 200
    spec = resp.get_json()
    assert spec["info"]["title"] == "Euterpium API"
    # All key paths must appear in the spec
    paths = spec.get("paths", {})
    assert any("/status" in p for p in paths)
    assert any("/now-playing" in p for p in paths)
    assert any("fingerprint" in p for p in paths)
    assert any("/game/start" in p for p in paths)
    assert any("/game/stop" in p for p in paths)


# ── Bearer auth ───────────────────────────────────────────────────────────────


@pytest.fixture
def authed_client(monkeypatch):
    """Test client with bearer auth enabled, returns (client, key)."""
    monkeypatch.setattr(config, "get_rest_api_key", lambda: _TEST_KEY)
    app = create_app(_make_tracker())
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, _TEST_KEY


def test_auth_missing_header_returns_401(authed_client):
    client, _ = authed_client
    assert client.get("/api/status").status_code == 401


def test_auth_wrong_token_returns_401(authed_client):
    client, _ = authed_client
    resp = client.get("/api/status", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_auth_correct_token_grants_access(authed_client):
    client, key = authed_client
    resp = client.get("/api/status", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 200


def test_auth_swagger_ui_exempt(authed_client):
    """Swagger UI must be reachable without auth so users can discover the token."""
    client, _ = authed_client
    assert client.get("/api/").status_code == 200


def test_auth_swagger_json_exempt(authed_client):
    client, _ = authed_client
    assert client.get("/api/swagger.json").status_code == 200


def test_auth_post_endpoint_requires_token(authed_client):
    client, key = authed_client
    assert client.post("/api/fingerprint/now").status_code == 401
    resp = client.post("/api/fingerprint/now", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 202
