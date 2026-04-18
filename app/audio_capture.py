# audio_capture.py — WASAPI loopback capture and audio change detection

import io
import logging
import wave
from dataclasses import dataclass

import numpy as np

import config
from config import (
    CAPTURE_SECONDS,
    MIN_SILENCE_BEFORE_CHANGE,
    SAMPLE_RATE,
)

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Return value of AudioChangeDetector.check()."""

    changed: bool
    rms: float
    flatness: float | None = None  # None if silent
    hamming_ratio: float | None = None  # None if silent, noisy, or no prior fingerprint


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


def compute_spectral_flatness(audio: np.ndarray) -> float:
    """
    Returns spectral flatness of audio (0 = pure tone, 1 = white noise).
    Mixes stereo to mono before computing.
    """
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    magnitudes = np.abs(np.fft.rfft(audio))
    magnitudes = magnitudes[magnitudes > 1e-10]
    if len(magnitudes) == 0:
        return 1.0
    geometric_mean = np.exp(np.mean(np.log(magnitudes)))
    arithmetic_mean = np.mean(magnitudes)
    if arithmetic_mean < 1e-10:
        return 1.0
    return float(np.clip(geometric_mean / arithmetic_mean, 0.0, 1.0))


def compute_spectral_fingerprint(audio: np.ndarray, n_bands: int = 32) -> np.ndarray:
    """
    Returns an n_bands-length binary array fingerprinting the spectral shape.
    Bit i is 1 if band i's energy is above the mean across all bands.
    Uses logarithmically-spaced frequency bands to match pitch perception.
    Mixes stereo to mono before computing.
    """
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    magnitudes = np.abs(np.fft.rfft(audio))
    n_freqs = len(magnitudes)

    # n_bands+1 log-spaced bin edges covering the full spectrum
    edges = np.round(np.logspace(0, np.log10(max(n_freqs, 2)), n_bands + 1)).astype(int)
    edges = np.clip(edges, 0, n_freqs)

    band_energies = np.array(
        [
            np.sum(magnitudes[edges[i] : max(edges[i] + 1, edges[i + 1])] ** 2)
            for i in range(n_bands)
        ],
        dtype=float,
    )

    mean_energy = np.mean(band_energies)
    return (band_energies > mean_energy).astype(np.uint8)


class AudioChangeDetector:
    """
    Monitors system audio and signals when the music has meaningfully changed.

    Two-stage check on each 1-second poll sample:
    1. Spectral flatness gate — if audio looks like noise/SFX, skip ACRCloud.
    2. Spectral fingerprint comparison — detect track changes even when loudness
       is constant, by comparing the frequency-band energy profile.

    Tuning constants are read from config on every call so UI changes take
    effect immediately.
    """

    SHORT_SAMPLE = 1.0  # seconds per poll sample

    def __init__(self):
        self._quiet_count: int = 0
        self._last_fingerprint: np.ndarray | None = None

    def check(self) -> CheckResult:
        """
        Takes a short audio sample and returns a CheckResult.
        `result.changed` is True when recognition should be triggered — either
        because the spectral fingerprint has changed significantly (track change)
        or because music was detected for the first time / after a silence gap
        (initial detection).  All other fields carry the metrics used to reach
        that decision.
        Call this on a POLL_INTERVAL loop.
        """
        min_rms = config.get_min_rms()
        flatness_threshold = config.get_spectral_flatness_threshold()
        n_bands = config.get_fingerprint_bands()
        change_threshold = config.get_fingerprint_change_threshold()

        device = get_loopback_device()
        if not device:
            return CheckResult(changed=False, rms=0.0)

        try:
            with device.recorder(samplerate=SAMPLE_RATE) as mic:
                audio = mic.record(numframes=int(SAMPLE_RATE * self.SHORT_SAMPLE))
        except Exception as e:
            logger.debug(f"Short sample capture failed: {e}")
            return CheckResult(changed=False, rms=0.0)

        rms = compute_rms(audio)

        # ── Silence check ──────────────────────────────────────────────────
        if rms < min_rms:
            self._quiet_count += 1
            if self._quiet_count >= MIN_SILENCE_BEFORE_CHANGE:
                self._last_fingerprint = None
                self._quiet_count = 0
            logger.debug(f"AudioChangeDetector: rms={rms:.3f} → silent")
            return CheckResult(changed=False, rms=rms)

        self._quiet_count = 0

        # ── Flatness gate ──────────────────────────────────────────────────
        flatness = compute_spectral_flatness(audio)
        if flatness > flatness_threshold:
            logger.debug(
                f"AudioChangeDetector: rms={rms:.3f} flatness={flatness:.2f} [noise] → skip"
            )
            return CheckResult(changed=False, rms=rms, flatness=flatness)

        n_bands = max(1, n_bands)

        # ── Fingerprint comparison ─────────────────────────────────────────
        fingerprint = compute_spectral_fingerprint(audio, n_bands)

        if self._last_fingerprint is None or len(self._last_fingerprint) != n_bands:
            self._last_fingerprint = fingerprint
            logger.debug(
                f"AudioChangeDetector: rms={rms:.3f} flatness={flatness:.2f}"
                f" [music] no prior fingerprint → storing (trigger)"
            )
            return CheckResult(changed=True, rms=rms, flatness=flatness)

        hamming = int(np.sum(fingerprint != self._last_fingerprint))
        hamming_ratio = hamming / n_bands
        self._last_fingerprint = fingerprint

        if hamming_ratio > change_threshold:
            logger.debug(
                f"AudioChangeDetector: rms={rms:.3f} flatness={flatness:.2f} [music]"
                f" hamming={hamming}/{n_bands} ({hamming_ratio:.3f}) → CHANGE"
            )
            return CheckResult(
                changed=True, rms=rms, flatness=flatness, hamming_ratio=hamming_ratio
            )

        logger.debug(
            f"AudioChangeDetector: rms={rms:.3f} flatness={flatness:.2f} [music]"
            f" hamming={hamming}/{n_bands} ({hamming_ratio:.3f}) → no change"
        )
        return CheckResult(changed=False, rms=rms, flatness=flatness, hamming_ratio=hamming_ratio)
