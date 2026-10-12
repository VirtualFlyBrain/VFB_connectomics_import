"""Bringing a neuron's OBJ to a displayable size: which published rung, or decimate.

`docs/MESH_SIZING.md` is the argument; this is the arithmetic. Nothing here fetches,
writes or transforms — it takes a surface area and a face count and says what to serve —
so the policy can be read and tested without a bucket, a template or a transform.

The policy
----------
**Serve the finest rung the publisher ships that fits the wire budget. Reprocess only when
nothing they ship fits.**

That is deliberately not quality-optimal: at equal face count our own quadric decimation is
measurably *better* than maleCNS's lod2 (mean error 20.7 vs 33.3 nm against lod0). We serve
their rung anyway, because the objective is responsibility rather than quality — we serve
their geometry unaltered and own only the choice of which one. Anyone re-deriving the
quality argument will conclude this is a mistake; it is a different objective. See
`docs/MESH_SIZING.md`, "the method test".

Predict to choose, measure to serve
-----------------------------------
Rung density varies ~±50% neuron to neuron, so a predicted size is never safe. `plan()`
picks a starting rung from the ladder's calibration; the caller then fetches it and calls
`judge()` on the **actual** face count, stepping down while the answer is not ACCEPT. We
fetch the mesh regardless, so the exact count is free before anything is written.

This fired on the first ten-neuron prototype: DNp01(GF)_R brain, 10,653 um2, predicted
18.79 MB at lod1 — a fit — and arrived at 2,610,604 faces = 23.50 MB, because the giant
fibre runs at 245 f/um2. A predict-only rule ships that file and never knows.

Both limits are enforced on the measurement
-------------------------------------------
There are two, and they fail differently:

* the **budget** is the wire cost, and busting it is a slow page;
* the **ceiling** is a density above which nothing displays better, and busting it is bytes
  spent on detail no viewer resolves.

An earlier version checked the ceiling against the ladder *constant* and never rechecked
it, which is the same mistake the budget rule exists to prevent. Measured on the panel of
2026-10-02, DNp01(GF)_R's VNC half came back at **370 f/um2** and shipped. `judge()` now
applies both to the count that actually arrived.

Datasets with no ladder
-----------------------
BANC publishes LOD 0 only, so there is nothing to choose between and `decimate_target()` is
the whole policy for it. That target is **two-sided**: the density target for typical
neurons, the budget cap for the tail. The cap is what was missing — `budget_mb` used to be
a skip threshold with an uncapped density target behind it, so a 60,000 um2 neuron
decimated to ~6 M faces (~50 MB) and the function reported success.
"""
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

__all__ = ['Ladder', 'Budget', 'Plan', 'ACCEPT', 'OVER_BUDGET', 'OVER_CEILING',
           'plan', 'judge', 'decimate_target', 'estimate_mb']

#: `judge()` outcomes. Only ACCEPT may be written.
ACCEPT, OVER_BUDGET, OVER_CEILING = 'accept', 'over_budget', 'over_ceiling'


@dataclass(frozen=True)
class Ladder:
    """A publisher's LOD ladder, calibrated once per dataset.

    `density` maps lod number -> faces per um2 **in template space**. Template space is
    load-bearing: maleCNS's source-space area is 1.78x its template-space area, so a
    source-space f/um2 compares to nothing in `docs/ISSUES.md` and makes every density look
    1.8x too small.

    One constant per rung is only legitimate because it was checked: over 100 neurons the
    lod2 density spread is 1.44x p5-p95 with no drift against size (r(log area, density) =
    -0.33). A dataset whose rungs are less coherent than that should decimate instead,
    which targets density directly. `calibrated_from` records how the numbers were got,
    because that is the expensive part to reconstruct.
    """
    density: Mapping[int, float]
    calibrated_from: str
    #: `num_lods` is per-segment in the neuroglancer manifest, so a dataset where small
    #: cells get fewer rungs is entirely plausible. Callers that can read the manifest
    #: should pass what it says to `plan(served=...)` rather than trusting this.
    expected_lods: Optional[int] = None

    def __post_init__(self):
        if not self.density:
            raise ValueError('a Ladder needs at least one rung')
        if any(d <= 0 for d in self.density.values()):
            raise ValueError(f'non-positive rung density in {dict(self.density)}')

    @property
    def rungs(self) -> Tuple[int, ...]:
        """Rung numbers finest first. Finer = lower lod = higher density."""
        return tuple(sorted(self.density))


@dataclass(frozen=True)
class Budget:
    """What a served OBJ is allowed to cost, and the density above which it is waste.

    `bytes_per_face` converts a face count to a wire size. 9.0 is the measured gzipped
    cost of our 3 dp OBJ (7.6-8.7 across every mesh in `docs/MESH_SIZING.md`; rounded up,
    so it errs toward the coarser rung).

    **Caveat, measured 2026-10-02:** www.virtualflybrain.org returns `volume_man.obj` as
    `application/octet-stream` with no `Content-Encoding`, even when gzip and br are
    offered — so the real wire cost today is the RAW size, ~35.2 bytes/face, not 9.0.
    Rebasing is a decision rather than a bug fix: 20 MB at 9 B/face caps a 60,000 um2
    neuron at exactly hemibrain's 37 f/um2, and that coincidence is what justifies the
    number. At 35.2 B/face the same cap lands at 9.5 f/um2, which is four times coarser
    than anything VFB serves. So the budget stays on the gzipped basis and the server
    should be taught to compress; `estimate_mb(..., bytes_per_face=RAW_BYTES_PER_FACE)`
    reports what is actually being sent in the meantime.

    `skip_mb` is a "don't bother" threshold, never a limit — the distinction that the
    single `MESH_BUDGET_MB` constant used to blur.
    """
    max_mb: float = 20.0
    ceiling_f_per_um2: float = 200.0
    bytes_per_face: float = 9.0
    skip_mb: float = 4.0

    #: measured on the 3 dp OBJs this pipeline writes; see the class docstring.
    RAW_BYTES_PER_FACE = 35.2

    @property
    def max_faces(self) -> int:
        """Face count at which `max_mb` is reached."""
        return int(self.max_mb * 1e6 / self.bytes_per_face)


@dataclass(frozen=True)
class Plan:
    """One rung's predicted cost, as `plan()` reports it."""
    lod: int
    faces: int
    mb: float
    fits: bool


def estimate_mb(faces: int, budget: Budget, bytes_per_face: Optional[float] = None) -> float:
    """Wire size of `faces` faces, in MB. `bytes_per_face` overrides the budget's basis."""
    return faces * (budget.bytes_per_face if bytes_per_face is None
                    else bytes_per_face) / 1e6


def admissible(ladder: Ladder, budget: Budget,
               served: Optional[Sequence[int]] = None) -> Tuple[int, ...]:
    """Rungs worth considering, finest first.

    A rung whose calibrated density is above the ceiling is dropped outright — nothing
    displays better above it, so it can only ever cost bytes. For maleCNS that removes
    lod0 (1292 f/um2) and nothing else.
    """
    pool = ladder.rungs if served is None else tuple(
        r for r in ladder.rungs if r in set(served))
    return tuple(r for r in pool if ladder.density[r] <= budget.ceiling_f_per_um2)


def plan(area_um2: float, ladder: Ladder, budget: Budget,
         served: Optional[Sequence[int]] = None) -> Tuple[Tuple[Plan, ...], Optional[int]]:
    """`(predictions, first rung to try)` for a region of this surface area.

    The second element is the finest rung *predicted* to fit, or — when none does — the
    finest admissible one, so the caller always has somewhere to start and the measurement
    decides from there. `None` means the ladder offers nothing under the ceiling, which is
    a dataset-configuration error rather than a per-neuron outcome.
    """
    rungs = admissible(ladder, budget, served)
    if not rungs:
        return (), None
    preds = tuple(
        Plan(lod=r,
             faces=int(area_um2 * ladder.density[r]),
             mb=round(estimate_mb(int(area_um2 * ladder.density[r]), budget), 2),
             fits=estimate_mb(int(area_um2 * ladder.density[r]), budget) <= budget.max_mb)
        for r in rungs)
    fitting = [p.lod for p in preds if p.fits]
    return preds, (min(fitting) if fitting else min(rungs))


def judge(faces: int, area_um2: float, budget: Budget) -> str:
    """ACCEPT, OVER_BUDGET or OVER_CEILING for a mesh that has actually been fetched.

    Both limits are applied to the measurement, never to the prediction. Budget is reported
    first when both are busted: it is the one that decides what gets written either way,
    and reporting a single reason keeps the log line readable.
    """
    if estimate_mb(faces, budget) > budget.max_mb:
        return OVER_BUDGET
    if area_um2 > 0 and faces / area_um2 > budget.ceiling_f_per_um2:
        return OVER_CEILING
    return ACCEPT


def next_rung(lod: int, ladder: Ladder, budget: Budget,
              served: Optional[Sequence[int]] = None) -> Optional[int]:
    """The next coarser admissible rung after `lod`, or None if `lod` is the coarsest."""
    rungs = admissible(ladder, budget, served)
    coarser = [r for r in rungs if r > lod]
    return min(coarser) if coarser else None


def decimate_target(n_faces: int, area_um2: float, density: float,
                    budget: Budget) -> Optional[int]:
    """Faces to decimate to, or None to leave the mesh alone.

    The target is **two-sided**: density binds for a typical neuron, the budget cap binds
    for the tail. Before this was two-sided, `budget_mb` was consulted only as a skip
    threshold and `density * area` ran uncapped, so a large neuron could decimate to ~50 MB
    and be reported as a success; worse, a mesh already *below* the density target was
    returned untouched however large it was. Both escapes are closed by taking the minimum
    and then comparing against the count we actually have.

    A check on the numbers, which is why 20 MB is the number: at 9 bytes/face the cap is
    2.22 M faces, so a 60,000 um2 neuron lands at 37 f/um2 — exactly hemibrain's measured
    "displays fine" density. The cap and the quality floor meet where `docs/ISSUES.md`
    IMG-1 said they should.
    """
    if n_faces < 1000:
        return None                                  # too small for decimation to mean much
    if density and density > 0:
        target = min(int(density * area_um2), budget.max_faces)
    else:
        target = budget.max_faces                    # density disabled: budget still binds
    if target >= n_faces:
        return None                                  # already at or below both limits
    if estimate_mb(n_faces, budget) <= budget.skip_mb:
        # Small enough that reducing it buys nothing. Checked AFTER the target, so a mesh
        # over the budget is never skipped for being "small" — skip_mb < max_mb always.
        return None
    return max(target, 1)
