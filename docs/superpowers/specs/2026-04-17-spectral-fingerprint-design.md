# Spectral Fingerprint Music Gate

**Date:** 2026-04-17
**Branch:** feature/spectral-fingerprint
**Goal:** Avoid unnecessary ACRCloud calls by detecting whether current audio contains music, and whether that music has changed since the last check.

---

## Problem

`AudioChangeDetector` uses RMS energy delta to decide when to trigger an ACRCloud fingerprint. This misses the common case where one game music track transitions to another at the same loudness level — the energy doesn't change, so no capture is triggered and the track change goes undetected.

Secondary problem: energy changes caused by SFX or ambient noise trigger ACRCloud calls that return 1001 (no match), wasting API credits.

---

## Solution

Replace the RMS-delta change signal with a two-stage spectral analysis that runs on the same 1-second poll sample already captured by `AudioChangeDetector`:

1. **Spectral flatness gate** — is there music here at all?
2. **Spectral fingerprint comparison** — has the music changed?

No new dependencies. Pure numpy.

---

## Algorithm

### Spectral flatness gate

Spectral flatness = geometric mean of FFT magnitudes / arithmetic mean of FFT magnitudes.

- Range: 0 (pure sine tone) → 1 (white noise)
- Game music: typically 0.1–0.5
- SFX / ambient noise / silence: typically 0.5–1.0

If flatness > `SPECTRAL_FLATNESS_THRESHOLD`, classify as non-music and return False immediately — no ACRCloud call.

### Spectral fingerprint

1. Compute FFT of the 1-second sample
2. Divide the spectrum into `FINGERPRINT_BANDS` logarithmically-spaced frequency bands (log spacing matches pitch perception)
3. For each band, record whether its energy is above (1) or below (0) the mean energy across all bands
4. Result: an N-bit binary array

Compare new fingerprint to `_last_fingerprint` using Hamming distance:
- If `hamming_distance / N > FINGERPRINT_CHANGE_THRESHOLD` → signal a change (return True)
- Store the new fingerprint regardless

### Silence handling

The existing `_quiet_count` / `MIN_RMS` silence detection runs first, before flatness or fingerprinting. Silent audio resets state and returns False unchanged.

---

## Changes to `AudioChangeDetector`

**New internal state:** `_last_fingerprint: np.ndarray | None`

**New flow in `check()`:**

```
capture 1s sample
  → rms < MIN_RMS? → silent → reset state, return False
  → flatness > SPECTRAL_FLATNESS_THRESHOLD? → non-music → log, return False
  → compute fingerprint
  → no prior fingerprint? → store, return False
  → hamming > FINGERPRINT_CHANGE_THRESHOLD? → store, return True (CHANGE)
  → store, return False (no change)
```

The existing `_baseline_rms` slow-drift logic is removed. The silence floor (`is_quiet` / `_quiet_count`) is kept unchanged.

---

## Tuning Parameters

Four parameters added to `[audio]` in `euterpium.ini` and exposed via `config.py` getters. All are local variables at the top of `audio_capture.py`, loaded via config so UI settings changes take effect immediately.

| Config key | Variable | Default | Meaning |
|---|---|---|---|
| `min_rms` | `MIN_RMS` | `0.01` | Silence floor (existing `is_quiet` threshold, now named) |
| `spectral_flatness_threshold` | `SPECTRAL_FLATNESS_THRESHOLD` | `0.6` | Max flatness to count as music (0–1) |
| `fingerprint_bands` | `FINGERPRINT_BANDS` | `32` | Number of log-spaced frequency bands |
| `fingerprint_change_threshold` | `FINGERPRINT_CHANGE_THRESHOLD` | `0.35` | Fraction of differing bits that signals a track change (0–1) |

Naming is consistent with existing keys (`change_threshold`, `poll_interval`, etc.).

---

## Debug Logging

Every `check()` call logs one line at `DEBUG` level showing every metric used in the decision:

```
AudioChangeDetector: rms=0.003 → silent
AudioChangeDetector: rms=0.091 flatness=0.74 [noise] → skip
AudioChangeDetector: rms=0.142 flatness=0.31 [music] hamming=12/32 (0.375) → CHANGE
AudioChangeDetector: rms=0.138 flatness=0.29 [music] hamming=4/32 (0.125) → no change
AudioChangeDetector: rms=0.142 flatness=0.31 [music] no prior fingerprint → storing
```

---

## Testing

New file: `tests/test_audio_capture.py`

### Spectral flatness gate
- Pure sine wave → flatness below threshold → classified as music
- White noise → flatness above threshold → classified as non-music
- Near-silence → caught by RMS check before flatness is computed

### Fingerprint generation
- Same audio → identical fingerprint (Hamming distance = 0)
- Same audio with volume change → low Hamming distance (below change threshold)
- Different-spectrum audio → high Hamming distance (above change threshold)

### `AudioChangeDetector.check()` integration

Mock `get_loopback_device` to inject synthetic audio (consistent with existing test patterns):

| Scenario | Expected result |
|---|---|
| Noise audio | Returns False, no fingerprint stored |
| Silent audio | Returns False, state reset |
| First musical sample | Returns False (no prior fingerprint), fingerprint stored |
| Second musical sample, similar spectrum | Returns False |
| Second musical sample, different spectrum | Returns True |

### Config round-trip
- `config.get_spectral_flatness_threshold()`, `get_fingerprint_bands()`, `get_fingerprint_change_threshold()`, `get_min_rms()` return correct values from a test ini

---

## Files Changed

| File | Change |
|---|---|
| `app/audio_capture.py` | Add spectral fingerprint logic to `AudioChangeDetector`; add 4 config constants |
| `app/config.py` | Add 4 getters: `get_min_rms`, `get_spectral_flatness_threshold`, `get_fingerprint_bands`, `get_fingerprint_change_threshold` |
| `app/euterpium.ini` | Add new keys to `[audio]` section with defaults and comments |
| `tests/test_audio_capture.py` | New file — unit tests as described above |

No changes to `tracker.py`, `fingerprint.py`, or UI files. The `AudioChangeDetector` interface (`check()` → bool) is unchanged.
