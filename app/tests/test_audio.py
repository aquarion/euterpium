# tests/test_audio.py — audio_to_wav_bytes, compute_rms, AudioChangeDetector logic

import io
import sys
import wave

import numpy as np
import pytest

from audio_capture import (
    AudioChangeDetector,
    audio_to_wav_bytes,
    compute_rms,
    compute_spectral_fingerprint,
    compute_spectral_flatness,
)

SAMPLE_RATE = 44100


def _sine(freq_hz: float, duration: float = 1.0) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


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
    # Two signals with non-overlapping spectral content should produce
    # fingerprints that differ by more than the change threshold.
    # Use dense harmonic clusters at opposite ends of the spectrum.
    t = np.linspace(0, 1.0, SAMPLE_RATE, endpoint=False)
    low_freqs = [50, 80, 120, 160, 200, 250, 300, 350, 400, 500]
    high_freqs = [6000, 7000, 8000, 9000, 10000, 12000, 14000, 16000, 18000, 20000]
    low = sum(0.1 * np.sin(2 * np.pi * f * t) for f in low_freqs)
    high = sum(0.1 * np.sin(2 * np.pi * f * t) for f in high_freqs)
    fp1 = compute_spectral_fingerprint(low.astype(np.float32))
    fp2 = compute_spectral_fingerprint(high.astype(np.float32))
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
    Returns a mock loopback that yields a constant-amplitude DC buffer
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


def _make_mock_loopback_audio(audio_sequence):
    """
    Returns a mock loopback that yields pre-computed audio arrays
    for each successive call to record().
    """
    call_count = [0]

    class MockRecorder:
        def __init__(self):
            idx = min(call_count[0], len(audio_sequence) - 1)
            self._audio = audio_sequence[idx]
            call_count[0] += 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def record(self, numframes):
            audio = self._audio
            if len(audio) >= numframes:
                return audio[:numframes]
            return np.pad(audio, (0, numframes - len(audio)))

    class MockDevice:
        def recorder(self, samplerate):
            return MockRecorder()

    return MockDevice()


def test_detector_first_check_stores_fingerprint(monkeypatch):
    import audio_capture

    monkeypatch.setattr(
        audio_capture, "get_loopback_device", lambda: _make_mock_loopback_audio([_sine(440)])
    )
    detector = AudioChangeDetector()
    result = detector.check()
    # First music detection triggers a fingerprint (silence→music transition)
    assert result.changed is True
    assert detector._last_fingerprint is not None


def test_detector_no_change_on_same_spectrum(monkeypatch):
    import audio_capture

    idx = [0]
    audio = _sine(440)

    def mock_device():
        idx[0] += 1
        return _make_mock_loopback_audio([audio])

    monkeypatch.setattr(audio_capture, "get_loopback_device", mock_device)
    detector = AudioChangeDetector()
    detector.check()  # store first fingerprint
    result = detector.check()  # same spectrum
    assert result.changed is False


def test_detector_signals_change_on_different_spectrum(monkeypatch):
    import audio_capture

    t = np.linspace(0, 1.0, SAMPLE_RATE, endpoint=False)
    low_freqs = [50, 80, 120, 160, 200, 250, 300, 350, 400, 500]
    high_freqs = [6000, 7000, 8000, 9000, 10000, 12000, 14000, 16000, 18000, 20000]
    low = sum(0.1 * np.sin(2 * np.pi * f * t) for f in low_freqs).astype(np.float32)
    high = sum(0.1 * np.sin(2 * np.pi * f * t) for f in high_freqs).astype(np.float32)
    audios = [low, high]
    idx = [0]

    def mock_device():
        audio = audios[min(idx[0], len(audios) - 1)]
        idx[0] += 1
        return _make_mock_loopback_audio([audio])

    monkeypatch.setattr(audio_capture, "get_loopback_device", mock_device)
    detector = AudioChangeDetector()
    detector.check()  # store fingerprint for low-frequency cluster
    result = detector.check()  # high-frequency cluster — very different spectrum
    assert result.changed is True


def test_detector_noise_gate_blocks_acr_call(monkeypatch):
    """White noise should be classified as non-music and return changed=False."""
    import audio_capture

    rng = np.random.default_rng(0)
    noise = rng.uniform(-0.5, 0.5, SAMPLE_RATE).astype(np.float32)

    monkeypatch.setattr(
        audio_capture, "get_loopback_device", lambda: _make_mock_loopback_audio([noise])
    )
    detector = AudioChangeDetector()
    result = detector.check()
    assert result.changed is False
    assert result.flatness is not None
    assert result.flatness > 0.5


def test_detector_result_contains_metrics(monkeypatch):
    import audio_capture

    monkeypatch.setattr(
        audio_capture, "get_loopback_device", lambda: _make_mock_loopback_audio([_sine(440)])
    )
    detector = AudioChangeDetector()
    detector.check()  # first check — stores fingerprint
    result = detector.check()
    assert isinstance(result.rms, float)
    assert isinstance(result.flatness, float)
    assert isinstance(result.hamming_ratio, float)


def test_detector_result_silent_has_none_metrics(monkeypatch):
    import audio_capture

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: _make_mock_loopback([0.0]))
    detector = AudioChangeDetector()
    result = detector.check()
    assert result.changed is False
    assert result.flatness is None
    assert result.hamming_ratio is None


def test_detector_returns_false_when_no_device(monkeypatch):
    import audio_capture

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: None)
    detector = AudioChangeDetector()
    result = detector.check()
    assert result.changed is False


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
    result = detector.check()
    assert result.changed is False


def test_detector_increments_quiet_count_on_silence(monkeypatch):
    import audio_capture

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: _make_mock_loopback([0.0]))
    monkeypatch.setattr(audio_capture, "MIN_SILENCE_BEFORE_CHANGE", 999)
    detector = AudioChangeDetector()
    detector.check()
    detector.check()
    assert detector._quiet_count == 2


def test_detector_resets_fingerprint_after_sustained_silence(monkeypatch):
    """Sustained silence clears _last_fingerprint so new music is treated as fresh."""
    import audio_capture

    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    audios = [_sine(440)] + [silence] * 5

    idx = [0]

    def mock_device():
        audio = audios[min(idx[0], len(audios) - 1)]
        idx[0] += 1
        return _make_mock_loopback_audio([audio])

    monkeypatch.setattr(audio_capture, "get_loopback_device", mock_device)
    monkeypatch.setattr(audio_capture, "MIN_SILENCE_BEFORE_CHANGE", 3)

    detector = AudioChangeDetector()
    detector.check()  # store fingerprint at 440 Hz
    assert detector._last_fingerprint is not None

    for _ in range(4):  # drive quiet count to >= 3
        detector.check()

    assert detector._last_fingerprint is None  # reset on sustained silence


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
