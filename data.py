"""Shells of the hexagonal lattice for OEIS A004016.

a(n) = #{(x, y) in Z^2 : x^2 + xy + y^2 = n}. Lattice point (x, y) maps to the
plane point (x + y/2, y*sqrt(3)/2), whose squared length is exactly n.

Run `python -m data` to validate and write out/shells.npz.
"""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
SHELLS_PATH = OUT / "shells.npz"

N = 4096
R = 74  # max |x| with x^2+xy+y^2 < N is sqrt(4(N-1)/3) ~ 73.9
A_VALUES = (0, 1, 6, 12, 18, 24, 30, 36, 48)  # every a(n) value for n < N
OEIS_PREFIX = [1, 6, 0, 6, 6, 0, 0, 12, 0, 6, 0, 0, 6, 12, 0, 0, 6, 0, 0, 12]


def compute_shells():
    """Return dict of arrays: a, offsets, pts_xy, pts_plane, tier.

    Shell n is pts_*[offsets[n]:offsets[n + 1]], points ordered by angle.
    """
    r = np.arange(-R, R + 1)
    x, y = np.meshgrid(r, r, indexing="ij")
    x, y = x.ravel(), y.ravel()
    norm = x * x + x * y + y * y
    keep = norm < N
    x, y, norm = x[keep], y[keep], norm[keep]

    px = x + y / 2
    py = y * np.sqrt(3) / 2
    order = np.lexsort((np.arctan2(py, px), norm))
    x, y, norm, px, py = x[order], y[order], norm[order], px[order], py[order]

    a = np.bincount(norm, minlength=N)
    return {
        "a": a,
        "offsets": np.concatenate([[0], np.cumsum(a)]),
        "pts_xy": np.stack([x, y], axis=1),
        "pts_plane": np.stack([px, py], axis=1),
        "tier": np.searchsorted(A_VALUES, a),
    }


def save_shells(shells):
    OUT.mkdir(exist_ok=True)
    np.savez(SHELLS_PATH, **shells)


def load_shells():
    if not SHELLS_PATH.exists():
        save_shells(compute_shells())
    with np.load(SHELLS_PATH) as f:
        return {k: f[k] for k in f.files}


def check(shells):
    a, offsets, xy = shells["a"], shells["offsets"], shells["pts_xy"]

    assert list(a[:20]) == OEIS_PREFIX, f"prefix mismatch: {list(a[:20])}"
    assert a.sum() == 14839, a.sum()
    assert set(np.unique(a)) == set(A_VALUES), np.unique(a)
    assert (np.array(A_VALUES)[shells["tier"]] == a).all()

    # Every shell is invariant under 60-degree rotation (x, y) -> (-y, x + y).
    for n in np.flatnonzero(a):
        pts = xy[offsets[n]:offsets[n + 1]]
        rot = np.stack([-pts[:, 1], pts[:, 0] + pts[:, 1]], axis=1)
        assert set(map(tuple, pts)) == set(map(tuple, rot)), f"shell {n} not 6-fold"

    # Plane radius^2 equals the norm.
    r2 = (shells["pts_plane"] ** 2).sum(axis=1)
    norms = np.repeat(np.arange(N), a)
    assert np.allclose(r2, norms), "plane coords do not match norm"


def main():
    shells = compute_shells()
    check(shells)
    save_shells(shells)
    a = shells["a"]
    print(f"a(0..19) = {a[:20].tolist()}")
    print(f"points = {a.sum()}, non-empty shells = {np.count_nonzero(a)}")
    print(f"all checks passed -> {SHELLS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
