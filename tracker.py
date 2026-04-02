# tracker.py — Tracker class, runs the detection loop in a background thread

import logging
import queue
import threading
import time

import config
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
        self._last_track_lock = threading.Lock()
        self._fingerprint_lock = threading.Lock()
        self._manual_fingerprint_running = False

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
        """Check if tracker is currently running."""
        return (
            self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()
        )

    def force_fingerprint(self):
        """Force an immediate fingerprint attempt (manual trigger)."""
        if not self.is_running:
            self._emit("error", "Tracker not running")
            return
        # Debounce - prevent overlapping manual fingerprints
        with self._last_track_lock:
            if self._manual_fingerprint_running:
                self._emit("status", "Manual fingerprinting already in progress")
                return
            self._manual_fingerprint_running = True
        threading.Thread(target=self._manual_fingerprint, daemon=True).start()

    def _manual_fingerprint(self):
        """Manual fingerprint logic (runs in separate thread)."""
        try:
            self._emit("status", "Manual fingerprinting requested...")

            # Check ACRCloud configuration (host, key, and secret)
            if not config.get_acrcloud_host() or not config.acrcloud_is_configured():
                self._emit(
                    "error",
                    "ACRCloud not fully configured — check host, access key, and secret",
                )
                return

            game = get_running_game()
            if not game:
                self._emit("status", "No game running — checking SMTC instead")
                track = get_smtc_track_sync(ignored_apps=config.get_smtc_ignored_apps())
                if track:
                    if self._try_set_last_track(track):
                        post_now_playing(track)
                        self._emit("track", track, None)
                    else:
                        self._emit("status", "Same track detected — no change")
                else:
                    self._emit("status", "No media playing")
                return

            # Game is running - try fingerprinting
            self._emit("status", f"Fingerprinting audio from {game['display_name']}...")
            with self._fingerprint_lock:
                audio = capture_audio()
                if audio is None:
                    self._emit("error", "Failed to capture audio")
                    return

                wav = audio_to_wav_bytes(audio)
                track = identify_audio(wav)

            if track:
                if self._try_set_last_track(track):
                    post_now_playing(track, game=game)
                    self._emit("track", track, game)
                    self._emit(
                        "status",
                        f"Identified: {track.get('artist', '?')} - {track.get('title', '?')}",
                    )
                else:
                    self._emit("status", "Same track detected — no change")
            else:
                self._emit("status", f"No match found in {game['display_name']}")

        except Exception as e:
            logger.error(f"Manual fingerprint error: {e}", exc_info=True)
            self._emit("error", f"Fingerprint failed: {e}")
        finally:
            # Always reset the running flag
            with self._last_track_lock:
                self._manual_fingerprint_running = False

    # ── Internal ───────────────────────────────────────────────────────────

    def _emit(self, event_type: str, *args):
        self.event_queue.put((event_type, *args))

    def _try_set_last_track(self, track: dict) -> bool:
        """Atomically update last_track if the new track is meaningfully different."""
        with self._last_track_lock:
            if self._tracks_are_same(track, self.last_track):
                return False
            self.last_track = track
            return True

    def _tracks_are_same(self, a: dict | None, b: dict | None) -> bool:
        if a is None or b is None:
            return False

        # Compare titles (case-insensitive)
        if a.get("title", "").lower() != b.get("title", "").lower():
            return False

        # Compare sources - different sources means different tracks
        if a.get("source") != b.get("source"):
            return False

        # Compare games - same title from different games is different
        a_game = a.get("_game")
        b_game = b.get("_game")
        if a_game != b_game:
            # Handle None cases
            if a_game is None or b_game is None:
                return a_game == b_game
            # Compare game identifiers (prefer display_name, fall back to name)
            a_game_id = a_game.get("display_name") or a_game.get("name")
            b_game_id = b_game.get("display_name") or b_game.get("name")
            return a_game_id == b_game_id

        return True

    def _run(self):
        detector = AudioChangeDetector()

        while not self._stop_event.is_set():
            if self._paused:
                time.sleep(POLL_INTERVAL)
                continue

            try:
                game = get_running_game()

                if game:
                    with self._last_track_lock:
                        manual_fingerprint_running = self._manual_fingerprint_running
                    if manual_fingerprint_running:
                        time.sleep(POLL_INTERVAL)
                        continue

                    changed = detector.check()
                    if changed:
                        self._emit(
                            "status", f"Audio change in {game['display_name']} — fingerprinting…"
                        )
                        if not self._fingerprint_lock.acquire(blocking=False):
                            continue

                        try:
                            audio = capture_audio()
                            if audio is not None:
                                wav = audio_to_wav_bytes(audio)
                                track = identify_audio(wav)

                                if track:
                                    if self._try_set_last_track(track):
                                        post_now_playing(track, game=game)
                                        self._emit("track", track, game)
                                else:
                                    self._emit(
                                        "status", f"No match found in {game['display_name']}"
                                    )
                                    with self._last_track_lock:
                                        current_track = self.last_track
                                    if not (current_track and current_track.get("_game") == game):
                                        fallback = {
                                            "source": "game_only",
                                            "title": "",
                                            "artist": "",
                                            "_game": game,
                                        }
                                        # Don't post_now_playing for unidentified tracks
                                        with self._last_track_lock:
                                            self.last_track = fallback
                                        self._emit("track", fallback, game)
                        finally:
                            self._fingerprint_lock.release()
                else:
                    track = get_smtc_track_sync(ignored_apps=config.get_smtc_ignored_apps())
                    if track and self._try_set_last_track(track):
                        post_now_playing(track)
                        self._emit("track", track, None)
                    elif not track:
                        with self._last_track_lock:
                            if self.last_track is not None:
                                self.last_track = None
                                self._emit("status", "Playback stopped")

            except Exception as e:
                logger.error(f"Tracker error: {e}", exc_info=True)
                self._emit("error", str(e))

            time.sleep(POLL_INTERVAL)
