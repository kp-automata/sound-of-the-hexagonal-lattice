"""Every look parameter in one place. Colors are (r, g, b) in 0..1."""
from dataclasses import dataclass, field


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


# One color per a(n) value, index = data.A_VALUES.index(a(n)): cool -> hot by value.
PALETTE = [hex_rgb(h) for h in (
    "#46506a",  # 0   empty shell (used for the ring pulse only)
    "#ffffff",  # 1   origin
    "#3a86ff",  # 6
    "#00c2d1",  # 12
    "#43d17a",  # 18
    "#c8e04a",  # 24
    "#ffc93c",  # 30
    "#ff8a3c",  # 36
    "#ff3c6e",  # 48
)]


# History color by distance from the origin (0 -> center, 1 -> final radius 64).
RADIUS_RAMP = [hex_rgb(h) for h in ("#2b3f8c", "#1f8fa8", "#7fd6b0", "#f2e3a0")]


@dataclass
class Style:
    width: int = 1920
    height: int = 1080
    background: tuple = hex_rgb("#07080c")
    palette: list = field(default_factory=lambda: list(PALETTE))

    # Camera: view half-height in lattice units, V(s) = sqrt(v_min^2 + k^2 * s)
    # for beat position s. "fixed" shows the whole final disk throughout.
    camera: str = "follow"
    v_min: float = 4.0
    k: float = 1.3

    # Base lattice: every lattice point, tiny and dim.
    base_radius_px: float = 1.1
    base_color: tuple = hex_rgb("#8090b0")
    base_alpha: float = 0.18

    # History: points on shells already passed.
    # history_color: "tier" = palette color of a(m); "radius" = RADIUS_RAMP by distance.
    # history_band: passed points fade toward history_floor with distance behind the
    # ring, e-folding over this fraction of the view radius (0 = never fades).
    history_radius_px: float = 1.8
    history_alpha: float = 0.55
    history_color: str = "tier"
    history_band: float = 0.0
    history_floor: float = 0.1

    # Wavefront ring at r = sqrt(s).
    ring_width_px: float = 1.5
    ring_color: tuple = hex_rgb("#c0d0ff")
    ring_alpha: float = 0.25
    ring_pulse_alpha: float = 0.5  # extra alpha at each onset, decays with flash_tau

    # Flash on the current shell's points.
    flash_tau: float = 0.3  # seconds
    flash_tail_beats: int = 10
    flash_radius_px: float = 6.5
    glow_radius_px: float = 30.0
    glow_alpha: float = 0.85
    halo_gap_px: float = 4.0  # crisp ring around each flashing node
    halo_width_px: float = 1.5

    # Origin: a heartbeat source that pulses and emits a wave on every beat.
    origin_radius_px: float = 5.0
    origin_glow_px: float = 70.0
    origin_glow_alpha: float = 0.9
    origin_tau: float = 0.1  # seconds, pulse decay
    wave_travel: float = 0.25  # seconds for a wave to reach the current ring
    wave_width_px: float = 2.5
    wave_alpha: float = 0.45

    spokes: bool = False
    spoke_alpha: float = 0.25

    hud: bool = True
    hud_size_px: float = 26.0
    hud_color: tuple = hex_rgb("#a0a8c0")

    def scaled(self, factor):
        """Copy with the resolution and every pixel size multiplied by factor."""
        from dataclasses import replace
        px = {k: getattr(self, k) * factor for k in (
            "base_radius_px", "history_radius_px", "ring_width_px", "flash_radius_px",
            "glow_radius_px", "halo_gap_px", "halo_width_px", "origin_radius_px",
            "origin_glow_px", "wave_width_px", "hud_size_px")}
        return replace(self, width=round(self.width * factor), height=round(self.height * factor), **px)


# Named look variants for side-by-side comparison (`render.py compare`).
VARIANTS = {
    "A: a(n) colors": {},
    "B: a(n) colors + fade": {"history_band": 0.12},
    "C: radius colors": {"history_color": "radius"},
    "D: radius colors + fade": {"history_color": "radius", "history_band": 0.12},
}
