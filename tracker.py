# tracker.py — Tracker class, runs the detection loop in a background thread

import logging
import queue
import threading
import time

from api_client import post_now_playing
from audio_capture import AudioChangeDetector, audio_to_wav_bytes, capture_audio
from config import POLL_INTERVAL
from fingerprint import identify_audio
from game_detector import get_running_game
from smtc import get_smtc_track_sync

logger = logging.getLogger(__name__)


class Tracker:
    """
    Runs the music detection loop in a daemon thread.
    Emits events to an output queue for the UI to consume.

    Event types pushed to the queue:
        ("track", track_dict, game_dict | None)   — new track detected
        ("status", message_str)                   — status update
        ("error", message_str)                    — error message
    """

    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused = False
        self.last_track: dict | None = None

    # ── Public controls ────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._emit("status", "Tracker started")

    def stop(self):
        self._stop_event.set()
        self._emit("status", "Tracker stopped")

    def pause(self):
        self._paused = True
        self._emit("status", "Tracker paused")

    def resume(self):
        self._paused = False
        self._emit("status", "Tracker resumed")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Internal ───────────────────────────────────────────────────────────

    def _emit(self, event_type: str, *args):
        self.event_queue.put((event_type, *args))

    def _tracks_are_same(self, a: dict | None, b: dict | None) -> bool:
        if a is None or b is None:
            return False
        return (
            a.get("title", "").lower() == b.get("title", "").lower()
            and a.get("artist", "").lower() == b.get("artist", "").lower()
        )

    def _run(self):
        detector = AudioChangeDetector()

        while not self._stop_event.is_set():
            if self._paused:
                time.sleep(POLL_INTERVAL)
                continue

            try:
                game = get_running_game()

                if game:
                    changed = detector.check()
                    if changed:
                        self._emit("status", f"Audio change in {game['display_name']} — fingerprinting…")
                        audio = capture_audio()
                        if audio is not None:
                            wav = audio_to_wav_bytes(audio)
                            track = identify_audio(wav)

                            if track:
                                if not self._tracks_are_same(track, self.last_track):
                                    post_now_playing(track, game=game)
                                    self.last_track = track
                                    self._emit("track", track, game)
                            else:
                                self._emit("status", f"No match found in {game['display_name']}")
                                if not (self.last_track and self.last_track.get("_game") == game):
                                    fallback = {
                                        "source": "game_only",
                                        "title": "",
                                        "artist": "",
                                        "_game": game,
                                    }
                                    post_now_playing(
                                        {"source": "game_only", "title": "", "artist": ""},
                                        game=game,
                                    )
                                    self.last_track = fallback
                                    self._emit("track", fallback, game)
                else:
                    track = get_smtc_track_sync()
                    if track and not self._tracks_are_same(track, self.last_track):
                        post_now_playing(track)
                        self.last_track = track
                        self._emit("track", track, None)
                    elif not track and self.last_track is not None:
                        self.last_track = None
                        self._emit("status", "Playback stopped")

            except Exception as e:
                logger.error(f"Tracker error: {e}", exc_info=True)
                self._emit("error", str(e))

            time.sleep(POLL_INTERVAL)
