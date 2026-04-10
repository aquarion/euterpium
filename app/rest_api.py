# rest_api.py — Local REST API server for Euterpium
#
# Listens on http://127.0.0.1:43174/api
# Swagger UI available at http://127.0.0.1:43174/api/

import logging
import threading

from flask import Blueprint, Flask
from flask_restx import Api, Namespace, Resource, fields

import game_detector

logger = logging.getLogger(__name__)

PORT = 43174
HOST = "127.0.0.1"


def _build_now_playing_payload(tracker) -> dict | None:
    """Build the payload dict that would be sent to the external API."""
    last = tracker.last_track
    if not last:
        return None
    payload = {k: v for k, v in last.items() if not k.startswith("_")}
    game = last.get("_game")
    if game:
        payload["game"] = game
    return payload


def create_app(tracker) -> Flask:
    """Create and configure the Flask application with the REST API."""
    app = Flask(__name__)
    app.config["RESTX_MASK_SWAGGER"] = False

    blueprint = Blueprint("api", __name__, url_prefix="/api")
    api = Api(
        blueprint,
        version="1.0",
        title="Euterpium API",
        description="Local REST interface for Euterpium music fingerprinting.",
        doc="/",
    )

    # ── Models ────────────────────────────────────────────────────────────────

    game_input = api.model(
        "GameStart",
        {
            "process": fields.String(
                required=True,
                description="Executable filename (e.g. witcher3.exe)",
                example="witcher3.exe",
            ),
            "name": fields.String(
                required=True,
                description="Human-readable game name",
                example="The Witcher 3",
            ),
            "pid": fields.Integer(
                required=False,
                description="Process ID for stale-entry detection (optional)",
                example=1234,
            ),
        },
    )

    status_model = api.model(
        "Status",
        {
            "listening": fields.Boolean(description="Whether the tracker loop is running"),
            "last_track": fields.Raw(description="Last detected track payload, or null"),
        },
    )

    message_model = api.model(
        "Message",
        {"message": fields.String(description="Informational message")},
    )

    # ── Namespaces ────────────────────────────────────────────────────────────

    ns_status = Namespace("", description="Tracker status")
    ns_fingerprint = Namespace("fingerprint", description="Fingerprinting controls")
    ns_game = Namespace("game", description="Game lifecycle (Playnite integration)")

    api.add_namespace(ns_status)
    api.add_namespace(ns_fingerprint)
    api.add_namespace(ns_game)

    # ── /api/status ───────────────────────────────────────────────────────────

    @ns_status.route("/status")
    class Status(Resource):
        @ns_status.marshal_with(status_model)
        @ns_status.doc(description="Return current tracker status and last detected track.")
        def get(self):
            return {
                "listening": tracker.is_running,
                "last_track": _build_now_playing_payload(tracker),
            }

    # ── /api/now-playing ──────────────────────────────────────────────────────

    now_playing_model = api.model(
        "NowPlaying",
        {"payload": fields.Raw(description="Payload that would be sent to the external API")},
    )

    @ns_status.route("/now-playing")
    class NowPlaying(Resource):
        @ns_status.marshal_with(now_playing_model)
        @ns_status.doc(description="Return the payload that would be posted to the external API.")
        def get(self):
            return {"payload": _build_now_playing_payload(tracker)}

    # ── /api/fingerprint/now ──────────────────────────────────────────────────

    @ns_fingerprint.route("/now")
    class FingerprintNow(Resource):
        @ns_fingerprint.marshal_with(message_model, code=202)
        @ns_fingerprint.doc(description="Execute an immediate fingerprint (like the 'Fingerprint Now' button).")
        def post(self):
            tracker.force_fingerprint()
            return {"message": "Fingerprint triggered"}, 202

    # ── /api/game/start ───────────────────────────────────────────────────────

    @ns_game.route("/start")
    class GameStart(Resource):
        @ns_game.expect(game_input)
        @ns_game.marshal_with(message_model, code=200)
        @ns_game.doc(description="Notify Euterpium that a game has started. Begins game-audio fingerprinting.")
        def post(self):
            data = api.payload or {}
            process = (data.get("process") or "").strip()
            name = (data.get("name") or "").strip()
            pid = data.get("pid")
            if not process or not name:
                ns_game.abort(400, "Both 'process' and 'name' are required")
            game_detector.set_current_game(process=process, name=name, pid=pid)
            return {"message": f"Game started: {name}"}, 200

    # ── /api/game/stop ────────────────────────────────────────────────────────

    @ns_game.route("/stop")
    class GameStop(Resource):
        @ns_game.marshal_with(message_model, code=200)
        @ns_game.doc(description="Notify Euterpium that the current game has stopped.")
        def post(self):
            game_detector.clear_current_game()
            return {"message": "Game stopped"}, 200

    app.register_blueprint(blueprint)
    return app


def start_server(tracker) -> threading.Thread:
    """Start the REST API server in a background daemon thread."""
    app = create_app(tracker)
    t = threading.Thread(
        target=lambda: app.run(host=HOST, port=PORT, debug=False, use_reloader=False),
        daemon=True,
        name="rest-api",
    )
    t.start()
    logger.info("REST API started on http://%s:%d/api/", HOST, PORT)
    return t
