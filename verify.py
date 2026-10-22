"""Check a rendered mp4: frame count/rate, and audio alignment against the wav.

Frames are a pure function of their index, so sync reduces to: the video has
exactly the expected frames, and the muxed audio sits at a constant, known lag
(AAC priming, which Timeline already compensates) from start to end.

    python -m verify [out/A004016.mp4]
"""
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from audio import load_wav_mono
from data import ROOT
from encode import AAC_PRIMING_SAMPLES
from timeline import Timeline


def count_video_frames(path):
    out = subprocess.run(
        ["gst-launch-1.0", "-q", "filesrc", f"location={path}", "!", "qtdemux", "!",
         "h264parse", "!", "avdec_h264", "!", "videoconvert", "!", "videoscale", "!",
         "video/x-raw,format=GRAY8,width=16,height=16", "!", "fdsink", "fd=1"],
        capture_output=True, check=True).stdout
    return len(out) // 256


def decode_audio(path, dst):
    subprocess.run(
        ["gst-launch-1.0", "-q", "filesrc", f"location={path}", "!", "qtdemux", "!",
         "aacparse", "!", "avdec_aac", "!", "audioconvert", "!",
         "audio/x-raw,format=S16LE,channels=1", "!", "wavenc", "!", "filesink", f"location={dst}"],
        check=True)
    with wave.open(str(dst)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def lag_at(ref, dec, t, rate, span=2.0, search=3000):
    a, b = int(t * rate), int((t + span) * rate)
    seg = ref[a:b]
    scores = [np.dot(seg, dec[a + L:b + L]) for L in range(-search, search)]
    return int(np.argmax(scores)) - search


def main():
    path = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "out/A004016.mp4")
    tl = Timeline.load()
    ok = True

    frames = count_video_frames(path)
    print(f"video frames: {frames} (expected {tl.n_frames})")
    if frames != tl.n_frames:
        sys.exit("not a full render (frame count differs); verify only checks full renders")

    ref, rate = load_wav_mono()
    with tempfile.TemporaryDirectory() as tmp:
        dec = decode_audio(path, Path(tmp) / "dec.wav")
    print(f"audio: {len(dec) / rate:.3f} s decoded, source {len(ref) / rate:.3f} s")
    for t in (1.0, tl.duration / 2, tl.duration - 4.0):
        lag = lag_at(ref, dec, t, rate)
        good = lag == AAC_PRIMING_SAMPLES
        ok &= good
        print(f"  lag at {t:6.1f} s: {lag} samples ({lag / rate * 1000:+.2f} ms) "
              f"{'ok' if good else f'!= {AAC_PRIMING_SAMPLES}'}")

    print("all checks passed" if ok else "CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
