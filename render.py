"""Render stills, preview clips or the full video.

    python -m render still 0 1 7 49 91 637 4095 [--since 0] [--scale 0.5]
    python -m render clip 0 200 [--scale 0.5]
    python -m render compare 0 240        # 2x2 grid of style.VARIANTS, as a clip
    python -m render --compare still 637  # ...or as stills
    python -m render full
"""
import argparse
import multiprocessing as mp
import time
from dataclasses import replace

from data import OUT, ROOT, load_shells
from encode import Encoder
from scene import Scene, new_surface
from style import VARIANTS, Style
from timeline import Timeline

_worker = {}


class Tiled:
    """2x2 grid of Scenes, one per style.VARIANTS entry, drawn with a label each."""

    def __init__(self, style, shells, tl):
        self.st, self.tl = style, tl
        half = style.scaled(0.5)
        self.tiles = []
        for i, (label, overrides) in enumerate(VARIANTS.items()):
            scene = Scene(shells, tl, replace(half, **overrides))
            surface, ctx = new_surface(scene.st)
            pos = ((i % 2) * half.width, (i // 2) * half.height)
            self.tiles.append((label, scene, surface, ctx, pos))

    def draw(self, ctx, f):
        for label, scene, surface, sctx, (x, y) in self.tiles:
            scene.draw(sctx, f)
            surface.flush()
            ctx.set_source_surface(surface, x, y)
            ctx.paint()
            ctx.set_font_size(self.st.hud_size_px * 0.9)
            ctx.set_source_rgb(1, 1, 1)
            ctx.move_to(x + 16, y + 16 + self.st.hud_size_px)
            ctx.show_text(label)
        ctx.set_source_rgb(0.3, 0.3, 0.35)
        ctx.rectangle(self.st.width / 2 - 1, 0, 2, self.st.height)
        ctx.rectangle(0, self.st.height / 2 - 1, self.st.width, 2)
        ctx.fill()


def make_scene(scale=1.0, camera=None, compare=False):
    style = Style()
    if camera:
        style.camera = camera
    if scale != 1.0:
        style = style.scaled(scale)
    shells, tl = load_shells(), Timeline.load()
    return Tiled(style, shells, tl) if compare else Scene(shells, tl, style)


def _init(scale, camera, compare):
    scene = make_scene(scale, camera, compare)
    surface, ctx = new_surface(scene.st)
    _worker.update(scene=scene, surface=surface, ctx=ctx)


def _frame(f):
    w = _worker
    w["scene"].draw(w["ctx"], f)
    w["surface"].flush()
    return bytes(w["surface"].get_data())


def encode_frames(path, f0, f1, scale, camera, audio, workers, compare=False):
    """Render frames in batches: while one batch is written to the encoder, the
    workers render the next. At most two batches (~8 MB/frame at 1080p) are in
    memory; an unbounded imap outruns x264 and exhausts RAM on long renders."""
    st, tl = Style().scaled(scale), Timeline.load()
    batch = workers * 4
    starts = range(f0, f1, batch)
    start = time.time()
    with Encoder(path, st.width, st.height, tl.fps, audio=audio) as enc, \
            mp.Pool(workers, _init, (scale, camera, compare)) as pool:
        def submit(b):
            return pool.map_async(_frame, range(b, min(b + batch, f1)), chunksize=4)

        pending = submit(starts[0])
        for k, b in enumerate(starts):
            frames = pending.get()
            if k + 1 < len(starts):
                pending = submit(starts[k + 1])
            for frame in frames:
                enc.write(frame)
            del frames
            done = min(b + batch, f1) - f0
            el = time.time() - start
            print(f"\r  frame {f0 + done}/{f1}  {done / max(el, 1e-9):5.1f} fps", end="", flush=True)
    print(f"\nwrote {path} ({f1 - f0} frames in {time.time() - start:.1f} s)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--camera", choices=["follow", "fixed"])
    p.add_argument("--workers", type=int, default=max(mp.cpu_count() - 1, 1))
    p.add_argument("--compare", action="store_true", help="2x2 grid of style.VARIANTS")
    p.add_argument("--tag", default="", help="suffix for output filenames (keeps earlier renders)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("still")
    s.add_argument("beats", type=int, nargs="+")
    s.add_argument("--since", type=int, default=0, help="frames after the onset")
    for name in ("clip", "compare"):
        c = sub.add_parser(name)
        c.add_argument("n0", type=int)
        c.add_argument("n1", type=int)
    sub.add_parser("full")
    args = p.parse_args()
    compare = args.compare or args.cmd == "compare"
    prefix = "compare_" if compare else ""
    tag = f"_{args.tag}" if args.tag else ""

    if args.cmd == "still":
        scene = make_scene(args.scale, args.camera, compare)
        surface, ctx = new_surface(scene.st)
        (OUT / "stills").mkdir(parents=True, exist_ok=True)
        for n in args.beats:
            f = scene.tl.onset_frame(n) + args.since
            t0 = time.time()
            scene.draw(ctx, f)
            dt = time.time() - t0
            path = OUT / "stills" / f"{prefix}n{n:04d}_s{args.since}{tag}.png"
            surface.write_to_png(str(path))
            print(f"{path.relative_to(ROOT)}  (frame {f}, {dt * 1000:.0f} ms)")
    elif args.cmd in ("clip", "compare"):
        tl = Timeline.load()
        f0 = max(tl.onset_frame(args.n0) - 1, 0)
        f1 = min(tl.onset_frame(args.n1), tl.n_frames)
        path = OUT.relative_to(ROOT) / f"{prefix}{args.n0}_{args.n1}{tag}.mp4"
        encode_frames(path, f0, f1, args.scale, args.camera,
                      (f0 / tl.fps, (f1 - f0) / tl.fps), args.workers, compare)
    else:
        tl = Timeline.load()
        encode_frames(OUT.relative_to(ROOT) / f"A004016{tag}.mp4", 0, tl.n_frames,
                      args.scale, args.camera, None, args.workers)


if __name__ == "__main__":
    main()
