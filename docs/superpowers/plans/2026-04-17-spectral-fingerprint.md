# Spectral Fingerprint Music Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the RMS-energy change detector with spectral flatness gating and fingerprint comparison so that same-loudness track transitions are detected and non-musical audio skips ACRCloud calls.

**Architecture:** `AudioChangeDetector.check()` gains two spectral analysis steps (flatness gate + binary fingerprint comparison) that run on the existing 1-second poll sample. It returns a `CheckResult` dataclass instead of a bare bool so the tracker can forward metrics to the UI. A thin canvas-based meters strip in the main window shows flatness and Hamming distance live.

**Tech Stack:** Python, numpy (already in use), tkinter (already in use)

---

## File Map

| File | What changes |
|---|---|
| `app/audio_capture.py` | Add `CheckResult` dataclass; add `compute_spectral_flatness`, `compute_spectral_fingerprint`; refactor `AudioChangeDetector` — new `check()` returning `CheckResult`, remove `_baseline_rms`, add `_last_fingerprint`; remove `CHANGE_THRESHOLD` import |
| `app/config.py` | Add `get_min_rms`, `get_spectral_flatness_threshold`, `get_fingerprint_bands`, `get_fingerprint_change_threshold`; remove `CHANGE_THRESHOLD` constant |
| `app/euterpium.ini` | Add 4 new keys to `[audio]` |
| `app/ui/settings_window.py` | Replace `change_threshold` Audio-tab field with 4 new fields |
| `app/tracker.py` | Unpack `result.changed`; emit `("metrics", result)` on every poll |
| `app/ui/window.py` | Add meters strip below Now Playing card; handle `("metrics", ...)` event |
| `app/tests/test_audio.py` | Update existing `AudioChangeDetector` tests; add spectral function tests |
| `app/tests/test_config.py` | Add round-trip tests for the 4 new getters |

---

## Task 1: Config — add 4 new audio getters

**Files:**
- Modify: `app/config.py`
- Modify: `app/euterpium.ini`
- Modify: `app/tests/test_config.py`

- [ ] **Step 1.1: Write failing config tests**

Add to the bottom of `app/tests/test_config.py`:

```python
# ── Spectral fingerprint config ───────────────────────────────────────────────


def test_get_min_rms_default(tmp_config):
    assert config.get_min_rms() == pytest.approx(0.01)


def test_get_spectral_flatness_threshold_default(tmp_config):
    assert config.get_spectral_flatness_threshold() == pytest.approx(0.6)


def test_get_fingerprint_bands_default(tmp_config):
    assert config.get_fingerprint_bands() == 32


def test_get_fingerprint_change_threshold_default(tmp_config):
    assert config.get_fingerprint_change_threshold() == pytest.approx(0.35)


def test_spectral_config_round_trip(tmp_config):
    config.save({
        "audio": {
            "min_rms": "0.02",
            "spectral_flatness_threshold": "0.5",
            "fingerprint_bands": "16",
            "fingerprint_change_threshold": "0.4",
        }
    })
    assert config.get_min_rms() == pytest.approx(0.02)
    assert config.get_spectral_flatness_threshold() == pytest.approx(0.5)
    assert config.get_fingerprint_bands() == 16
    assert config.get_fingerprint_change_threshold() == pytest.approx(0.4)
```

Also add `import pytest` to `test_config.py` if not already present.

- [ ] **Step 1.2: Run tests to confirm they fail**

```
cd app && poetry run pytest tests/test_config.py::test_get_min_rms_default -v
```

Expected: `FAILED — AttributeError: module 'config' has no attribute 'get_min_rms'`

- [ ] **Step 1.3: Add 4 getters to `config.py`**

In `app/config.py`, after the `get_min_silence_before_change` getter (around line 220), add:

```python
def get_min_rms() -> float:
    return _getfloat(_cfg(), "audio", "min_rms", 0.01)


def get_spectral_flatness_threshold() -> float:
    return _getfloat(_cfg(), "audio", "spectral_flatness_threshold", 0.6)


def get_fingerprint_bands() -> int:
    return _getint(_cfg(), "audio", "fingerprint_bands", 32)


def get_fingerprint_change_threshold() -> float:
    return _getfloat(_cfg(), "audio", "fingerprint_change_threshold", 0.35)
```

- [ ] **Step 1.4: Add keys to `euterpium.ini`**

In `app/euterpium.ini`, replace the `[audio]` section with:

```ini
[audio]
sample_rate           = 44100
capture_seconds       = 10
poll_interval         = 1.0
change_threshold      = 0.08
min_silence_before_change = 2
min_rms               = 0.01    ; RMS below this is treated as silence
spectral_flatness_threshold = 0.6  ; 0=pure tone, 1=noise — audio above this skips ACRCloud
fingerprint_bands     = 32         ; number of log-spaced frequency bands in the fingerprint
fingerprint_change_threshold = 0.35  ; fraction of fingerprint bits that must differ to signal a track change
```

- [ ] **Step 1.5: Run tests to confirm they pass**

```
cd app && poetry run pytest tests/test_config.py -q
```

Expected: all pass.

- [ ] **Step 1.6: Commit**

```bash
git add app/config.py app/euterpium.ini app/tests/test_config.py
git commit -m "feat: add spectral fingerprint config getters"
```

---

## Task 2: `CheckResult` dataclass + spectral helper functions

**Files:**
- Modify: `app/audio_capture.py`
- Modify: `app/tests/test_audio.py`

- [ ] **Step 2.1: Write failing tests for spectral helpers**

Add to `app/tests/test_audio.py` after the existing `compute_rms` tests and before `audio_to_wav_bytes`:

```python
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
```

Also update the existing import line at the top of `test_audio.py` from:

```python
from audio_capture import AudioChangeDetector, audio_to_wav_bytes, compute_rms
```

to:

```python
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
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```
cd app && poetry run pytest tests/test_audio.py::test_spectral_flatness_pure_tone_is_low -v
```

Expected: `FAILED — ImportError: cannot import name 'CheckResult'`

- [ ] **Step 2.3: Add `CheckResult` and spectral helpers to `audio_capture.py`**

At the top of `app/audio_capture.py`, add the `dataclasses` import:

```python
import io
import logging
import wave
from dataclasses import dataclass
```

After the `logger = logging.getLogger(__name__)` line, add:

```python
@dataclass
class CheckResult:
    """Return value of AudioChangeDetector.check()."""

    changed: bool
    rms: float
    flatness: float | None = None       # None if silent
    hamming_ratio: float | None = None  # None if silent, noisy, or no prior fingerprint
```

After `compute_rms`, add:

```python
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
    edges = np.round(
        np.logspace(0, np.log10(max(n_freqs, 2)), n_bands + 1)
    ).astype(int)
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
```

- [ ] **Step 2.4: Run new tests**

```
cd app && poetry run pytest tests/test_audio.py -k "spectral or fingerprint" -v
```

Expected: all new tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add app/audio_capture.py app/tests/test_audio.py
git commit -m "feat: add CheckResult dataclass and spectral analysis helpers"
```

---

## Task 3: Refactor `AudioChangeDetector`

**Files:**
- Modify: `app/audio_capture.py`
- Modify: `app/tests/test_audio.py`

- [ ] **Step 3.1: Update existing `AudioChangeDetector` tests**

The existing detector tests break because `check()` will return `CheckResult` instead of `bool`. Replace the entire `# ── AudioChangeDetector` section of `test_audio.py` (from the `_make_mock_loopback` helper through `test_detector_signals_change_after_sustained_silence`) with the following:

```python
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

    monkeypatch.setattr(audio_capture, "get_loopback_device", lambda: _make_mock_loopback_audio([_sine(440)]))
    detector = AudioChangeDetector()
    result = detector.check()
    assert result.changed is False
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

    audios = [_sine(200), _sine(8000)]
    idx = [0]

    def mock_device():
        audio = audios[min(idx[0], len(audios) - 1)]
        idx[0] += 1
        return _make_mock_loopback_audio([audio])

    monkeypatch.setattr(audio_capture, "get_loopback_device", mock_device)
    detector = AudioChangeDetector()
    detector.check()  # store fingerprint for 200 Hz
    result = detector.check()  # 8000 Hz — very different spectrum
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
```

- [ ] **Step 3.2: Run tests to see current failures**

```
cd app && poetry run pytest tests/test_audio.py -k "detector" -v
```

Expected: mix of failures — some from changed return type, some from removed attributes.

- [ ] **Step 3.3: Refactor `AudioChangeDetector` in `audio_capture.py`**

Replace the entire `AudioChangeDetector` class with:

```python
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
        `result.changed` is True when a track change is detected.
        All other fields carry the metrics used to reach that decision.
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

        # ── Fingerprint comparison ─────────────────────────────────────────
        fingerprint = compute_spectral_fingerprint(audio, n_bands)

        if self._last_fingerprint is None or len(self._last_fingerprint) != n_bands:
            self._last_fingerprint = fingerprint
            logger.debug(
                f"AudioChangeDetector: rms={rms:.3f} flatness={flatness:.2f}"
                f" [music] no prior fingerprint → storing"
            )
            return CheckResult(changed=False, rms=rms, flatness=flatness)

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
        return CheckResult(
            changed=False, rms=rms, flatness=flatness, hamming_ratio=hamming_ratio
        )
```

Also update the imports at the top of `audio_capture.py` — replace:

```python
from config import (
    CAPTURE_SECONDS,
    CHANGE_THRESHOLD,
    MIN_SILENCE_BEFORE_CHANGE,
    SAMPLE_RATE,
)
```

with:

```python
import config

from config import (
    CAPTURE_SECONDS,
    MIN_SILENCE_BEFORE_CHANGE,
    SAMPLE_RATE,
)
```

(The `config` module import is needed so `check()` can call `config.get_min_rms()` etc. at call time rather than at import time. `CAPTURE_SECONDS`, `MIN_SILENCE_BEFORE_CHANGE`, and `SAMPLE_RATE` are still used as module-level constants in `capture_audio` and `AudioChangeDetector`.)

- [ ] **Step 3.4: Run all audio tests**

```
cd app && poetry run pytest tests/test_audio.py -v
```

Expected: all pass. If `test_detector_noise_gate_blocks_acr_call` is flaky (white noise RNG), re-run once — it uses a seeded RNG so it should be stable.

- [ ] **Step 3.5: Remove `CHANGE_THRESHOLD` from `config.py`**

In `app/config.py`, remove the `get_change_threshold` getter and the `CHANGE_THRESHOLD` constant at the bottom. The `change_threshold` ini key remains (it just isn't read by anything after Task 4).

- [ ] **Step 3.6: Run full test suite**

```
cd app && poetry run pytest tests/ -q
```

Expected: all pass (settings_window does not have tests; tracker tests mock `detector.check()` returning a bool — check whether `test_tracker.py` needs updating).

If `test_tracker.py` patches `detector.check` to return `True`/`False`, update those patches to return `CheckResult(changed=True, rms=0.5)` / `CheckResult(changed=False, rms=0.5)`.

- [ ] **Step 3.7: Commit**

```bash
git add app/audio_capture.py app/config.py app/tests/test_audio.py
git commit -m "feat: replace RMS change detector with spectral fingerprint"
```

---

## Task 4: Update Audio settings tab

**Files:**
- Modify: `app/ui/settings_window.py`

The Audio tab currently has a `change_threshold` field that maps to the now-unused `CHANGE_THRESHOLD`. Replace it with the 4 new fingerprint config fields.

- [ ] **Step 4.1: Replace `_build_audio` in `settings_window.py`**

Replace the `_build_audio` method (lines ~483–515) with:

```python
def _build_audio(self, parent):
    self._poll_interval = tk.StringVar(value=str(config.get_poll_interval()))
    self._capture_secs = tk.StringVar(value=str(config.get_capture_seconds()))
    self._min_rms = tk.StringVar(value=str(config.get_min_rms()))
    self._min_silence = tk.StringVar(value=str(config.get_min_silence_before_change()))
    self._flatness_threshold = tk.StringVar(value=str(config.get_spectral_flatness_threshold()))
    self._fingerprint_bands = tk.StringVar(value=str(config.get_fingerprint_bands()))
    self._change_threshold = tk.StringVar(value=str(config.get_fingerprint_change_threshold()))

    fields = [
        (
            "Poll interval (seconds)",
            self._poll_interval,
            "How often to sample audio when a game is running",
        ),
        (
            "Capture length (seconds)",
            self._capture_secs,
            "Length of audio sent to ACRCloud for identification",
        ),
        (
            "Silence floor (min RMS, 0.0 – 1.0)",
            self._min_rms,
            "Audio quieter than this is treated as silence",
        ),
        (
            "Min quiet checks before silence reset",
            self._min_silence,
            "Consecutive silent samples before clearing the stored fingerprint",
        ),
        (
            "Noise gate (flatness threshold, 0.0 – 1.0)",
            self._flatness_threshold,
            "Audio above this is treated as SFX/noise and skips ACRCloud — lower = stricter",
        ),
        (
            "Fingerprint bands",
            self._fingerprint_bands,
            "Number of frequency bands in the spectral fingerprint (default: 32)",
        ),
        (
            "Track change threshold (0.0 – 1.0)",
            self._change_threshold,
            "Fraction of fingerprint bits that must differ to signal a track change",
        ),
    ]

    for label, var, hint in fields:
        _styled_label(parent, label).pack(anchor="w", pady=(10, 1))
        _styled_entry(parent, var, width=12).pack(anchor="w")
        _styled_label(parent, hint, dim=True).pack(anchor="w")
```

- [ ] **Step 4.2: Update the save handler**

In the `_save` method, replace the `"audio"` section dict (around line 692–696) with:

```python
"audio": {
    "poll_interval": str(poll),
    "capture_seconds": str(capture),
    "min_rms": self._min_rms.get().strip(),
    "min_silence_before_change": str(silence),
    "spectral_flatness_threshold": self._flatness_threshold.get().strip(),
    "fingerprint_bands": self._fingerprint_bands.get().strip(),
    "fingerprint_change_threshold": self._change_threshold.get().strip(),
},
```

Also update the validation block that parses `poll`, `capture`, `thresh`, `silence` — remove the `thresh` line and add nothing (we no longer validate it as a float at save time; the config getters handle bad values gracefully).

The relevant section in `_save` currently looks like:

```python
try:
    poll = float(self._poll_interval.get())
    capture = float(self._capture_secs.get())
    thresh = float(self._threshold.get())
    silence = int(self._min_silence.get())
except ValueError:
    messagebox.showerror(...)
    return
```

Replace with:

```python
try:
    poll = float(self._poll_interval.get())
    capture = float(self._capture_secs.get())
    silence = int(self._min_silence.get())
except ValueError:
    messagebox.showerror(
        "Invalid value",
        "Poll interval and capture length must be numbers.\n"
        "Min quiet checks must be a whole number.",
        parent=self._win,
    )
    return
```

- [ ] **Step 4.3: Run the full test suite**

```
cd app && poetry run pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 4.4: Commit**

```bash
git add app/ui/settings_window.py
git commit -m "feat: update Audio settings tab with fingerprint config fields"
```

---

## Task 5: Update `tracker.py`

**Files:**
- Modify: `app/tracker.py`
- Modify: `app/tests/test_tracker.py` (if it mocks `detector.check()`)

- [ ] **Step 5.1: Check `test_tracker.py` for `detector.check` mocks**

```
cd app && grep -n "check" tests/test_tracker.py
```

Any mock that patches `detector.check` to return `True` or `False` must be updated to return `CheckResult(changed=True/False, rms=0.5)`. Update those tests now.

For example, if a test does:

```python
monkeypatch.setattr(detector, "check", lambda: True)
```

Change it to:

```python
from audio_capture import CheckResult
monkeypatch.setattr(detector, "check", lambda: CheckResult(changed=True, rms=0.5))
```

- [ ] **Step 5.2: Run existing tracker tests to establish baseline**

```
cd app && poetry run pytest tests/test_tracker.py -v
```

Note any failures before making changes.

- [ ] **Step 5.3: Update `tracker.py` — unpack `CheckResult` and emit metrics**

In `app/tracker.py`, in `_run`, replace:

```python
changed = detector.check()
if changed:
```

with:

```python
result = detector.check()
self._emit("metrics", result)
if result.changed:
```

Also add the import at the top of tracker.py (it already imports from audio_capture — add `CheckResult` to be explicit, though it is only needed for type annotations):

```python
from audio_capture import AudioChangeDetector, CheckResult, audio_to_wav_bytes, capture_audio
```

- [ ] **Step 5.4: Run tracker tests**

```
cd app && poetry run pytest tests/test_tracker.py -v
```

Expected: all pass.

- [ ] **Step 5.5: Run full test suite**

```
cd app && poetry run pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 5.6: Commit**

```bash
git add app/tracker.py app/tests/test_tracker.py
git commit -m "feat: forward CheckResult metrics from tracker to UI queue"
```

---

## Task 6: Live metrics UI

**Files:**
- Modify: `app/ui/window.py`

No unit tests — manual smoke test described at the end.

- [ ] **Step 6.1: Add meter constants and imports to `window.py`**

At the top of `window.py`, after the colour constants, add:

```python
METER_H = 10  # canvas height in pixels
```

And add `import config` after the existing `import tkinter as tk` block:

```python
import config
from audio_capture import CheckResult
```

- [ ] **Step 6.2: Add `_build_meters` method**

Add this method to `MainWindow`, after `_build_ui`:

```python
def _build_meters(self, after_widget):
    """Build the spectral metrics strip (flatness + hamming distance gauges)."""
    self._meters_frame = tk.Frame(self._root, bg=BG_CARD, padx=20, pady=6)

    tk.Label(
        self._meters_frame,
        text="AUDIO ANALYSIS",
        font=("Segoe UI", 7, "bold"),
        bg=BG_CARD,
        fg=TEXT_DIM,
    ).pack(anchor="w")

    # Flatness row
    flat_row = tk.Frame(self._meters_frame, bg=BG_CARD)
    flat_row.pack(fill="x", pady=(3, 0))
    tk.Label(
        flat_row, text="Music", font=("Segoe UI", 8), bg=BG_CARD, fg=TEXT_DIM, width=5, anchor="e"
    ).pack(side="left")
    self._flatness_canvas = tk.Canvas(
        flat_row, height=METER_H, bg=BG, highlightthickness=0
    )
    self._flatness_canvas.pack(side="left", fill="x", expand=True, padx=(4, 4))
    tk.Label(
        flat_row, text="Noise", font=("Segoe UI", 8), bg=BG_CARD, fg=TEXT_DIM, width=5, anchor="w"
    ).pack(side="left")

    # Change row
    change_row = tk.Frame(self._meters_frame, bg=BG_CARD)
    change_row.pack(fill="x", pady=(3, 0))
    tk.Label(
        change_row, text="Same", font=("Segoe UI", 8), bg=BG_CARD, fg=TEXT_DIM, width=5, anchor="e"
    ).pack(side="left")
    self._hamming_canvas = tk.Canvas(
        change_row, height=METER_H, bg=BG, highlightthickness=0
    )
    self._hamming_canvas.pack(side="left", fill="x", expand=True, padx=(4, 4))
    tk.Label(
        change_row, text="Diff", font=("Segoe UI", 8), bg=BG_CARD, fg=TEXT_DIM, width=5, anchor="w"
    ).pack(side="left")

    self._flatness_canvas.bind("<Configure>", lambda e: self._redraw_meters())
    self._hamming_canvas.bind("<Configure>", lambda e: self._redraw_meters())

    self._last_metrics: CheckResult | None = None
    # Pack after the Now Playing card
    self._meters_frame.pack(fill="x", padx=16, pady=(0, 4))
```

- [ ] **Step 6.3: Add `_update_meters` and `_redraw_meters` methods**

```python
def _update_meters(self, result: "CheckResult"):
    """Receive a CheckResult from the tracker and update both gauges."""
    self._last_metrics = result
    self._redraw_meters()

def _redraw_meters(self):
    if self._last_metrics is None:
        return
    result = self._last_metrics
    flatness_threshold = config.get_spectral_flatness_threshold()
    change_threshold = config.get_fingerprint_change_threshold()
    n_bands = config.get_fingerprint_bands()

    for canvas in (self._flatness_canvas, self._hamming_canvas):
        canvas.delete("all")

    w_flat = self._flatness_canvas.winfo_width()
    w_ham = self._hamming_canvas.winfo_width()
    h = METER_H

    if w_flat <= 1:
        return

    # ── Flatness bar ───────────────────────────────────────────────────────
    if result.flatness is None:
        # Silent — dim bar
        self._flatness_canvas.create_rectangle(0, 0, w_flat, h, fill=TEXT_DIM, outline="")
    else:
        fill_w = max(1, int(w_flat * result.flatness))
        color = TEXT_GREEN if result.flatness <= flatness_threshold else TEXT_RED
        self._flatness_canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline="")
        tick_x = int(w_flat * flatness_threshold)
        self._flatness_canvas.create_line(tick_x, 0, tick_x, h, fill=TEXT_MAIN, width=1)

    # ── Hamming / change bar ───────────────────────────────────────────────
    if w_ham <= 1:
        return

    if result.hamming_ratio is None:
        self._hamming_canvas.create_rectangle(0, 0, w_ham, h, fill=TEXT_DIM, outline="")
    else:
        fill_w = max(1, int(w_ham * result.hamming_ratio))
        color = TEXT_GREEN if result.hamming_ratio <= change_threshold else TEXT_RED
        self._hamming_canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline="")
        tick_x = int(w_ham * change_threshold)
        self._hamming_canvas.create_line(tick_x, 0, tick_x, h, fill=TEXT_MAIN, width=1)
```

- [ ] **Step 6.4: Wire `_build_meters` into `_build_ui`**

In `_build_ui`, after the Now Playing card block (after `self._lbl_delivery.pack(...)`), add:

```python
self._build_meters(after_widget=card)
```

- [ ] **Step 6.5: Wire `_update_meters` into `_handle_message`**

In `_handle_message`, add a new `elif` branch:

```python
elif kind == "metrics":
    _, result = msg
    self._update_meters(result)
```

- [ ] **Step 6.6: Update `update_track` public API for thread-safety**

The `_update_meters` method is already called via the queue (from `_handle_message`), so it runs in the tkinter thread — no additional threading changes needed.

- [ ] **Step 6.7: Run the full test suite**

```
cd app && poetry run pytest tests/ -q
```

Expected: all pass (the window has no unit tests).

- [ ] **Step 6.8: Smoke test — start the app with a game running**

Run the app normally. With a game running:
- The AUDIO ANALYSIS strip should appear below the Now Playing card
- The flatness bar should sit in the green zone during music playback
- The flatness bar should spike red during loud SFX or silence between tracks
- When a track changes, the Hamming bar should spike red briefly, then settle back green

- [ ] **Step 6.9: Commit**

```bash
git add app/ui/window.py
git commit -m "feat: add live spectral metrics strip to main window"
```

---

## Final: verify and open PR

- [ ] **Run full test suite one last time**

```
cd app && poetry run pytest tests/ -q
```

Expected: all pass, no warnings.

- [ ] **Open PR**

```bash
git push -u origin feature/spectral-fingerprint
gh pr create --title "feat: spectral fingerprint music gate" --body "$(cat <<'EOF'
## Summary
- Replaces RMS-delta change detection with spectral flatness gating + binary fingerprint comparison
- Detects track changes at constant loudness (fixes common miss when one track transitions to another)
- Skips ACRCloud when audio is classified as noise/SFX (saves API credits)
- `AudioChangeDetector.check()` returns `CheckResult` dataclass with rms/flatness/hamming_ratio metrics
- Adds a live AUDIO ANALYSIS meters strip to the main window (flatness + change gauges with threshold markers)
- 4 new tunable config keys in `[audio]`: `min_rms`, `spectral_flatness_threshold`, `fingerprint_bands`, `fingerprint_change_threshold`
- All exposed in the Audio settings tab

## Test plan
- [ ] `poetry run pytest tests/ -q` — all pass
- [ ] Start app with a game running — AUDIO ANALYSIS strip visible, flatness bar green during music
- [ ] Track change — Hamming bar spikes red briefly then returns green
- [ ] SFX / loading screen — flatness bar turns red, ACRCloud not called
- [ ] Settings → Audio tab shows 7 fields including the 4 new fingerprint fields; save round-trips correctly

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
