# tests/test_audio.py — audio_to_wav_bytes, compute_rms, AudioChangeDetector logic

import io
import sys
import wave

import numpy as np
import pytest

from audio_capture import (
    AudioChangeDetector,
    CheckResult,
    audio_to_wav_bytes,
    compute_rms,
    compute_spectral_fingerprint,
    compute_spectral_flatness,
)

SAMPLE_RATE = 44100


def _sine(freq_hz: float, duration: float = 1.0) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


# ── CheckResult ───────────────────────────────────────────────────────────────


def test_check_result_instantiation():
    """Verify CheckResult dataclass can be instantiated."""
    result = CheckResult(
        changed=True,
        rms=0.5,
        flatness=0.1,
        hamming_ratio=0.2,
    )
    assert result.changed is True
    assert result.rms == 0.5
    assert result.flatness == 0.1
    assert result.hamming_ratio == 0.2


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


# ── compute_spectral_flatness ─────────────────────────────────────────────────


def test_spectral_flatness_pure_tone_is_low():
    flatness = compute_spectral_flatness(_sine(440))
    assert flatness < 0.3


def test_spectral_flatness_white_noise_is_high():
    rng = np.random.default_rng(42)
    noise = rng.uniform(-1, 1, SAMPLE_RATE).astype(np.float32)
    flatness = compute_spectral_flatness(noise)
    assert flatness > 0.5


def test_spectral_flatness_silence_returns_one():
    audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
    assert compute_spectral_flatness(audio) == pytest.approx(1.0)


def test_spectral_flatness_stereo_mixed_to_mono():
    stereo = np.stack([_sine(440), _sine(440)], axis=1)
    mono = _sine(440)
    assert compute_spectral_flatness(stereo) == pytest.approx(
        compute_spectral_flatness(mono), rel=1e-3
    )


# ── compute_spectral_fingerprint ─────────────────────────────────────────────


def test_fingerprint_same_audio_is_identical():
    audio = _sine(440)
    assert np.array_equal(
        compute_spectral_fingerprint(audio),
        compute_spectral_fingerprint(audio),
    )


def test_fingerprint_volume_change_is_below_threshold():
    audio = _sine(440)
    fp1 = compute_spectral_fingerprint(audio)
    fp2 = compute_spectral_fingerprint(audio * 0.1)
    hamming_ratio = np.sum(fp1 != fp2) / len(fp1)
    assert hamming_ratio < 0.35


def test_fingerprint_different_frequency_is_above_threshold():
    fp1 = compute_spectral_fingerprint(_sine(200))
    fp2 = compute_spectral_fingerprint(_sine(8000))
    hamming_ratio = np.sum(fp1 != fp2) / len(fp1)
    assert hamming_ratio > 0.35


def test_fingerprint_length_matches_n_bands():
    assert len(compute_spectral_fingerprint(_sine(440), n_bands=16)) == 16


def test_fingerprint_stereo_mixed_to_mono():
    mono = _sine(440)
    stereo = np.stack([mono, mono], axis=1)
    assert np.array_equal(
        compute_spectral_fingerprint(mono),
        compute_spectral_fingerprint(stereo),
    )


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


def test_detector_returns_false_when_record_raises(monkeypatch):
    import audio_capture

    class FailingRecorder:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def record(self, numframes):
            raise RuntimeError("device disconnected")

    class FailingDevice:
        def recorder(self, samplerate):
            return FailingRecorder()

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: FailingDevice())
    detector = AudioChangeDetector()
    assert detector.check() is False


def test_detector_increments_quiet_count_on_silence(monkeypatch):
    import audio_capture

    # Use a very small amplitude that is below the 0.01 quiet threshold
    amplitudes = [0.001, 0.001, 0.001]
    idx = [0]

    def mock_device():
        amp = amplitudes[min(idx[0], len(amplitudes) - 1)]
        idx[0] += 1
        return _make_mock_loopback([amp])

    monkeypatch.setattr(audio_capture, "get_loopback_device", mock_device)
    # Suppress both triggers so we can observe the count incrementing
    monkeypatch.setattr(audio_capture, "MIN_SILENCE_BEFORE_CHANGE", 999)
    monkeypatch.setattr(audio_capture, "CHANGE_THRESHOLD", 999.0)
    detector = AudioChangeDetector()
    detector.check()  # baseline at ~0 (quiet)
    detector.check()  # quiet — increments count
    assert detector._quiet_count == 1


def test_detector_signals_change_after_sustained_silence(monkeypatch):
    import audio_capture

    # Drive quiet_count to MIN_SILENCE_BEFORE_CHANGE by returning silence repeatedly
    silence = 0.0
    loud = 0.5
    amplitudes = [loud] + [silence] * 10

    idx = [0]

    def mock_device():
        amp = amplitudes[min(idx[0], len(amplitudes) - 1)]
        idx[0] += 1
        return _make_mock_loopback([amp])

    monkeypatch.setattr(audio_capture, "get_loopback_device", mock_device)
    monkeypatch.setattr(audio_capture, "MIN_SILENCE_BEFORE_CHANGE", 3)
    # Also suppress the delta threshold so only silence triggers the change
    monkeypatch.setattr(audio_capture, "CHANGE_THRESHOLD", 999.0)

    detector = AudioChangeDetector()
    detector.check()  # baseline at loud
    detector.check()  # quiet count 1
    detector.check()  # quiet count 2
    result = detector.check()  # quiet count hits 3 → change
    assert result is True


# ── get_loopback_device ───────────────────────────────────────────────────────


def test_get_loopback_device_returns_device(monkeypatch):
    import audio_capture

    class FakeSpeaker:
        name = "Fake Speakers"

    class FakeLoopback:
        pass

    class FakeSC:
        def default_speaker(self):
            return FakeSpeaker()

        def get_microphone(self, id, include_loopback):
            assert id == "Fake Speakers"
            assert include_loopback is True
            return FakeLoopback()

    fake_sc = FakeSC()
    monkeypatch.setitem(sys.modules, "soundcard", fake_sc)
    result = audio_capture.get_loopback_device()
    assert isinstance(result, FakeLoopback)


def test_get_loopback_device_returns_none_on_error(monkeypatch):
    import audio_capture

    class BrokenSC:
        def default_speaker(self):
            raise OSError("no audio device")

    monkeypatch.setitem(sys.modules, "soundcard", BrokenSC())
    result = audio_capture.get_loopback_device()
    assert result is None


# ── capture_audio ─────────────────────────────────────────────────────────────


def test_capture_audio_returns_none_when_no_device(monkeypatch):
    import audio_capture

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: None)
    assert audio_capture.capture_audio() is None


def test_capture_audio_returns_array_on_success(monkeypatch):
    import audio_capture

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: _make_mock_loopback([0.0]))
    result = audio_capture.capture_audio(seconds=0.1)
    assert result is not None
    assert isinstance(result, np.ndarray)
    np.testing.assert_array_equal(result, np.zeros(int(44100 * 0.1), dtype=np.float32))


def test_capture_audio_returns_none_on_record_error(monkeypatch):
    import audio_capture

    class FailingRecorder:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def record(self, numframes):
            raise RuntimeError("capture failed")

    class FailingDevice:
        def recorder(self, samplerate):
            return FailingRecorder()

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: FailingDevice())
    assert audio_capture.capture_audio() is None
