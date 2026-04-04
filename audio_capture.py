# audio_capture.py — WASAPI loopback capture and audio change detection

import io
import logging
import wave

import numpy as np

from config import (
    CAPTURE_SECONDS,
    CHANGE_THRESHOLD,
    MIN_SILENCE_BEFORE_CHANGE,
    SAMPLE_RATE,
)

logger = logging.getLogger(__name__)


def get_loopback_device():
    """Returns the default speaker's loopback device for capturing system audio."""
    try:
        import soundcard as sc

        default_speaker = sc.default_speaker()
        loopback = sc.get_microphone(id=str(default_speaker.name), include_loopback=True)
        return loopback
    except Exception as e:
        logger.error(f"Could not get loopback device: {e}")
        return None


def capture_audio(seconds: float = CAPTURE_SECONDS) -> np.ndarray | None:
    """
    Captures system audio output via WASAPI loopback.
    Returns a numpy array of float32 samples, or None on failure.
    """
    device = get_loopback_device()
    if not device:
        return None

    try:
        with device.recorder(samplerate=SAMPLE_RATE) as mic:
            audio = mic.record(numframes=int(SAMPLE_RATE * seconds))
        return audio
    except Exception as e:
        logger.error(f"Audio capture failed: {e}")
        return None


def audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    """
    Converts a numpy audio array to WAV bytes suitable for sending to ACRCloud.
    Mixes down to mono if stereo.
    """
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # stereo -> mono

    # Normalise and convert to 16-bit PCM
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())

    return buf.getvalue()


def compute_rms(audio: np.ndarray) -> float:
    """Returns the RMS energy of an audio array (0.0–1.0 range)."""
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return float(np.sqrt(np.mean(audio**2)))


class AudioChangeDetector:
    """
    Monitors system audio energy over time and signals when a meaningful
    audio change has occurred (e.g. a new track starting).

    Logic:
    - Polls audio RMS every POLL_INTERVAL seconds using a short sample
    - Tracks a rolling baseline of recent energy
    - Flags a change when RMS delta exceeds CHANGE_THRESHOLD
    - Debounces by requiring a brief period of stability after a change
    """

    SHORT_SAMPLE = 1.0  # seconds for energy polling (cheap)

    def __init__(self):
        self._baseline_rms: float | None = None
        self._quiet_count: int = 0
        self._changed: bool = False

    def check(self) -> bool:
        """
        Takes a short audio sample and returns True if a track change
        is detected. Call this on a POLL_INTERVAL loop.
        """
        device = get_loopback_device()
        if not device:
            return False

        try:
            with device.recorder(samplerate=SAMPLE_RATE) as mic:
                audio = mic.record(numframes=int(SAMPLE_RATE * self.SHORT_SAMPLE))
        except Exception as e:
            logger.debug(f"Short sample capture failed: {e}")
            return False

        rms = compute_rms(audio)

        # First reading — establish baseline
        if self._baseline_rms is None:
            self._baseline_rms = rms
            return False

        delta = abs(rms - self._baseline_rms)
        is_quiet = rms < 0.01

        if is_quiet:
            self._quiet_count += 1
        else:
            self._quiet_count = 0

        # Detect a significant energy shift
        if delta > CHANGE_THRESHOLD or self._quiet_count >= MIN_SILENCE_BEFORE_CHANGE:
            self._baseline_rms = rms
            self._quiet_count = 0
            logger.debug(f"Audio change detected (RMS delta={delta:.3f}, rms={rms:.3f})")
            return True

        # Slowly drift baseline toward current level
        self._baseline_rms = self._baseline_rms * 0.95 + rms * 0.05
        return False
