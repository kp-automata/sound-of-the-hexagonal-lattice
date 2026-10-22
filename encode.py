"""Encode raw BGRA frames + the wav into an mp4 with GStreamer (no ffmpeg needed).

    with Encoder("out/x.mp4", W, H, fps, audio=(start_s, dur_s)) as enc:
        enc.write(cairo_surface.get_data())

Run `python -m encode` for a 10 s smoke test (flash on every beat).
"""
import subprocess
import wave

from audio import WAV_PATH
from data import OUT, ROOT

# avenc_aac prepends one AAC frame of priming samples, and mp4mux writes an
# audio edit list starting at media time 0, so players do not skip them: the
# muxed audio plays this much later than the source. Measured by decoding
# out/smoke.mp4 and cross-correlating with the wav (lag = 1024 samples, r = 1.000).
AAC_PRIMING_SAMPLES = 1024


def slice_wav(start, duration, dst, src=WAV_PATH):
    """Copy [start, start + duration) seconds of src into dst (stdlib wave)."""
    with wave.open(str(src)) as r, wave.open(str(dst), "wb") as w:
        rate = r.getframerate()
        w.setparams(r.getparams())
        r.setpos(round(start * rate))
        w.writeframes(r.readframes(round(duration * rate)))


class Encoder:
    def __init__(self, path, width, height, fps, audio=None, quality=18, preset="medium"):
        """audio: None (full wav), (start_s, duration_s) to use a slice, or False for silent."""
        self.path = ROOT / path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.frame_bytes = width * height * 4

        audio_src = None
        if audio is None:
            audio_src = WAV_PATH
        elif audio:
            audio_src = self.path.with_suffix(".clip.wav")
            slice_wav(*audio, audio_src)
        self.audio_tmp = audio_src if audio_src != WAV_PATH else None

        cmd = [
            "gst-launch-1.0", "-q", "-e",
            "fdsrc", "fd=0", f"blocksize={self.frame_bytes}", "!",
            "rawvideoparse", f"width={width}", f"height={height}", "format=bgra",
            f"framerate={fps}/1", "!",
            "videoconvert", "!", "video/x-raw,format=I420", "!",
            "x264enc", f"speed-preset={preset}", "pass=qual",
            f"quantizer={quality}", "!",
            "h264parse", "!", "queue", "!", "mp4mux", "name=mux", "!",
            "filesink", f"location={self.path}",
        ]
        if audio_src:
            cmd += [
                "filesrc", f"location={audio_src}", "!", "wavparse", "!",
                "audioconvert", "!", "audioresample", "!",
                "avenc_aac", "bitrate=320000", "!", "queue", "!", "mux.",
            ]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, frame):
        assert len(frame) == self.frame_bytes, (len(frame), self.frame_bytes)
        self.proc.stdin.write(frame)

    def close(self):
        self.proc.stdin.close()
        code = self.proc.wait()
        if self.audio_tmp:
            self.audio_tmp.unlink(missing_ok=True)
        if code:
            raise RuntimeError(f"gst-launch-1.0 exited with {code}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def smoke_test(seconds=10, width=1280, height=720):
    import cairo

    from data import load_shells
    from timeline import Timeline

    tl = Timeline.load()
    a = load_shells()["a"]
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    assert surface.get_stride() == width * 4
    ctx = cairo.Context(surface)
    ctx.select_font_face("monospace")
    ctx.set_font_size(48)

    out = OUT.relative_to(ROOT) / "smoke.mp4"
    with Encoder(out, width, height, tl.fps, audio=(0, seconds)) as enc:
        for f in range(seconds * tl.fps):
            n, since = tl.beat_at(f)
            # flash on the onset frame, fade to a dim tint by the end of the beat
            level = 1 - 0.8 * since / 6 if n >= 0 else 0.0
            big = n >= 0 and a[n] > 0
            ctx.set_source_rgb(level * (1 if big else 0.35), level * (0.8 if big else 0.35), level * 0.35)
            ctx.paint()
            ctx.set_source_rgb(1, 1, 1)
            ctx.move_to(40, 80)
            ctx.show_text(f"frame {f:5d}   beat {n:4d}   a(n) = {a[n]}")
            surface.flush()
            enc.write(bytes(surface.get_data()))
    print(f"wrote {out}")


if __name__ == "__main__":
    smoke_test()
