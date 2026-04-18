# Audio Change Detection

How Euterpium decides when to send a sample to ACRCloud for fingerprinting.

## The problem

ACRCloud charges per recognition request. Sending a request every poll cycle is wasteful; sending only on true track changes is cheap. The detection layer sits between the raw audio capture and the fingerprinting API call.

## Overview

`AudioChangeDetector.check()` is called once per poll cycle (default every 10 s) when a game process is running. It captures a 1-second audio sample and runs two stages:

1. **Silence / noise gate** — suppresses requests when nothing musical is playing.
2. **Spectral fingerprint comparison** — triggers only when the music has meaningfully changed.

The method returns a `CheckResult` dataclass. When `result.changed` is `True` the caller sends a full capture to ACRCloud; otherwise it does nothing.

## Stage 1 — Silence gate

The sample's RMS energy is compared against `min_rms` (default `0.01`). If the audio is quieter than this threshold the detector increments an internal `_quiet_count`. Once `_quiet_count` reaches `min_silence_before_change` (default `2`) consecutive silent samples, `_last_fingerprint` is cleared so the next musical sample triggers recognition automatically. `changed=False` is returned.

## Stage 2 — Spectral flatness gate

Spectral flatness measures how noise-like vs. tone-like audio is:

```
flatness = geometric_mean(|FFT magnitudes|) / arithmetic_mean(|FFT magnitudes|)
```

Range is 0–1: 0 is a pure tone, 1 is white noise. Game sound effects and ambient noise sit near 1; music sits lower. If `flatness > spectral_flatness_threshold` (default `0.6`) the sample is treated as non-music and `changed=False` is returned. The flatness value is included in `CheckResult` for the UI meters.

## Stage 3 — Spectral fingerprint comparison

If the sample passes both gates it is fingerprinted:

1. Compute the FFT of the mono sample.
2. Sum squared magnitudes into `fingerprint_bands` (default `32`) logarithmically-spaced frequency bands.
3. Each band's bit is `1` if its energy exceeds the mean across all bands, `0` otherwise.
4. Compare the resulting binary vector against `_last_fingerprint` using Hamming distance.

```
hamming_ratio = number_of_differing_bits / fingerprint_bands
```

If `hamming_ratio > fingerprint_change_threshold` (default `0.35`) the track has changed — `changed=True` is returned.

If `_last_fingerprint` is `None` (first musical sample, or after a silence gap) the fingerprint is stored and `changed=True` is returned — this is the initial-detection trigger.

The current fingerprint always replaces `_last_fingerprint` after comparison so drift is tracked continuously.

## Decision flow

```
capture 1-second sample
│
├─ rms < min_rms?           → silent → changed=False
│                                       (clear fingerprint after N silent samples)
├─ flatness > threshold?    → noise  → changed=False
│
├─ no prior fingerprint?    → music, first sample → store fingerprint, changed=True
│
└─ hamming_ratio > threshold?
        yes  → track changed  → update fingerprint, changed=True
        no   → same track     → update fingerprint, changed=False
```

## CheckResult fields

| Field | Type | Meaning |
|---|---|---|
| `changed` | `bool` | True when recognition should be triggered |
| `rms` | `float` | RMS energy of the sample (0–1) |
| `flatness` | `float \| None` | Spectral flatness (0–1); `None` when silent |
| `hamming_ratio` | `float \| None` | Fraction of differing fingerprint bits; `None` when silent, noisy, or no prior fingerprint |

## Config parameters

All parameters live in `[audio]` in `euterpium.ini` and are re-read on every call so UI changes take effect immediately.

| Key | Default | Meaning |
|---|---|---|
| `min_rms` | `0.01` | RMS below this is treated as silence |
| `spectral_flatness_threshold` | `0.6` | Flatness above this is treated as noise/SFX |
| `fingerprint_bands` | `32` | Number of frequency bands in the fingerprint |
| `fingerprint_change_threshold` | `0.35` | Hamming ratio above this triggers recognition |
| `min_silence_before_change` | `2` | Consecutive silent samples before fingerprint reset |

## Debug logging

Each call emits one `DEBUG` line via the `audio_capture` logger:

```
AudioChangeDetector: rms=0.042 → silent
AudioChangeDetector: rms=0.183 flatness=0.78 [noise] → skip
AudioChangeDetector: rms=0.215 flatness=0.31 [music] no prior fingerprint → storing (trigger)
AudioChangeDetector: rms=0.198 flatness=0.29 [music] hamming=4/32 (0.125) → no change
AudioChangeDetector: rms=0.204 flatness=0.33 [music] hamming=14/32 (0.438) → CHANGE
```

## Live UI meters

`CheckResult` is emitted as a `("metrics", result)` event after every call. The main window displays an audio meters strip while a game is running showing the RMS bar, flatness value, and (when available) the Hamming ratio. When the game stops a `("game_stopped",)` event clears the strip.
