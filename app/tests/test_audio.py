# tests/test_audio.py — audio_to_wav_bytes, compute_rms, AudioChangeDetector logic

import io
import wave

import numpy as np
import pytest

from audio_capture import AudioChangeDetector, audio_to_wav_bytes, compute_rms

# ── compute_rms ───────────────────────────────────────────────────────────────


def test_compute_rms_silence():
    audio = np.zeros(1000, dtype=np.float32)
    assert compute_rms(audio) == pytest.approx(0.0)


def test_compute_rms_full_amplitude():
    audio = np.ones(1000, dtype=np.float32)
    assert compute_rms(audio) == pytest.approx(1.0)


def test_compute_rms_stereo_mixed_to_mono():
    # Stereo all-ones — mixing to mono should still give RMS of 1.0
    audio = np.ones((1000, 2), dtype=np.float32)
    assert compute_rms(audio) == pytest.approx(1.0)


def test_compute_rms_known_value():
    # sin wave at amplitude 0.5 — RMS = 0.5 / sqrt(2) ≈ 0.3536
    t = np.linspace(0, 2 * np.pi, 10000)
    audio = (0.5 * np.sin(t)).astype(np.float32)
    assert compute_rms(audio) == pytest.approx(0.5 / (2**0.5), rel=1e-3)


# ── audio_to_wav_bytes ────────────────────────────────────────────────────────


def test_audio_to_wav_bytes_produces_valid_wav():
    audio = np.zeros(4410, dtype=np.float32)
    wav = audio_to_wav_bytes(audio)
    with wave.open(io.BytesIO(wav)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2  # 16-bit PCM
        assert wf.getframerate() == 44100
        assert wf.getnframes() == 4410


def test_audio_to_wav_bytes_stereo_mixed_to_mono():
    audio = np.zeros((4410, 2), dtype=np.float32)
    wav = audio_to_wav_bytes(audio)
    with wave.open(io.BytesIO(wav)) as wf:
        assert wf.getnchannels() == 1


def test_audio_to_wav_bytes_clips_at_boundaries():
    # Values outside [-1, 1] should be clipped, not wrap-around
    audio = np.array([2.0, -2.0], dtype=np.float32)
    wav = audio_to_wav_bytes(audio)
    with wave.open(io.BytesIO(wav)) as wf:
        raw = wf.readframes(2)
    samples = np.frombuffer(raw, dtype=np.int16)
    assert samples[0] == 32767
    assert samples[1] == -32767


# ── AudioChangeDetector ───────────────────────────────────────────────────────


def _make_mock_loopback(amplitude_sequence):
    """
    Returns a mock loopback device that yields a constant-amplitude buffer
    for each successive call to record(), cycling through amplitude_sequence.
    """

    call_count = [0]

    class MockRecorder:
        def __init__(self):
            self._amp = amplitude_sequence[min(call_count[0], len(amplitude_sequence) - 1)]
            call_count[0] += 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def record(self, numframes):
            return np.full(numframes, self._amp, dtype=np.float32)

    class MockDevice:
        def recorder(self, samplerate):
            return MockRecorder()

    return MockDevice()


def test_detector_first_check_establishes_baseline(monkeypatch):
    import audio_capture

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: _make_mock_loopback([0.5]))
    detector = AudioChangeDetector()
    assert detector.check() is False
    assert detector._baseline_rms is not None


def test_detector_no_change_on_stable_audio(monkeypatch):
    import audio_capture

    calls = [0]

    def mock_device():
        calls[0] += 1
        return _make_mock_loopback([0.5])

    monkeypatch.setattr(audio_capture, "get_loopback_device", mock_device)
    detector = AudioChangeDetector()
    detector.check()  # establish baseline at 0.5
    result = detector.check()  # same level
    assert result is False


def test_detector_signals_change_on_large_rms_jump(monkeypatch):
    import audio_capture

    amplitudes = [0.05, 0.9]  # quiet then loud — delta ~0.85, well above 0.15 threshold
    idx = [0]

    def mock_device():
        amp = amplitudes[min(idx[0], len(amplitudes) - 1)]
        idx[0] += 1
        return _make_mock_loopback([amp])

    monkeypatch.setattr(audio_capture, "get_loopback_device", mock_device)
    detector = AudioChangeDetector()
    detector.check()  # baseline at 0.05
    result = detector.check()  # jumps to 0.9
    assert result is True


def test_detector_returns_false_when_no_device(monkeypatch):
    import audio_capture

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: None)
    detector = AudioChangeDetector()
    assert detector.check() is False
