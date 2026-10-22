"""Beat timing measured from output/lattice.wav — the sync source of truth.

The render is a continuous synth bass: loudness never drops between notes, so
onsets are found with short-window spectral flux (any change in the spectrum)
rather than an amplitude envelope. Every beat sounds, including a(n) = 0 beats,
which retrigger the lowest note.

Run `python -m audio` to measure and write out/timing.json.
The MIDI file is not used here; it is only a reference.
"""
import json
import wave

import numpy as np

from data import N, OUT, ROOT, load_shells

WAV_PATH = ROOT / "output" / "lattice.wav"
TIMING_PATH = OUT / "timing.json"

NFFT = 512  # 11.6 ms at 44.1 kHz: short enough to place attacks within ~1 ms
HOP = 64
MAX_BIN = 47  # ~4 kHz
MAX_RESIDUAL_MS = 2.0


def load_wav_mono(path=WAV_PATH):
    """Return (mono float32 in [-1, 1], sample rate). Expects 24-bit PCM."""
    with wave.open(str(path)) as w:
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    assert width == 3, f"expected 24-bit wav, got {8 * width}-bit"
    b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
    s = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
    s = np.where(s >= 1 << 23, s - (1 << 24), s)
    mono = s.reshape(-1, ch).mean(axis=1) / (1 << 23)
    return mono.astype(np.float32), rate


def _log_spec(frames):
    win = np.hanning(NFFT).astype(np.float32)
    return np.log1p(100 * np.abs(np.fft.rfft(frames * win, axis=1))[:, :MAX_BIN])


def onset_strength(x, rate):
    """Positive spectral flux on a HOP grid. Returns (strength, frame-center times)."""
    chunk = 1 << 16
    parts = []
    for start in range(0, len(x) - NFFT, chunk * HOP):
        seg = x[start:start + chunk * HOP + NFFT]
        frames = np.lib.stride_tricks.sliding_window_view(seg, NFFT)[::HOP][:chunk]
        parts.append(_log_spec(frames))
    spec = np.concatenate(parts)
    flux = np.concatenate([[0], np.maximum(np.diff(spec, axis=0), 0).sum(axis=1)])
    flux = (flux - flux.mean()) / flux.std()
    times = (np.arange(len(flux)) * HOP + NFFT / 2) / rate
    return flux, times


def fold(flux, times, beat_times, lags):
    """Mean flux at beat_times + lag, for each lag (nearest frame)."""
    dt = times[1] - times[0]
    k = np.round((beat_times[:, None] + lags[None, :] - times[0]) / dt).astype(int)
    k = k[((k >= 0) & (k < len(flux))).all(axis=1)]
    return flux[k].mean(axis=0)


LAGS = np.arange(-0.03, 0.06, 0.00025)
CHUNK = 256


def coarse_period(flux, times, n_beats):
    """(score, period) of the best uniform grid, searched over 0.110-0.160 s."""
    beats = np.arange(n_beats)
    return max((fold(flux, times, beats * p, LAGS).max(), p)
               for p in np.arange(0.110, 0.160, 0.0005))


def chunk_lags(flux, times, n_beats, period):
    """Peak lag of the folded onset strength for each CHUNK of beats. Returns (centers, lags)."""
    centers, lags = [], []
    for c in range(0, n_beats, CHUNK):
        beats = np.arange(c, min(c + CHUNK, n_beats))
        m = fold(flux, times, beats * period, LAGS)
        centers.append(beats.mean())
        lags.append(LAGS[int(np.argmax(m))])
    return np.array(centers), np.array(lags)


def detector_bias(rate, a, period, n_beats=800):
    """Lag at which the detector peaks for a synthetic render with onsets exactly on the grid."""
    t = np.arange(int((n_beats + 1) * period * rate)) / rate
    note = np.minimum((t / period).astype(int), len(a) - 1)
    f0 = 440 * 2 ** ((a[note] + 20 - 69) / 12)
    phase = 2 * np.pi * np.cumsum(f0) / rate
    tt = t - note * period
    env = np.exp(-tt / 0.08) * np.minimum(1, tt / 0.002) + 0.05
    syn = (env * sum(np.sin(k * phase) / k for k in range(1, 9))).astype(np.float32)
    flux, times = onset_strength(syn, rate)
    m = fold(flux, times, np.arange(n_beats) * period, LAGS)
    return LAGS[int(np.argmax(m))]


def measure():
    a = load_shells()["a"]
    x, rate = load_wav_mono()
    duration = len(x) / rate
    nominal = duration / N
    flux, times = onset_strength(x, rate)

    score, coarse = coarse_period(flux, times, N)
    bias = detector_bias(rate, a, nominal)

    # Onset lag per chunk on the nominal grid; a line through them gives the
    # true period (slope) and offset (intercept). Residuals = jitter.
    centers, lags = chunk_lags(flux, times, N, nominal)
    slope, intercept = np.polyfit(centers, lags, 1)
    residual = lags - (slope * centers + intercept)
    offset = intercept - bias

    # Do repeated a(n) = 0 beats (same low note again) have an audible attack?
    rep0 = np.flatnonzero((a[1:] == 0) & (a[:-1] == 0)) + 1
    rep0_peak = fold(flux, times, rep0 * nominal + intercept, np.array([0.0]))[0]

    return {
        "wav": str(WAV_PATH.relative_to(ROOT)),
        "sample_rate": rate,
        "duration": duration,
        "n_beats": N,
        "period": nominal,
        "offset": round(float(offset), 4),
        "coarse_period": round(float(coarse), 4),
        "grid_score_z": round(float(score), 2),
        "detector_bias": round(float(bias), 4),
        "drift_ms_total": round(float(slope * N * 1000), 2),
        "max_residual_ms": round(float(np.abs(residual).max() * 1000), 2),
        "repeat_a0_onset_z": round(float(rep0_peak), 2),
    }


def check(timing):
    assert abs(timing["coarse_period"] - timing["period"]) < 0.001, (
        f"best grid {timing['coarse_period']} s != duration/beats {timing['period']} s: "
        "the wav is not a uniform grid; timeline needs a per-beat onset table")
    assert abs(timing["drift_ms_total"]) <= MAX_RESIDUAL_MS, (
        f"onsets drift {timing['drift_ms_total']} ms across the file")
    assert timing["max_residual_ms"] <= MAX_RESIDUAL_MS, (
        f"chunk onsets scatter {timing['max_residual_ms']} ms around the grid")
    assert timing["grid_score_z"] > 2, "weak beat grid; onset detection unreliable"


def main():
    timing = measure()
    check(timing)
    OUT.mkdir(exist_ok=True)
    TIMING_PATH.write_text(json.dumps(timing, indent=2) + "\n")
    t = timing
    print(f"wav: {t['duration']:.3f} s, {t['sample_rate']} Hz")
    print(f"grid: period {t['period'] * 1000:.3f} ms (best coarse {t['coarse_period'] * 1000:.1f} ms, "
          f"score z={t['grid_score_z']}), offset {t['offset'] * 1000:+.2f} ms "
          f"(detector bias {t['detector_bias'] * 1000:+.2f} ms)")
    print(f"drift over file {t['drift_ms_total']:+.2f} ms, "
          f"max chunk residual {t['max_residual_ms']:.2f} ms")
    print(f"repeated a(n)=0 beats onset z={t['repeat_a0_onset_z']} "
          f"({'audible' if t['repeat_a0_onset_z'] > 1 else 'not audible'})")
    print(f"all checks passed -> {TIMING_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
