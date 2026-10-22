"""Draw one frame. Pure: frame index in, pixels out, no I/O.

Layers, back to front: base lattice, history (shells already passed), wavefront
ring at r = sqrt(s), flash + glow on recent shells, HUD.
"""
import math

import cairo
import numpy as np

from data import A_VALUES, N
from style import RADIUS_RAMP

SQRT3_2 = math.sqrt(3) / 2


class Scene:
    def __init__(self, shells, timeline, style):
        self.tl = timeline
        self.st = style
        self.a = shells["a"]
        self.offsets = shells["offsets"]
        self.pts = shells["pts_plane"]
        self.tier = shells["tier"]
        self.pt_tier = np.repeat(self.tier, self.a)

        self.r = np.sqrt((self.pts ** 2).sum(axis=1))  # ascending, since sorted by norm

        # History color: key per point into hist_colors.
        if style.history_color == "radius":
            bins = 32
            r = self.r / math.sqrt(N - 1)
            self.hist_key = np.minimum((r * bins).astype(int), bins - 1)
            ramp = np.array(RADIUS_RAMP)
            u = np.linspace(0, 1, bins) * (len(ramp) - 1)
            i = np.minimum(u.astype(int), len(ramp) - 2)
            self.hist_colors = [tuple(c) for c in ramp[i] + (ramp[i + 1] - ramp[i]) * (u - i)[:, None]]
        else:
            self.hist_key = self.pt_tier
            self.hist_colors = style.palette

    def view_radius(self, s):
        st = self.st
        if st.camera == "fixed":
            s = N
        return math.sqrt(st.v_min ** 2 + st.k ** 2 * max(s, 0.0))

    def draw(self, ctx, f):
        st, tl = self.st, self.tl
        W, H = st.width, st.height
        s = max(tl.phase(f), 0.0)
        n, _ = tl.beat_at(f)
        t = f / tl.fps

        ctx.set_source_rgb(*st.background)
        ctx.paint()

        scale = (H / 2) / self.view_radius(s)
        ctx.save()
        ctx.translate(W / 2, H / 2)
        # Screen coords of plane points; y flipped so +y is up.
        half_w, half_h = W / 2 / scale + 1, H / 2 / scale + 1

        def visible(p):
            return p[(np.abs(p[:, 0]) <= half_w) & (np.abs(p[:, 1]) <= half_h)]

        self._lattice(ctx, scale, half_w, half_h)

        self._history(ctx, n, s, scale, visible)

        # Ring, pulsing on every onset (every beat sounds, including a(n) = 0).
        pulse = 0.0
        if n >= 0:
            pulse = math.exp(-(t - tl.onset_frame(n) / tl.fps) / st.flash_tau)
        ctx.set_line_width(st.ring_width_px * (1 + pulse))
        rc = st.palette[self.tier[n]] if n >= 0 and self.a[n] else st.ring_color
        ctx.set_source_rgba(*rc, st.ring_alpha + st.ring_pulse_alpha * pulse)
        ctx.arc(0, 0, math.sqrt(s) * scale, 0, 2 * math.pi)
        ctx.stroke()

        if n >= 0:
            self._waves(ctx, n, t, scale)

        # Flash + glow on the last few shells, oldest first so the newest is on top.
        for m in range(max(n - st.flash_tail_beats + 1, 0), n + 1):
            if not self.a[m]:
                continue
            e = math.exp(-self._age(m, t) / st.flash_tau)
            pts = self.pts[self.offsets[m]:self.offsets[m + 1]] * scale
            self._flash(ctx, pts, st.palette[self.tier[m]], e)

        if n >= 0:
            self._origin(ctx, n, t)

        ctx.restore()
        if st.hud and n >= 0:
            self._hud(ctx, n)

    def _age(self, m, t):
        """Seconds since beat m's onset frame (0 exactly on that frame)."""
        return t - self.tl.onset_frame(m) / self.tl.fps

    def _beat_color(self, m):
        return self.st.palette[self.tier[m]] if self.a[m] else self.st.ring_color

    def _waves(self, ctx, n, t, scale):
        """Each beat m emits a wave from the origin that reaches shell m's radius
        after wave_travel seconds (ease-out), fading as it goes."""
        st = self.st
        span = math.ceil(st.wave_travel / self.tl.period)
        for m in range(max(n - span, 0), n + 1):
            u = self._age(m, t) / st.wave_travel
            if not 0 <= u < 1:
                continue
            r = (1 - (1 - u) ** 2) * math.sqrt(m) * scale
            ctx.set_line_width(st.wave_width_px * (1 - 0.5 * u))
            ctx.set_source_rgba(*self._beat_color(m), st.wave_alpha * (1 - u))
            ctx.new_sub_path()
            ctx.arc(0, 0, r, 0, 2 * math.pi)
            ctx.stroke()

    def _origin(self, ctx, n, t):
        """The origin as a heartbeat: a standing glow that flares on every beat."""
        st = self.st
        e = math.exp(-self._age(n, t) / st.origin_tau)
        color = self._beat_color(n)
        gr = st.origin_glow_px * (0.5 + 0.5 * e)
        g = cairo.RadialGradient(0, 0, 0, 0, 0, gr)
        g.add_color_stop_rgba(0, *color, st.origin_glow_alpha * (0.35 + 0.65 * e))
        g.add_color_stop_rgba(0.3, *color, st.origin_glow_alpha * (0.15 + 0.35 * e))
        g.add_color_stop_rgba(1, *color, 0)
        ctx.set_source(g)
        ctx.arc(0, 0, gr, 0, 2 * math.pi)
        ctx.fill()
        ctx.set_source_rgba(1, 1, 1, 0.7 + 0.3 * e)
        ctx.arc(0, 0, st.origin_radius_px * (1 + 0.6 * e), 0, 2 * math.pi)
        ctx.fill()

    def _lattice(self, ctx, scale, half_w, half_h):
        """Every lattice point as a dim dot. Row j holds (i + j/2, j*sqrt3/2) for all i,
        so each row is one dashed line of zero-length dashes with round caps: one
        stroke per row instead of one arc per point."""
        st = self.st
        ctx.save()
        ctx.set_source_rgba(*st.base_color, st.base_alpha)
        ctx.set_line_width(2 * st.base_radius_px)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_dash([0, scale])
        j_max = int(half_h / SQRT3_2) + 1
        for j in range(-j_max, j_max + 1):
            x0 = math.floor(-half_w - j / 2) + j / 2
            y = -j * SQRT3_2 * scale
            ctx.move_to(x0 * scale, y)
            ctx.line_to((half_w + 1) * scale, y)
        ctx.stroke()
        ctx.restore()

    def _history(self, ctx, n, s, scale, visible):
        """Shells m < n. Points are sorted by norm, so passed shells are a prefix."""
        st = self.st
        if n <= 0:
            return
        end = self.offsets[n]

        def batch(sel, alpha):
            pts, key = self.pts[sel], self.hist_key[sel]
            for k in np.unique(key):
                self._dots(ctx, visible(pts[key == k]) * scale, st.history_radius_px,
                           self.hist_colors[k], alpha)

        if not st.history_band:
            batch(slice(0, end), st.history_alpha)
            return

        # alpha = floor + (alpha - floor) * exp(-(ring r - point r) / w), quantized
        # into LEVELS steps; points more than 5w behind the ring sit at the floor.
        levels = 16
        w = st.history_band * self.view_radius(s)
        ring = math.sqrt(s)
        cut = int(np.searchsorted(self.r[:end], ring - 5 * w))
        batch(slice(0, cut), st.history_floor)
        idx = np.arange(cut, end)
        e = np.exp(-np.maximum(ring - self.r[idx], 0) / w)
        q = np.minimum((e * levels).astype(int), levels - 1)
        span = st.history_alpha - st.history_floor
        for lv in np.unique(q):
            batch(idx[q == lv], st.history_floor + span * (lv + 0.5) / levels)

    def _dots(self, ctx, pts, radius, color, alpha):
        if not len(pts):
            return
        ctx.set_source_rgba(*color, alpha)
        tau = 2 * math.pi
        for x, y in pts:
            ctx.move_to(x + radius, -y)
            ctx.arc(x, -y, radius, 0, tau)
        ctx.fill()

    def _flash(self, ctx, pts, color, e):
        st = self.st
        tau = 2 * math.pi
        gr = st.glow_radius_px * (0.6 + 0.4 * e)
        for x, y in pts:
            g = cairo.RadialGradient(x, -y, 0, x, -y, gr)
            g.add_color_stop_rgba(0, *color, st.glow_alpha * e)
            g.add_color_stop_rgba(1, *color, 0)
            ctx.set_source(g)
            ctx.arc(x, -y, gr, 0, tau)
            ctx.fill()
        if st.spokes:
            ctx.set_source_rgba(*color, st.spoke_alpha * e)
            ctx.set_line_width(1)
            for x, y in pts:
                ctx.move_to(0, 0)
                ctx.line_to(x, -y)
            ctx.stroke()
        core = st.history_radius_px + (st.flash_radius_px - st.history_radius_px) * e
        # Crisp halo so each node reads clearly even when glows overlap.
        ctx.set_source_rgba(*color, min(1.0, 1.2 * e))
        ctx.set_line_width(st.halo_width_px)
        for x, y in pts:
            ctx.new_sub_path()
            ctx.arc(x, -y, core + st.halo_gap_px, 0, tau)
        ctx.stroke()
        # White-hot core fading to the shell color.
        mix = tuple(c + (1 - c) * e * 0.7 for c in color)
        self._dots(ctx, pts, core, mix, min(1.0, st.history_alpha + e))

    def _hud(self, ctx, n):
        st = self.st
        ctx.select_font_face("monospace")
        ctx.set_font_size(st.hud_size_px)
        ctx.set_source_rgba(*st.hud_color, 0.9)
        pad = st.hud_size_px
        ctx.move_to(pad, st.height - pad)
        ctx.show_text(f"n = {n:4d}    a(n) = {self.a[n]:2d}    #{{x² + xy + y² = n}}")
        k = A_VALUES.index(self.a[n])
        ctx.set_source_rgb(*st.palette[k])
        ctx.rectangle(pad, st.height - pad - st.hud_size_px * 1.6, st.hud_size_px * 0.5, st.hud_size_px * 0.18)
        ctx.fill()


def new_surface(style):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, style.width, style.height)
    assert surface.get_stride() == style.width * 4
    return surface, cairo.Context(surface)
