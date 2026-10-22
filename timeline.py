"""Frame <-> beat mapping, driven by out/timing.json (measured from the wav).

Beat n is heard in the mp4 at onset(n) = offset + av_delay + n * period, where
offset is the attack time measured in the wav and av_delay is the audio delay
the encoder adds (AAC priming). It is shown on the frame nearest that onset,
so with FPS = 48 and period = 0.125 every beat starts exactly 6 frames after
the previous one.
"""
import json
from dataclasses import dataclass

from audio import TIMING_PATH
from encode import AAC_PRIMING_SAMPLES

FPS = 48


@dataclass(frozen=True)
class Timeline:
    period: float
    offset: float
    av_delay: float
    n_beats: int
    duration: float
    fps: int = FPS

    @classmethod
    def load(cls, fps=FPS):
        t = json.loads(TIMING_PATH.read_text())
        av_delay = AAC_PRIMING_SAMPLES / t["sample_rate"]
        return cls(t["period"], t["offset"], av_delay, t["n_beats"], t["duration"], fps)

    @property
    def n_frames(self):
        return round(self.duration * self.fps)

    def onset_time(self, n):
        return self.offset + self.av_delay + n * self.period

    def onset_frame(self, n):
        return round(self.onset_time(n) * self.fps)

    def beat_at(self, f):
        """(n, frames since beat n's onset frame) for frame f; n = -1 before the first beat."""
        n = int((f / self.fps - self.offset - self.av_delay) / self.period)
        n = max(-1, min(n, self.n_beats - 1))
        while n >= 0 and self.onset_frame(n) > f:
            n -= 1
        while n + 1 < self.n_beats and self.onset_frame(n + 1) <= f:
            n += 1
        return n, f - self.onset_frame(n) if n >= 0 else f

    def phase(self, f):
        """Continuous beat position at frame f (e.g. 12.5 = halfway through beat 12)."""
        return (f / self.fps - self.offset - self.av_delay) / self.period
