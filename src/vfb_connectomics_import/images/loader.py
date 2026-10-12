#!/usr/bin/env python
"""Write EM neuron images (SWC + OBJ + NRRD) onto the VFB templates.

Replaces the ad-hoc per-dataset loaders that lived only inside Jenkins jobs. Same output
contract — `volume.swc`, `volume_man.obj`, `volume.nrrd` written into the KB-supplied
folder — but version-controlled, and driven by a declared dataset rather than by constants
in this file.

`--connectome banc|malecns` selects everything that differs between datasets. None of it
lives here: identity, cut planes and transform chains are in
[`connectomes.py`](connectomes.py), geometry fetching in [`sources.py`](sources.py), chain
resolution in [`chain.py`](chain.py) and the mesh-size policy in [`sizing.py`](sizing.py).
This module owns orchestration and the deletion policy, and nothing else.

The filesystem contract (what is written, swapped and deleted) lives in
[`io.py`](io.py). It is separate because it is the part that can
destroy a served image, and it needs no network or transform, so it can be read closely and
tested outright. This module owns fetching, geometry, transforms and orchestration.

Usage
-----
    export IMAGE_FIELD_DIR=/local/transform_fields          # required, see docs/TRANSFORMS.md
    export KB_USER=... KB_PASSWORD=...
    vfb-em-images --connectome malecns --region both --workers 8 --ledger run.jsonl
    # or, uninstalled: PYTHONPATH=src python -m vfb_connectomics_import.images.loader

    # Jenkins/SLURM array: split the work list N ways, one ledger per task
    vfb-em-images --connectome banc --region brain --shard $I --of $N --ledger shard-$I.jsonl

    # stage skeletons in bulk first (strongly recommended, see --skeleton-dir)
    gsutil -m rsync -r \
      gs://lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/banc_banc_space_swc \
      /local/banc_swc

Replace in place, one neuron at a time (`--mode replace`, the default)
---------------------------------------------------------------------
Almost every neuron in both current datasets **already has** an image. This job replaces
them, and it
is emphatically *not* wipe-everything-then-rebuild: at no point is any neuron left without
an image. Per neuron the complete new set is built to `volume.partial.*`, then swapped in
with `os.replace` — atomic and overwriting, so a served file goes straight from old to new
and is never briefly absent. On any failure the partials are discarded and the old image
keeps serving, and the neuron is retried next run. So the job can be stopped at any moment
and the site is never in a broken state, which is what makes its speed unimportant.

`--mode fill` is the other case: only write where a product is missing (IMG-4's no-image
share), leaving existing images alone.

Deliberate deletions
--------------------
There are exactly two, both in `decide()`:

* The rebuild finds **no material in this region** (or too little to depict) *and* a usable
  source was available. That is a positive finding, not a failure: the image sitting there
  is spurious and is removed. This is the only thing that cleans up the ~4,660
  wrong-template BANC images of docs/ISSUES.md IMG-3. `--no-delete-spurious` disables it.
* Files left over from the previous alignment are swept *after* a successful swap:
  `volume.obj`, `volume.dps.pkl`, and any product no longer in `--products`. The dps is a
  navis Dotprops pickle feeding NBLAST, and must go — NBLAST only re-adds a neuron to its
  combined cache when the per-folder dps has *changed*, so a stale one keeps the old shape
  in that cache indefinitely. `volume.wlz` and `thumbnail*` are deliberately left.

If there was **no usable source at all**, nothing is deleted. Upstream mesh coverage is
only 94.4%/68.8%, so absent input must never destroy a good image.

Resuming after a stop
---------------------
**`--ledger FILE` is required for a meaningful resume in replace mode.** File existence
cannot indicate progress: nearly every neuron already has files, so there is nothing to
test. Order of operations is **sort -> shard -> roots -> ledger -> limit**, so
`--shard i --of n` always owns the same deterministic subset across restarts and each array
task may keep its own ledger safely. `error` is never terminal, so failures retry.

Test batches
------------
`--limit N` takes N neurons **and logs exactly which ones**, so a test run's membership is
in the build log, not just in the report CSV. It samples evenly across the sorted list
rather than taking the head, because root ids are not random — all 730 beginning
`720575940` have no published SWC — so `--sample head` returns an all-pathological batch.
Both are deterministic. `--roots a,b,c` (or `--roots @file`) restricts to specific ids, to
reproduce a batch exactly or retry named failures; every `--limit` run prints the `--roots`
line that would reproduce it.

What it does per neuron
-----------------------
1. Fetch a skeleton, in the dataset's preference order: the publisher's own full-resolution
   SWC where there is one; else **skeletonised from the mesh** (measured ~5 us/face, cheaper
   than the mesh fetch we already pay, and 20-27x more nodes than BANC's published `_l2`);
   else the dataset's coarse fallback if it has one.
2. Fetch the mesh and cut it at the NEUROPIL boundary, in SOURCE space, on the axis the
   dataset separates on (BANC on y, maleCNS on z). The gap between the two neuropils —
   244 um for BANC, 187 um for maleCNS — is dropped from both halves: registration support
   runs well past each neuropil with no anatomy to constrain it, so material there warps
   into plausible coordinates that *pass* a bbox check (docs/ISSUES.md IMG-3). This is the
   step whose absence is IMG-2.
3. Transform along the region's DECLARED chain, with the baked field collapsing the
   expensive span — no path search, no elastix, no `via`/`avoid`. See connectomes.py.
4. Trim to the target template bounding box.
5. Decide: swap the new set in, delete a spurious old one, or keep what is there.
6. Size the OBJ. Where the publisher ships an LOD ladder, choose a rung and serve their
   geometry unaltered; where they do not (BANC), decimate ours. See sizing.py. The NRRD is
   unaffected either way: it voxelises onto a ~0.5 um grid, so it neither gains from a fine
   mesh nor suffers from a coarse one.

Neuroglancer remains the long-term answer for serving.

See docs/TRANSFORMS.md (transform paths, staging, the `use_https` trap), docs/MESH_SIZING.md
(which rung, or decimate) and docs/ISSUES.md (IMG-1/IMG-2/IMG-3/IMG-4).
"""
import argparse
import base64
import io
import json
import logging
import os
import ssl
import sys
import time
import traceback
import urllib.request
import warnings
from dataclasses import dataclass, field
from multiprocessing import Pool
from typing import Optional, Sequence

import certifi

# The stock CA store on some of these python builds is empty; without this every HTTPS
# fetch fails with CERTIFICATE_VERIFY_FAILED.
ssl._create_default_https_context = lambda *a, **k: ssl.create_default_context(
    cafile=certifi.where())
warnings.filterwarnings('ignore')
logging.getLogger('navis').setLevel(logging.ERROR)

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))   # -> src/, so the package imports
from vfb_connectomics_import.images import chain, connectomes, sizing, sources  # noqa: E402
from vfb_connectomics_import.images.io import (          # noqa: E402
    PRODUCTS, TERMINAL, Ledger, OutputSet, partial_path)

KB_ENDPOINT = os.environ.get('KB_ENDPOINT', 'http://kb.virtualflybrain.org:80')
VFB_URL_PREFIXES = ('http://www.virtualflybrain.org/data/',
                    'https://www.virtualflybrain.org/data/')


def hush_navis():
    """Silence navis' INFO chatter — must run AFTER `import navis`.

    Setting the level at module import does nothing: navis installs its own handler at
    INFO when it is imported, which happens later (lazily, inside functions). Without this
    every plot3d emits "Use the `.show()` method to plot the figure.", one line per neuron.
    """
    import logging
    for name in ('navis', 'navis.plotting', 'pygeos', 'trimesh'):
        logging.getLogger(name).setLevel(logging.ERROR)


# ------------------------------------------------------------------------- cutting
# A `connectomes.Cut` names the axis, the plane and which side this region keeps. BANC
# separates on y and maleCNS on z, so neither can be hard-coded here; and cutting in SOURCE
# space is mandatory rather than a convenience, because the target-template bbox trim that
# follows it does NOT catch misplaced material (docs/ISSUES.md IMG-3).
def cut_swc(arr, cut):
    """Rows of an SWC array on the keep side of the plane. Columns 2:5 are xyz."""
    return arr[cut.mask(arr[:, 2:5])]


def cut_mesh(mesh, cut):
    """Open cut (cap=False) at the neuropil boundary. None if nothing remains.

    `cap=False` on purpose: a cap would invent a flat disc of surface that is not anatomy,
    inflate the area the mesh-sizing rule measures, and show up as a lid in the viewer.
    """
    normal = np.zeros(3)
    normal[cut.axis] = float(cut.keep)
    origin = np.zeros(3)
    origin[cut.axis] = float(cut.at)
    try:
        h = mesh.slice_plane(plane_origin=origin, plane_normal=normal, cap=False)
    except BaseException:
        return None
    return h if (h is not None and len(h.faces)) else None


# ------------------------------------------------------------------- mesh size reduction
# docs/ISSUES.md IMG-1. The served OBJs are unusably large, and the reason is tessellation
# density, not neuron size. Measured 2026-08-26 on APL, the same cell in both datasets:
#
#   hemibrain APL_R   62,244 um2    2.31 M faces    37 f/um2   263 nm mean edge   (fine)
#   maleCNS  APL_R    60,334 um2   11.97 M faces   198 f/um2   114 nm mean edge   (515 MB)
#
# Identical surface area; maleCNS simply triangulates 5.4x finer. Source density by
# dataset: hemibrain 37, FlyWire 104 (lod=2), maleCNS 198, BANC 199-220, OpticLobe 459.
# hemibrain is the outlier and it is the one that displays acceptably, so its density is
# the target and the reduction factor falls out of the source mesh rather than being
# guessed. Decimating maleCNS APL to 37 f/um2 lands it at 18.5 MB gzipped -- exactly
# where hemibrain APL already sits.
#
# Why the earlier "decimation destroys these meshes" finding was wrong: it tested 4-8
# faces/um2, a 25-50x reduction, and read component count as fragmentation on meshes whose
# *source* component count is already 17,008 (sub-um2 dust, MESH-2). At 37 f/um2 quadric
# decimation is safe -- measured on maleCNS APL: 91.0% of area kept, 0.13% of area further
# than 250 nm from the result, nothing beyond 1 um, components 17,008 -> 2,284 (dust
# merged, not arbor split), boundary edges 673 -> 3.
#
# The area that goes is voxel-scale surface corrugation, not tube thickness: the effective
# radius 2V/A is unchanged (BANC 149.6 -> 149.5 nm, maleCNS 147.0 -> 149.3 nm). So do NOT
# add a normal-offset "re-inflation" to recover the area -- matching area overshoots
# volume by 10-24% and serves neurites fatter than the reconstruction.
# Revised 2026-08-27 from 37 to 100 f/um2 after reviewing live output: at 37 the thinnest
# twigs visibly broke up, and that was judged too strong. 100 keeps ~51% of faces (a 1.97x
# reduction) i.e. "about half the file size", and sits at roughly FlyWire's lod=2 density
# (104). The 37 figure was hemibrain-matched and remains the most aggressive defensible
# target on the geometry (docs/ISSUES.md IMG-1) — this is a deliberate trade of file size
# for twig fidelity, not a correction. Source density is ~197 f/um2, confirmed two ways:
# measured directly in IMG-1 (199-220), and back-computed from the 18.8% of faces kept at
# 37 on live output.
#
# Superseded for datasets that publish a ladder (2026-09-16, docs/MESH_SIZING.md): where
# the publisher ships several rungs we pick one of theirs and decimate nothing, because the
# objective is responsibility rather than quality. `MESH_DENSITY` is therefore the target
# only for a dataset with no ladder — today that is BANC alone. It is now one side of a
# two-sided target: `sizing.decimate_target()` also caps the result at the wire budget,
# which this constant on its own never did.
MESH_DENSITY = 100.0         # faces per um2 of surface area; no-ladder datasets only
OBJ_DP = 3                   # 1 nm quantisation; worst vertex moves 0.86 nm (IMG-1)


@dataclass
class Settings:
    """Everything a worker needs that does not vary per neuron.

    Passed once to the pool initializer rather than threaded through each task — the task
    is then just (root, folder, region), which is what it should have been all along.
    """
    connectome: str = 'banc'                 # key into connectomes.CONNECTOMES
    products: Sequence[str] = ('swc', 'obj', 'nrrd')
    mode: str = 'replace'                    # 'replace' | 'fill'
    delete_spurious: bool = True
    min_nodes: int = 10
    min_faces: int = 100
    mesh_density: float = MESH_DENSITY       # no-ladder datasets only; see sizing.py
    budget: sizing.Budget = field(default_factory=sizing.Budget)
    field_dir: Optional[str] = None
    skeleton_dir: Optional[str] = None
    archive_dir: Optional[str] = None
    mmap: bool = True

    @property
    def cx(self):
        return connectomes.get(self.connectome)


# ---------------------------------------------------------------------------- worker state
# Built lazily inside each worker. h5py is NOT fork-safe and H5transform.full_ingest() is
# ~4.6 GB resident, so the parent must never open an H5 handle and workers must each build
# their own. The baked .npy fields are a different matter: they are memory-mapped, and the
# OS page cache serves every reader from one set of physical pages, so all workers share
# ~543 MB rather than holding a copy each. That sharing does not depend on fork — any
# process mmapping the same file read-only gets the same pages — so this is correct under
# both 'fork' (Linux/Jenkins) and 'spawn' (macOS) start methods.
class _Worker:
    navis = None
    settings = Settings()
    cx = None
    seq = {}
    src = None


_W = _Worker()


def worker_init(settings):
    import navis
    import flybrains

    flybrains.register_transforms()
    navis.set_pbars(hide=True)
    hush_navis()

    _W.navis = navis
    _W.settings = settings
    _W.cx = settings.cx
    _W.seq = {}
    _W.src = sources.for_connectome(settings.connectome,
                                    skeleton_dir=settings.skeleton_dir)
    # Note what is NOT here: `transforms.register()`. Chains are resolved by named edge
    # lookup (chain.py), so the baked fields never enter the navis registry and therefore
    # cannot perturb routing for anything else sharing this process — which is how
    # registering BANC's fields used to break maleCNS's brain path (docs/ISSUES.md CODE-1).


def _seq(region):
    """TransformSequence for this region, built on first use inside this worker.

    `chain.resolve` walks the region's DECLARED hops. It never searches for a path, so a
    flybrains upgrade that adds a dataset or retypes an edge fails loudly here instead of
    silently rerouting a male CNS through a female VNC template.
    """
    if region.name not in _W.seq:
        seq, _desc = chain.resolve(region, field_dir=_W.settings.field_dir,
                                   mmap=_W.settings.mmap)
        _W.seq[region.name] = seq
    return _W.seq[region.name]


# ------------------------------------------------------------------------------- fetching
@dataclass
class Sources:
    """What we managed to fetch for one neuron, in the connectome's SOURCE units."""
    mesh: object = None
    swc: object = None
    swc_source: str = 'none'
    #: rung `mesh` was fetched at. For a dataset with a ladder this is the COARSEST rung —
    #: it is here to measure surface area cheaply, not to be served. `size_mesh()` fetches
    #: the rung that actually gets written.
    mesh_lod: Optional[int] = None
    #: whether a mesh was ever fetched, as opposed to whether one is still held. `process()`
    #: drops `mesh` before `decide()` runs to free the largest allocation in the loader, and
    #: `usable` must not change when it does — otherwise saving memory silently reclassifies
    #: a mesh-only neuron as `no_source` and skips its write.
    mesh_fetched: bool = False

    @property
    def usable(self):
        """False means we have no basis for judging this neuron — and therefore no right
        to delete anything (see decide())."""
        return self.mesh_fetched or self.swc is not None


def probe_lod(cx):
    """The rung to fetch first: the coarsest the ladder offers, or 0 with no ladder.

    Coarsest because this fetch exists to measure area, and area is the one quantity that
    barely moves between rungs — maleCNS lod3 keeps 92-95% of lod0's area while costing
    ~0.4% of the faces. Paying lod1 to find out we cannot afford lod1 would be the obvious
    way to get this wrong.
    """
    return max(cx.ladder.rungs) if cx.ladder else 0


def load_sources(ident):
    """Skeleton + probe mesh, in preference order (see the module docstring).

    Mesh coverage can be incomplete upstream — BANC publishes one for 94.4% of `_skeleton`
    roots and 68.8% of `_l2`-only roots (docs/ISSUES.md IMG-4), because bancpipeline wraps
    each mesh in `try()` and swallows failures. So a missing mesh is expected, not
    exceptional, and must never be read as "this neuron has nothing here".
    """
    src, cx = _W.src, _W.cx
    lod = probe_lod(cx)
    mesh = src.mesh(ident, lod=lod)
    for arr, label in ((src.skeleton(ident), 'published_skeleton'),
                       (skeleton_from_mesh(ident, mesh), 'skeletonised_mesh'),
                       (src.coarse_skeleton(ident), 'published_coarse')):
        if arr is not None and len(arr) > 1:
            return Sources(mesh=mesh, swc=arr, swc_source=label,
                           mesh_lod=lod if mesh is not None else None,
                           mesh_fetched=mesh is not None)
    return Sources(mesh=mesh, swc=None, swc_source='none',
                   mesh_lod=lod if mesh is not None else None,
                   mesh_fetched=mesh is not None)


def as_mesh_neuron(tm, name):
    """MeshNeuron with units set. This matters: a MeshNeuron built from a bare trimesh is
    dimensionless, and navis.voxelize then cannot parse a pitch in microns."""
    mn = _W.navis.MeshNeuron(tm, units='microns')
    mn.id = mn.name = str(name)
    return mn


def skeleton_from_mesh(ident, mesh):
    """Skeletonise the mesh into an SWC array, or None.

    This is what upstream did to make BANC's published `_skeleton` files (skeletor), so it
    is the same operation rather than a substitute — and it beats the 125x-coarser `_l2`.

    On a dataset with a ladder the mesh handed in is the COARSEST rung, which would make a
    poor skeleton. That is acceptable only because this is a second-choice path that
    essentially never fires there: maleCNS publishes an SWC for 211,573 segments against
    the 166,701 VFB imports, so `published_skeleton` wins every time. If a future dataset
    has a ladder and poor skeleton coverage, fetch a finer rung here rather than living
    with it.
    """
    if mesh is None or not len(mesh.faces):
        return None
    try:
        n = _W.navis.skeletonize(as_mesh_neuron(mesh, ident)).nodes
    except Exception:
        return None
    arr = np.column_stack([
        n.node_id.values, np.zeros(len(n)),
        n.x.values, n.y.values, n.z.values,
        n.radius.values if 'radius' in n else np.zeros(len(n)),
        n.parent_id.values])
    return arr if len(arr) > 1 else None


# ----------------------------------------------------------------------- transform + trim
def _inside(pts, bb):
    return ~np.isnan(pts).any(1) & ~((pts < bb[:, 0]) | (pts > bb[:, 1])).any(1)


def xform(pts, region):
    return np.asarray(_seq(region).xform(np.asarray(pts, float).copy()), float)


def transform_swc(arr, region):
    """Cut, transform and trim an SWC array. Microns out, radius in microns. None if empty."""
    if arr is None:
        return None
    arr = cut_swc(arr, region.cut)
    if not len(arr):
        return None
    xyz = xform(arr[:, 2:5], region)
    keep = _inside(xyz, region.bb())
    if not keep.any():
        return None
    out = arr.copy().astype(float)
    out[:, 2:5] = xyz
    out = out[keep]
    kept = set(out[:, 0].astype(np.int64))
    par = out[:, 6].astype(np.int64)
    par[~np.isin(par, list(kept))] = -1          # reparent orphans to root
    out[:, 6] = par
    out[:, 5] = out[:, 5] / 1000.0               # nm radius -> microns
    return out


def transform_mesh(mesh, region):
    """Cut, transform and trim a mesh. Microns out. None if empty."""
    import trimesh
    if mesh is None:
        return None
    mesh = cut_mesh(mesh, region.cut)
    if mesh is None:
        return None
    xyz = xform(np.asarray(mesh.vertices), region)
    bad = ~_inside(xyz, region.bb())
    faces = np.asarray(mesh.faces)
    if bad.any():
        faces = faces[~bad[faces].any(1)]
        if not len(faces):
            return None
    out = trimesh.Trimesh(vertices=xyz, faces=faces, process=False)
    out.remove_unreferenced_vertices()
    return out if len(out.faces) else None


@dataclass
class Halves:
    """What of this neuron lands in this region, already in template microns."""
    swc: object = None
    mesh: object = None

    @property
    def nodes(self):
        return 0 if self.swc is None else len(self.swc)

    @property
    def faces(self):
        return 0 if self.mesh is None else len(self.mesh.faces)

    @property
    def empty(self):
        return self.swc is None and self.mesh is None


def build_halves(sources, region):
    """The skeleton half and a PROBE mesh half, both in template microns.

    The mesh here is whatever rung `load_sources` fetched — the coarsest, on a dataset with
    a ladder. It is enough to answer "is there anything in this region" and "how much
    surface area", which is all `decide()` and `size_mesh()` need from it.
    """
    return Halves(swc=transform_swc(sources.swc, region),
                  mesh=transform_mesh(sources.mesh, region))


def surface_area(mesh):
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    return float(np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]],
                                         v[f[:, 2]] - v[f[:, 0]]), axis=1).sum() / 2)


def size_mesh(ident, region, probe, st, rec):
    """The mesh to serve for this region, chosen per docs/MESH_SIZING.md.

    `probe` is the already-cut, already-transformed coarse mesh; its area sets the plan.
    Returns `(mesh, note)` in template microns, or `(probe, note)` for a dataset with no
    ladder, where the rung question does not arise and `decimate_mesh` does the work at
    write time instead.

    The loop is **predict to choose, measure to serve**: the plan picks a starting rung,
    and then every rung is judged on the face count that actually arrived. A rung that
    busts the budget or the density ceiling steps down; if the ladder runs out, the finest
    admissible rung is decimated, which is the one path that reprocesses anybody's
    geometry.
    """
    cx, budget = st.cx, st.budget
    if cx.ladder is None or probe is None:
        return probe, 'no ladder; decimation decides'

    area = surface_area(probe)
    rec['area_um2'] = round(area, 1)
    preds, start = sizing.plan(area, cx.ladder, budget)
    rec['lod_plan'] = ' '.join(f'lod{p.lod}={p.mb}MB{"" if p.fits else "!"}' for p in preds)
    if start is None:
        raise RuntimeError(f'{cx.id}: no rung of the ladder is under the '
                           f'{budget.ceiling_f_per_um2} f/um2 ceiling')

    tried, lod = [], start
    while lod is not None:
        raw = _W.src.mesh(ident, lod=lod)
        got = transform_mesh(raw, region)
        del raw
        if got is None:
            # The rung exists but nothing of it survives here. Trust the probe rather than
            # concluding the region is empty — a coarse rung can lose a thin process the
            # finer ones keep.
            tried.append(f'lod{lod}=empty')
            lod = sizing.next_rung(lod, cx.ladder, budget)
            continue
        n = len(got.faces)
        verdict = sizing.judge(n, area, budget)
        tried.append(f'lod{lod}={sizing.estimate_mb(n, budget):.1f}MB'
                     f'/{n / area:.0f}f' + ('' if verdict == sizing.ACCEPT else f'[{verdict}]'))
        if verdict == sizing.ACCEPT:
            rec.update(obj_lod=lod, obj_f_per_um2=round(n / area, 1),
                       lod_tried=' '.join(tried))
            return got, f'lod{lod}, {n:,} faces, {n / area:.0f} f/um2'
        nxt = sizing.next_rung(lod, cx.ladder, budget)
        if nxt is None:
            break
        del got
        lod = nxt

    # Nothing the publisher ships fits. Decimate the finest admissible rung to the stricter
    # of the ceiling and the budget. On maleCNS this has never fired and is not expected to:
    # lod3 does not reach 20 MB until ~328,000 um2, and APL_R — the largest cell measured —
    # is 63,397 um2.
    finest = sizing.admissible(cx.ladder, budget)[0]
    got = transform_mesh(_W.src.mesh(ident, lod=finest), region)
    if got is None:
        # The probe proved there IS material here, so every rung coming back empty is a
        # fetch failure, not a finding. `sources.mesh()` swallows exceptions and returns
        # None (coverage is genuinely patchy, IMG-4), so this is the only place the
        # difference can be drawn — and getting it wrong means `decide()` sees an empty
        # region with a usable source and deletes a correct image over a transient 503.
        # Raising makes the task retry; `error` is deliberately not terminal.
        raise RuntimeError(
            f'{ident}/{region.name}: the probe mesh (lod{probe_lod(cx)}) has material here '
            f'but no rung of the ladder returned any — treating this as a fetch failure, '
            f'not as an empty region. Tried: {" ".join(tried) or "none"}')
    before = len(got.faces)
    got = _decimate_to(got, sizing.decimate_target(
        before, area, budget.ceiling_f_per_um2, budget))
    rec.update(obj_lod=finest, obj_decimated=True,
               obj_f_per_um2=round(len(got.faces) / area, 1),
               lod_tried=' '.join(tried))
    return got, (f'lod{finest} DECIMATED {before:,} -> {len(got.faces):,} faces '
                 f'(no rung fits)')


# ---------------------------------------------------------------------------- the decision
#: Every outcome. `delete` is the only one that destroys an existing image.
KEEP, SWAP, DELETE = 'keep', 'swap', 'delete'


def decide(sources, halves, had_image, st):
    """(action, status, note) — the whole deletion policy, in one place.

    This is the function to read if you want to know when an image gets destroyed. There
    are only two ways: DELETE here, and the post-swap sweep of leftovers in
    `OutputSet.swap`. Everything else keeps what is on disk.
    """
    if not sources.usable:
        # No basis for judging this neuron, so never delete. A transient fetch failure or
        # an upstream coverage gap (94.4%/68.8%) must not destroy a good image.
        return KEEP, 'no_source', ('neither mesh nor skeleton available' +
                                   (' — existing image left untouched' if had_image else ''))

    if halves.empty:
        reason = 'no material in this region'
        status = 'empty_here'
    elif halves.nodes < st.min_nodes and halves.faces < st.min_faces:
        # A neuron that merely grazes this region leaves a few nodes at the cut plane — a
        # truncated tip, not a depictable arbor. Observed: a VNC half survived the bbox
        # trim with 5 nodes / 36 faces. This is the materiality rule of docs/ISSUES.md IMG-3.
        reason = (f'{halves.nodes} nodes / {halves.faces} faces below threshold '
                  f'({st.min_nodes}/{st.min_faces})')
        status = 'too_small'
    else:
        return SWAP, None, ''

    # We had a usable source and it puts nothing depictable here, so any image present is
    # spurious — the ~4,660 wrong-template BANC images of IMG-3. Deleting them is the only
    # way they are ever cleaned up.
    if had_image and st.delete_spurious:
        return DELETE, 'deleted_spurious', reason
    return KEEP, status, reason + (' — nothing written; existing left in place '
                                   '(--no-delete-spurious)' if had_image else
                                   ' — nothing written')


# ---------------------------------------------------------------------------- output files
def to_tree_neuron(arr, name):
    return _W.navis.TreeNeuron(pd.DataFrame({
        'node_id': arr[:, 0].astype(int), 'parent_id': arr[:, 6].astype(int),
        'x': arr[:, 2], 'y': arr[:, 3], 'z': arr[:, 4], 'radius': arr[:, 5]}),
        id=name, name=name, units='microns')


def clip_swc(arr, region):
    """Clamp an SWC array into the voxel grid. Done on the ARRAY, before the TreeNeuron is
    built, because `TreeNeuron.vertices` is a read-only property — assigning to it raises
    `AttributeError: can't set attribute`. That bit on the first neuron with a skeleton but
    no mesh (339 nodes / 0 faces), where the NRRD falls back to the skeleton: `hasattr(obj,
    'vertices')` is True for a TreeNeuron too, so the old shared helper looked safe and was
    not. MeshNeuron has `.vertices` writable and no `.nodes`; TreeNeuron has both, read-only.
    """
    bb = region.bb()
    out = np.asarray(arr, float).copy()
    out[:, 2:5] = np.clip(out[:, 2:5], bb[:, 0], bb[:, 1])
    return out


def clip_mesh(mesh, region):
    """Clamp mesh vertices into the voxel grid so voxelize can never see an out-of-range
    point. The trim uses the same bounds, so this only ever moves a point by
    floating-point noise."""
    bb = region.bb()
    mesh.vertices = np.clip(np.asarray(mesh.vertices), bb[:, 0], bb[:, 1])
    return mesh


def write_nrrd(obj, region, path):
    """Voxelise onto VFB's display grid and write a gzipped uint8 NRRD.

    Memory: the brain grid is 1210 x 566 x 174 = 119 M voxels, so ~119 MB as bool plus
    ~119 MB as uint8 — roughly 250-350 MB peak per worker, and the single largest
    allocation in this loader. Size worker count against that, not against the meshes.
    """
    vx = _W.navis.voxelize(obj, pitch=[f'{s} microns' for s in region.template.spacing],
                           bounds=region.template.bounds, parallel=False)
    vx.grid = vx.grid.astype('uint8') * 255
    _W.navis.write_nrrd(vx, filepath=path, compression_level=9)
    del vx


def _decimate_to(mesh, target):
    """Quadric-decimate to exactly `target` faces. `target` None leaves the mesh alone."""
    import trimesh
    import fast_simplification
    n = len(mesh.faces)
    if not target or target >= n:
        return mesh
    v, f = fast_simplification.simplify(np.asarray(mesh.vertices, np.float32),
                                        np.asarray(mesh.faces, np.int32),
                                        target_reduction=1 - target / n)
    return trimesh.Trimesh(vertices=np.asarray(v, float), faces=np.asarray(f, int),
                           process=False)


def decimate_mesh(mesh, density=MESH_DENSITY, budget=None):
    """Quadric-decimate for a dataset with no LOD ladder. Returns (mesh, note).

    Only reached for BANC today. Where the publisher ships rungs we pick one of theirs and
    never arrive here — see `size_mesh` and docs/MESH_SIZING.md.

    The target is `sizing.decimate_target`, which is **two-sided**: density binds for a
    typical neuron and the wire budget binds for the tail. The budget cap is the part that
    used to be missing — `budget_mb` was consulted only as a skip threshold while
    `density * area` ran uncapped, so a 60,000 um2 neuron decimated to ~6 M faces (~50 MB)
    and this function reported success. A second escape was worse still: a mesh already
    below the density target was returned untouched however large it was.
    """
    budget = budget or sizing.Budget()
    n = len(mesh.faces)
    area = surface_area(mesh)
    target = sizing.decimate_target(n, area, density, budget)
    if target is None:
        if n < 1000:
            return mesh, 'too small to decimate'
        return mesh, f'{sizing.estimate_mb(n, budget):.2f} MB est, within both limits'
    out = _decimate_to(mesh, target)
    capped = ' (budget cap)' if target == budget.max_faces else ''
    return out, (f'{n:,} -> {len(out.faces):,} faces '
                 f'({n / area:.0f} -> {len(out.faces) / area:.0f} f/um2){capped}')


def write_obj(mesh, path, dp=OBJ_DP):
    """OBJ at `dp` decimal places. navis/trimesh write 8 dp, which resolves 0.01 pm
    against an 8 nm voxel grid and costs ~1.5x the gzipped size for nothing (IMG-1)."""
    v, f = np.asarray(mesh.vertices, float), np.asarray(mesh.faces, int) + 1
    with open(path, 'wb') as fh:
        fh.write(f'# {len(v)} vertices, {len(f)} faces, microns, {dp} dp\n'
                 f'# vfb_connectomics_import.images.loader\n'.encode())
        np.savetxt(fh, v, fmt=f'v %.{dp}f %.{dp}f %.{dp}f')
        np.savetxt(fh, f, fmt='f %d %d %d')


def build_products(root, halves, region, out, st, rec):
    """Write the complete new set to `.partial` files. Returns {partial: final}.

    Nothing existing is touched here — that is the whole point. All products are rebuilt
    together: a new SWC beside an old OBJ from a different alignment would be worse than
    either alone.
    """
    built = {}
    mesh_neuron = None

    if 'swc' in out.products and halves.swc is not None:
        tmp = partial_path(out.paths['swc'])
        _W.navis.write_swc(to_tree_neuron(halves.swc, str(root)), tmp)
        built[tmp] = out.paths['swc']

    if halves.mesh is not None:
        mesh_neuron = as_mesh_neuron(clip_mesh(halves.mesh, region), root)
        if 'obj' in out.products:
            if st.cx.ladder is None:
                # No ladder: this is the only mesh there is, so reduce it ourselves.
                dec, note = decimate_mesh(halves.mesh, st.mesh_density, st.budget)
            else:
                # `size_mesh` already chose a published rung and verified its face count.
                dec, note = halves.mesh, rec.get('obj_note', 'rung chosen by size_mesh')
            rec['obj_faces'], rec['obj_note'] = len(dec.faces), note
            tmp = partial_path(out.paths['obj'])
            write_obj(dec, tmp)
            built[tmp] = out.paths['obj']
            if dec is not halves.mesh:
                del dec

    if 'nrrd' in out.products:
        # Prefer the mesh for NRRD detail, fall back to the skeleton — same preference
        # order as the maleCNS loader this replaces.
        src = mesh_neuron
        if src is None and halves.swc is not None:
            src = to_tree_neuron(clip_swc(halves.swc, region), str(root))
        if src is not None:
            tmp = partial_path(out.paths['nrrd'])
            write_nrrd(src, region, tmp)
            built[tmp] = out.paths['nrrd']
    return built


# ------------------------------------------------------------------------------ per neuron
def process(task):
    """One neuron, one region. Never raises: failures come back as status='error'."""
    root, folder, region_name = task
    st = _W.settings
    region = st.cx.region(region_name)
    t0 = time.time()
    rec = dict(root=root, region=region_name, folder=folder, status='?',
               swc_source='none', nodes=0, faces=0, wrote=[], removed=[],
               had_existing=False, note='')
    out = OutputSet(folder, st.products)
    try:
        os.makedirs(folder, exist_ok=True)
        out.clear_partials()                 # discard truncated writes from a kill
        had_image = bool(out.existing_volumes())
        rec['had_existing'] = had_image

        # `fill` only touches neurons with a gap (IMG-4's no-image share).
        if st.mode == 'fill' and out.complete():
            rec.update(status='skipped', note='all outputs present (mode=fill)')
            return _done(rec, t0, st.archive_dir)

        # Archive the pre-replacement image BEFORE anything can overwrite it. A copy, so
        # the live folder keeps serving. Only for test batches (--archive).
        arc = None
        if st.archive_dir:
            arc = os.path.join(st.archive_dir, region_name, str(root))
            rec['old_files'] = out.archive_to(os.path.join(arc, 'old'))

        sources = load_sources(root)
        rec['swc_source'] = sources.swc_source
        halves = build_halves(sources, region)
        sources.mesh = None                  # the probe; the big allocation, drop it early

        # Choose the rung to serve, if this dataset ships a ladder. Done BEFORE decide()
        # so materiality is judged on the mesh that would actually be written, not on the
        # coarse probe — at lod3 a real arbor can fall under --min-faces.
        if halves.mesh is not None:
            halves.mesh, rec['obj_note'] = size_mesh(root, region, halves.mesh, st, rec)
        rec['nodes'], rec['faces'] = halves.nodes, halves.faces

        action, status, note = decide(sources, halves, had_image, st)
        rec['note'] = note
        if action is KEEP:
            rec['status'] = status
            return _done(rec, t0, st.archive_dir)
        if action is DELETE:
            rec['removed'] = out.remove_all()
            rec['status'] = status
            rec['note'] = f'{note}; removed {len(rec["removed"])} stale file(s)'
            return _done(rec, t0, st.archive_dir)

        built = build_products(root, halves, region, out, st, rec)
        del halves
        if not built:
            rec.update(status='nothing_to_write',
                       note='nothing built; existing image left untouched')
            return _done(rec, t0, st.archive_dir)
        rec['wrote'], rec['removed'] = out.swap(built)
        rec['status'] = 'replaced' if had_image else 'created'
        if arc:
            rec['new_files'] = OutputSet(folder, st.products).archive_to(
                os.path.join(arc, 'new'))
    except Exception as e:
        # Discard partials so the old image keeps serving and the next run retries cleanly.
        try:
            out.clear_partials()
        except Exception:
            pass
        rec.update(status='error',
                   note=f'{type(e).__name__}: {e}'
                        + (' (existing image left untouched)' if rec['had_existing'] else ''))
        rec['traceback'] = traceback.format_exc()
    return _done(rec, t0, st.archive_dir)


def _done(rec, t0, archive_dir=None):
    rec['seconds'] = round(time.time() - t0, 2)
    if archive_dir:
        # A sidecar per neuron so vfb-banc-compare needs nothing but the archive dir,
        # and so "this product is missing" is recorded rather than inferred from absence.
        d = os.path.join(archive_dir, rec['region'], str(rec['root']))
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, 'meta.json'), 'w') as fh:
                json.dump({k: rec.get(k) for k in
                           ('root', 'region', 'status', 'swc_source', 'nodes', 'faces',
                            'obj_faces', 'obj_note', 'note', 'old_files', 'new_files',
                            'had_existing', 'seconds')},
                          fh, indent=1)
        except Exception:
            pass
    return rec


# ------------------------------------------------------------------------------- work list
def kb_query(statement, endpoint=KB_ENDPOINT):
    user = os.environ.get('KB_USER') or 'neo4j'
    pw = os.environ.get('KB_PASSWORD') or os.environ.get('password')
    if not pw:
        raise SystemExit('set $KB_PASSWORD (or $password) for the VFB KB')
    req = urllib.request.Request(
        f'{endpoint}/db/data/transaction/commit',
        data=json.dumps({'statements': [{'statement': statement}]}).encode(),
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Basic ' + base64.b64encode(
                     f'{user}:{pw}'.encode()).decode()})
    d = json.load(urllib.request.urlopen(req, timeout=900))
    if d.get('errors'):
        raise SystemExit(f'KB query failed: {d["errors"]}')
    return [x['row'] for x in d['results'][0]['data']]


def kb_worklist(cx, region_name, dataset=None, site=None, endpoint=KB_ENDPOINT):
    """(root_id, folder) for every channel of `dataset` registered to this region's template.

    This returns ALL of them — the KB has pre-created channels on both templates for every
    Bates2026 individual, while only ~2,964 neurons genuinely cross the neck. `decide()` is
    what determines whether a given folder is written, left alone, or cleared.

    The root id comes from the **Site xref accession**, not from `r.filename`, and the two
    are asserted equal. Verified 2026-08-25: they agree in all 146,511 brain channels, so
    this changes nothing today — it is here so a future materialisation (BANC's metadata
    already carries a `root_890` column) cannot silently feed this loader the wrong ids.

    Filtering on the DataSet is already safe for v626: the 15,779 Bates2025-only
    individuals that still have a brain channel are excluded because they have no
    Bates2026 `has_source`, and the 65,053 individuals in *both* datasets have identical
    BANC626/BANC888 accessions (0 differ) — same root, same segment, so replacing their
    image is correct for both.
    """
    dataset = dataset or cx.dataset
    site = site or cx.site
    channel = cx.region(region_name).template.channel
    rows = kb_query(
        f"MATCH (d:DataSet {{short_form:'{dataset}'}})<-[:has_source]-(i:Individual)"
        f"<-[:depicts]-(ic:Individual)-[r:in_register_with]"
        f"->(tc:Template {{short_form:'{channel}'}}) "
        f"MATCH (i)-[x:database_cross_reference]->(:Site {{short_form:'{site}'}}) "
        f"RETURN x.accession[0] AS root, r.folder[0] AS folder, "
        f"r.filename[0] AS reg_filename", endpoint=endpoint)
    out, mismatched = [], []
    for root, folder, reg_filename in rows:
        if not root or not folder:
            continue
        if reg_filename and str(reg_filename) != str(root):
            mismatched.append((str(root), str(reg_filename)))
        else:
            out.append((str(root), folder))
    if mismatched:
        # Never guess which is right: the image would depict the wrong segment.
        raise SystemExit(
            f'{len(mismatched):,} channels where the {site} accession disagrees with the '
            f'in_register_with filename, e.g. {mismatched[:3]}. This invariant held for '
            f'all 146,511 channels on 2026-08-25, so something has changed in the KB — '
            f'resolve which id is authoritative before writing any image.')
    return out


def _norm_root(write_root):
    """`write_root` with exactly one trailing separator.

    The VFB URL prefixes end in '/', so substituting a root that does not would splice
    straight into the next path segment: IMAGE_WRITE=/data/vfb would produce
    '/data/vfbVFB/i/0010/...'. Normalising here means both spellings behave.
    """
    return write_root if write_root.endswith('/') else write_root + '/'


def to_local(folder, write_root):
    root = _norm_root(write_root)
    for p in VFB_URL_PREFIXES:
        folder = folder.replace(p, root)
    return os.path.dirname(folder)


def to_url(local_folder, write_root):
    """Inverse of `to_local`: the public URL of a neuron's image folder.

    Printed per neuron so the console log is clickable — you can go straight from a line in
    the Jenkins build to the images it just wrote. The maleCNS loader did this and it is
    genuinely the fastest way to eyeball a result.
    """
    root = _norm_root(write_root)
    if not local_folder.startswith(root):
        return local_folder                      # not under write_root; show the path
    return VFB_URL_PREFIXES[0] + local_folder[len(root):].lstrip('/') + '/'


def build_tasks(args, regions):
    """Deterministic task list: sort -> shard -> roots -> ledger -> limit.

    Sharding comes BEFORE the ledger so each shard always owns exactly the same subset
    across restarts. Filtering first would shift the stride boundaries between runs, which
    is harmless with one shared ledger but would silently drop or duplicate neurons if each
    array task keeps its own.
    """
    tasks = []
    for name in regions:
        cx = connectomes.get(args.connectome)
        rows = kb_worklist(cx, name, dataset=args.dataset, site=args.site)
        print(f'{name}: {len(rows):,} channels in {args.dataset or cx.dataset}', flush=True)
        tasks += [(root, to_local(folder, args.write_root), name) for root, folder in rows]
    tasks.sort()

    if args.of > 1:
        tasks = tasks[args.shard::args.of]
        print(f'shard {args.shard}/{args.of}: {len(tasks):,} neurons')
    # --roots is a selection like --shard, so it narrows the work BEFORE the ledger is
    # consulted; otherwise the resume line reports "146,508 remain" for a 3-neuron run.
    if args.roots:
        wanted = set(_read_roots(args.roots))
        tasks = [t for t in tasks if t[0] in wanted]
        found = {t[0] for t in tasks}
        missing = wanted - found
        # Count ROOTS, not tasks: --region both gives two tasks per root, and reporting
        # "6 of 3 requested roots" reads like a bug in the selection.
        print(f'--roots: {len(found):,} of {len(wanted):,} requested roots matched '
              f'({len(tasks):,} task(s) across {len(regions)} region(s))'
              + (f'; not found: {sorted(missing)[:5]}' if missing else ''))
    if args.ledger and not args.redo:
        done = Ledger(args.ledger).done()
        if done:
            before = len(tasks)
            tasks = [t for t in tasks if (t[0], t[2]) not in done]
            print(f'ledger {args.ledger}: {len(done):,} recorded, '
                  f'{before - len(tasks):,} skipped, {len(tasks):,} remain')

    if args.limit and args.limit < len(tasks):
        if args.sample == 'head':
            tasks = tasks[:args.limit]
        else:
            # Evenly strided by default. Root IDs are not random: every one of the 730
            # roots beginning 720575940 has no published SWC (mostly unclassified
            # fragments, glia and not_a_neuron), so `--sample head` on a sorted list
            # returns an all-pathological batch. Striding is just as deterministic and
            # actually representative.
            step = len(tasks) / args.limit
            tasks = [tasks[int(i * step)] for i in range(args.limit)]
        log_selection(tasks, args.sample)
    return tasks


def _read_roots(spec):
    """Root ids from a comma-separated list, or from a file if `spec` starts with '@'."""
    if spec.startswith('@'):
        with open(spec[1:]) as fh:
            raw = fh.read().replace(',', ' ').split()
    else:
        raw = spec.replace(',', ' ').split()
    return [r.strip() for r in raw if r.strip()]


def log_selection(tasks, how, cap=200):
    """Print exactly which neurons a limited run selected.

    A test batch is only useful if you can tell afterwards which neurons were in it, and
    the progress lines do not say. The ledger and --report CSV both record every root, but
    those are files; this puts the membership in the build log itself.
    """
    print(f'selected {len(tasks):,} neuron(s) [{how}] — '
          f'{"listing all" if len(tasks) <= cap else f"first/last {cap // 2}"}:')
    shown = tasks if len(tasks) <= cap else tasks[:cap // 2] + [None] + tasks[-cap // 2:]
    for t in shown:
        if t is None:
            print('   ...')
            continue
        print(f'   {t[0]:20s} {t[2]}')
    print(f'reproduce this exact batch with: --roots {",".join(t[0] for t in tasks[:5])}'
          + (',...' if len(tasks) > 5 else ''), flush=True)


# ------------------------------------------------------------------------------------ main
def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--connectome', default=os.environ.get('CONNECTOME', 'banc'),
                    choices=sorted(connectomes.CONNECTOMES),
                    help='which dataset to build. Selects the bucket, the cut planes, the '
                         'transform chain, the DataSet/Site and the LOD ladder — all of '
                         'them declared in images/connectomes.py, none of them here.')
    ap.add_argument('--region', default='brain', choices=['brain', 'vnc', 'both'],
                    help='which template(s) to write (default: brain)')
    ap.add_argument('--mode', default='replace', choices=['replace', 'fill'],
                    help='replace: rebuild every neuron and swap the new image in over the '
                         'old one, one neuron at a time (default — almost every neuron '
                         'already has a v626-era image). fill: only write where a product '
                         'is missing, leaving existing images alone.')
    ap.add_argument('--products', default='swc,obj,nrrd',
                    help='comma-separated subset of swc,obj,nrrd (default: all)')
    ap.add_argument('--no-delete-spurious', action='store_true',
                    help='do not remove an existing image when the rebuild finds no '
                         'material in this region. Default is to remove it — that is the '
                         '~4,660 wrong-template images of docs/ISSUES.md IMG-3. Use this for a '
                         'first cautious pass.')
    ap.add_argument('--ledger', default=os.environ.get('IMAGE_LEDGER',
                                                       os.environ.get('BANC_LEDGER')),
                    help='append-only JSONL of finished neurons. REQUIRED for a meaningful '
                         'resume in replace mode: existing files cannot indicate progress '
                         'because almost every neuron already has them. Errors are retried.')
    ap.add_argument('--workers', type=int, default=8,
                    help='processes; ~350 MB peak each from voxelisation (default 8)')
    ap.add_argument('--field-dir', default=None,
                    help='baked fields; default $IMAGE_FIELD_DIR or $BANC_FIELD_DIR '
                         '(see docs/TRANSFORMS.md)')
    ap.add_argument('--skeleton-dir', default=os.environ.get('IMAGE_SWC_DIR',
                                                             os.environ.get('BANC_SWC_DIR')),
                    help='local mirror of banc_banc_space_swc/ — strongly recommended, it '
                         'removes ~0.5 s of per-neuron request latency')
    ap.add_argument('--write-root', default=os.environ.get('IMAGE_WRITE', '/IMAGE_WRITE/'),
                    help='local path that replaces the VFB data URL prefix')
    ap.add_argument('--dataset', default=None,
                    help="VFB DataSet; default is the connectome's own (Bates2026 for "
                         'banc, Berg2025a for malecns)')
    ap.add_argument('--site', default=None,
                    help='Site node whose accession is the neuron id; default is the '
                         "connectome's own (BANC888, male-cns_v1_0)")
    ap.add_argument('--shard', type=int, default=0, help='shard index for array jobs')
    ap.add_argument('--of', type=int, default=1, help='number of shards')
    ap.add_argument('--limit', type=int, default=None,
                    help='process at most N neurons, and log exactly which ones. Use for '
                         'test batches.')
    ap.add_argument('--sample', default='strided', choices=['strided', 'head'],
                    help='how --limit picks its N. strided (default) spreads the pick over '
                         'the whole sorted list; head takes the literal first N, which on '
                         'BANC is an all-pathological batch (the 730 roots beginning '
                         '720575940 have no published SWC). Both are deterministic.')
    ap.add_argument('--roots', default=None,
                    help='restrict to these root ids: comma-separated, or @file. Use to '
                         'reproduce a batch exactly, or to retry specific failures.')
    ap.add_argument('--redo', action='store_true',
                    default=os.environ.get('redo') == 'true',
                    help='ignore the ledger and reprocess every neuron in the selection. '
                         'This does NOT mean "delete first" — the old image is only ever '
                         'overwritten by a finished new one.')
    ap.add_argument('--min-nodes', type=int, default=10,
                    help='a region with fewer nodes than this is not depictable (default '
                         '10); a grazing neuron leaves a truncated tip, not an arbor')
    ap.add_argument('--min-faces', type=int, default=100,
                    help='mesh equivalent of --min-nodes (default 100)')
    ap.add_argument('--mesh-density', type=float, default=MESH_DENSITY,
                    help='for datasets with NO LOD ladder (BANC today): decimate the OBJ '
                         'to this many faces per um2 (default 100, ~2x reduction on BANC; '
                         '37 is the hemibrain-matched value but breaks up the thinnest '
                         'twigs). 0 disables the density target — the wire budget still '
                         'applies. Ignored where the publisher ships rungs.')
    ap.add_argument('--mesh-budget-mb', type=float, default=sizing.Budget.max_mb,
                    help='hard cap on a served OBJ, in estimated GZIPPED MB (default 20). '
                         'NOTE this changed meaning: it used to be the skip threshold, '
                         'which is now --mesh-skip-mb. Enforced on the measured face '
                         'count, never on the prediction.')
    ap.add_argument('--mesh-skip-mb', type=float, default=sizing.Budget.skip_mb,
                    help='leave a mesh alone if it is already smaller than this '
                         '(default 4 MB). Never a cap — see --mesh-budget-mb.')
    ap.add_argument('--mesh-ceiling', type=float, default=sizing.Budget.ceiling_f_per_um2,
                    help='faces per um2 above which nothing displays better (default 200). '
                         'A rung measuring above it steps down even if it fits the budget.')
    ap.add_argument('--no-mmap', action='store_true',
                    help='read the baked fields into memory instead of memory-mapping '
                         'them. Only needed if the mount does not support mmap (some NFS '
                         'exports). Costs ~543 MB RESIDENT PER WORKER, so lower --workers '
                         'to match. Memory-mapping is otherwise strictly better: the '
                         'kernel page cache shares one copy across all workers.')
    ap.add_argument('--no-download', action='store_true',
                    help='do not fetch the tail-hop H5 bridging registrations if absent; '
                         'fail instead. Use when $FLYBRAINS_DATA is pre-staged read-only.')
    ap.add_argument('--archive', default=None,
                    help='for TEST batches: copy each neuron\'s pre-replacement image, '
                         'and the new one, into DIR/<region>/<root>/{old,new}/ plus a '
                         'meta.json. Never touches the live folder. Render a comparison '
                         'with vfb-banc-compare. Do not use on a full run.')
    ap.add_argument('--quiet', action='store_true',
                    help='suppress the per-neuron console line (status, counts and a '
                         'clickable link to the image folder). Progress lines, errors and '
                         'the summary are always printed.')
    ap.add_argument('--tracebacks', type=int, default=3,
                    help='print a full stack trace for the first N errors (default 3). '
                         'One-line notes for every error always go to --report.')
    ap.add_argument('--progress-every', type=int, default=200,
                    help='progress line interval in neurons (default 200)')
    ap.add_argument('--report', default=None, help='write a per-neuron CSV report here')
    ap.add_argument('--dry-run', action='store_true',
                    help='preflight and build the work list, then stop')
    return ap.parse_args(argv)


#: (source, target) of a LIVE H5 hop -> the flybrains file it reads and the downloader that
#: fetches it. Keyed on the hop rather than on the region, because which hops stay live is a
#: property of how far each connectome's field was baked: BANC bakes to the F templates and
#: leaves the F -> U tail live, while maleCNS bakes all the way to U and needs none of this.
H5_DEPS = {
    ('JRC2018F', 'JRC2018U'): ('JRC2018U_JRC2018F.h5', 'download_jrc_transforms'),
    ('JRCVNC2018F', 'JRCVNC2018U'): ('JRCVNC2018U_JRCVNC2018F.h5',
                                     'download_jrc_vnc_transforms'),
}


def h5_needed(cx, regions):
    """The H5 dependencies the declared chains actually read, deduplicated."""
    need = {}
    for name in regions:
        for hop in cx.region(name).hops(use_baked=True):
            if hop.baked:
                continue
            dep = H5_DEPS.get((hop.source, hop.target))
            if dep:
                need[dep] = f'{name}: {hop}'
    return need


def ensure_h5(cx, regions, download=True):
    """Make sure every live H5 hop's registration is on this machine.

    Without something equivalent a fresh agent with an empty `$FLYBRAINS_DATA` fails on the
    first neuron instead of at preflight. Only what the selected regions actually read is
    fetched: a brain-only BANC run has no need for the VNC set, which includes a 1 GB
    `JRCVNC2018M_MANC.h5` we never touch — and a maleCNS run needs nothing at all.
    """
    import flybrains
    from flybrains.download import get_data_home
    need = h5_needed(cx, regions)
    if not need:
        print(f'h5: none needed — {cx.id} chains are baked end to end')
        return
    home = get_data_home()
    for (fname, fn), why in need.items():
        path = os.path.join(home, fname)
        if os.path.exists(path):
            print(f'h5 [{why}]: {path} ({os.path.getsize(path) / 1e6:.0f} MB)')
            continue
        if not download:
            raise SystemExit(
                f'{fname} not found in {home} and --no-download was given. The hop '
                f'[{why}] cannot run. Fetch it with flybrains.{fn}() or set '
                f'$FLYBRAINS_DATA.')
        print(f'h5 [{why}]: {fname} absent — downloading via flybrains.{fn}()',
              flush=True)
        getattr(flybrains, fn)()
        if not os.path.exists(path):
            raise SystemExit(f'flybrains.{fn}() ran but {path} is still missing')


#: (import name, what breaks without it). Checked at preflight because several of these
#: fail in ways that LOOK like data problems rather than config problems — a missing
#: cloudvolume makes every mesh fetch return None, which is indistinguishable from
#: "upstream published no mesh for this neuron", and silently degrades 40% of neurons to
#: the 125x-coarser published _l2 skeleton. Observed for real on a rebuilt venv.
REQUIRED = (
    ('navis', 'transforms and IO'),
    ('flybrains', 'template registration'),
    ('trimesh', 'mesh slicing'),
    ('scipy', 'baked-field interpolation'),
    ('cloudvolume', 'mesh fetch — without it EVERY neuron reports no mesh'),
    ('nrrd', 'NRRD output'),
    ('fast_simplification', 'OBJ decimation — needed above the wire budget'),
    ('skeletor', 'skeletonising the mesh for the 40.7% with no published _skeleton'),
)


def check_deps():
    """Fail with a list, not one import error at a time."""
    import importlib
    missing = []
    for mod, why in REQUIRED:
        try:
            importlib.import_module(mod)
        except Exception as e:
            missing.append(f'  {mod:22s} {why}   [{type(e).__name__}]')
    if missing:
        raise SystemExit(
            'missing python dependencies:\n' + '\n'.join(missing) +
            '\n\nInstall with:  pip install -e ".[images]"\n'
            'Do NOT run without these — a missing cloudvolume or skeletor degrades output '
            'silently rather than failing.')
    import importlib.metadata as md
    ver = []
    for mod, _ in REQUIRED:
        name = {'cloudvolume': 'cloud-volume', 'nrrd': 'pynrrd',
                'fast_simplification': 'fast-simplification'}.get(mod, mod)
        try:
            ver.append(f'{name} {md.version(name)}')
        except Exception:
            ver.append(f'{name} ?')
    print('deps: ' + ', '.join(ver), flush=True)


def preflight(args, regions):
    """Fail in seconds on a misconfigured agent rather than hours in.

    Deliberately does not run a transform: that would open an h5py handle in the parent,
    and h5py is not fork-safe.

    Note `hdf5plugin` is NOT needed here, unlike the maleCNS job which imports it. Checked
    2026-08-26: both H5 files this loader reads use plain gzip
    (`JRC2018U_JRC2018F.h5:0/dfield` and `JRCVNC2018U_JRCVNC2018F.h5:dfield`, compression
    gzip opts 6), which h5py handles natively. The maleCNS import was for its own
    JRCFIB2022M chain.
    """
    import flybrains
    import navis
    from vfb_connectomics_import.images import transforms as baked
    navis.set_pbars(hide=True)
    hush_navis()
    check_deps()
    cx = connectomes.get(args.connectome)
    print(f'connectome: {cx.id} — {cx.label}  (DataSet {cx.dataset}, Site {cx.site}, '
          f'space {cx.space}/{cx.units})')
    print(f'mesh sizing: ' + ('ladder ' + str(cx.ladder.rungs) + f' — {cx.ladder.calibrated_from}'
                              if cx.ladder else f'no ladder; decimate to {args.mesh_density} f/um2'))

    # 1. Cheapest check first. Locating our own fields is an instant stat; the H5 step
    #    below may download 717 MB. Checking in the other order meant a misconfigured
    #    agent paid for the download and *then* failed.
    d, how = baked.resolve_field_dir(args.field_dir)
    print(f'baked fields: {d}  (chosen by {how})', flush=True)

    # 2. Now the possibly-expensive one. flybrains only registers an H5 edge for a file
    #    that exists, so register_transforms() has to run AFTER any download or the
    #    chain resolution in step 3 would find no edge at all.
    ensure_h5(cx, regions, download=not args.no_download)
    flybrains.register_transforms()

    # 3. Resolve each declared chain for real. This is the whole preflight: every hop is
    #    looked up as a NAMED edge of a declared type and every baked field is opened and
    #    its sidecar checked against the hop it claims to be, so a missing field, a
    #    retyped flybrains edge or a field built against the wrong target all fail here
    #    rather than on the first neuron. `transforms.register()` is deliberately NOT
    #    called: nothing needs the fields in the global graph, and putting them there
    #    perturbs routing for every other dataset in the process (docs/ISSUES.md CODE-1).
    for name in regions:
        _seq_, desc = chain.resolve(cx.region(name), field_dir=args.field_dir,
                                    mmap=not args.no_mmap)
        print(f'chain [{name} -> {cx.region(name).template.name}]:')
        for line in desc:
            print(f'    {line}')
        cut = cx.region(name).cut
        print(f'    cut: {"xyz"[cut.axis]} {"<" if cut.keep < 0 else ">"} {cut.at:,.0f} '
              f'{cx.units}  ({cut.derived_from})')
        del _seq_

    if args.skeleton_dir and os.path.isdir(args.skeleton_dir):
        expected = sources.SOURCES[cx.id].EXPECTED_SWC
        n = len([f for f in os.listdir(args.skeleton_dir) if f.endswith('.swc')])
        pct = 100.0 * n / expected
        print(f'staged skeletons: {args.skeleton_dir} ({n:,} files, '
              f'{pct:.1f}% of the expected {expected:,})')
        if n < 0.95 * expected:
            # A staged dir is authoritative — a miss does NOT fall back to the bucket, it
            # falls through to skeletonising the mesh. So a half-finished rsync silently
            # downgrades published skeletons instead of failing, which is worth shouting
            # about rather than printing a number nobody reads.
            print(f'  *** WARNING: the mirror looks INCOMPLETE ({expected - n:,} '
                  f'files short). A staged directory is treated as authoritative: '
                  f'missing files do NOT fall back to the bucket, they fall through to '
                  f'skeletonising the mesh. Finish the rsync, or unset --skeleton-dir to '
                  f'fetch per neuron. ***', flush=True)
    else:
        print(f'staged skeletons: none ({args.skeleton_dir or "--skeleton-dir unset"}); '
              f'per-neuron HTTPS fetch adds ~0.5 s/neuron '
              f'(~2.6 h of wall clock over the full brain run at 8 workers)')
    if args.mode == 'replace' and not args.ledger:
        print('WARNING: --mode replace without --ledger. Nothing will record where this '
              'run got to, so a restart begins again from the first neuron.')


#: one-line-per-neuron statuses that are worth a compact console line even when things
#: went fine. Anything not here still prints, so nothing is ever silently skipped.
def neuron_line(rec, write_root):
    """One compact, clickable line per neuron.

    The URL is the point: a Jenkins console line you can click straight through to the
    images it just wrote. At 146k neurons this is ~146k lines (~20 MB), which Jenkins
    handles fine and the existing VFB loaders already do. `--quiet` turns it off.
    """
    bits = []
    if rec['wrote']:
        bits.append('+' + ','.join(sorted(
            k.replace('volume_man.obj', 'obj').replace('volume.', '')
            for k in rec['wrote'])))
    if rec['removed']:
        bits.append(f'-{len(rec["removed"])}')
    if rec['nodes'] or rec['faces']:
        faces = f'{rec["faces"]}f'
        obj = rec.get('obj_faces')
        if obj is not None and obj < rec['faces']:
            # decimated: show both, so the log alone answers "was this reduced?"
            faces = f'{rec["faces"]}->{obj}f'
        bits.append(f'{rec["nodes"]}n/{faces}')
    # Which rung was served, and at what density. On a ladder dataset this is the only
    # place the choice appears in the console log, and it is the thing to grep for when a
    # neuron looks too coarse.
    if rec.get('obj_lod') is not None:
        bits.append(f'lod{rec["obj_lod"]}'
                    + (f'@{rec["obj_f_per_um2"]:.0f}f/um2' if rec.get('obj_f_per_um2') else '')
                    + ('*' if rec.get('obj_decimated') else ''))
    detail = (' '.join(bits) or rec['note'])[:52]
    return (f'  {rec["status"]:16s} {rec["root"]:20s} {rec["region"]:5s} '
            f'{rec["seconds"]:5.1f}s  {detail:52s} '
            f'{to_url(rec["folder"], write_root)}')


def report_progress(i, total, t0, counts):
    el = time.time() - t0
    rate, left = el / i, total - i
    eta = left * rate
    # Include the weekday once the ETA is more than 12 h out — a bare "02:10" on a
    # multi-day run is ambiguous, which is the whole point of printing it.
    fin = time.localtime(time.time() + eta)
    when = time.strftime('%H:%M' if eta < 12 * 3600 else '%a %H:%M', fin)
    hrs = eta / 3600
    left_str = f'{eta / 60:.0f}m' if hrs < 3 else f'{hrs:.1f}h'
    print(f'  [{i:,}/{total:,}  {100.0 * i / total:5.1f}%]  {left:,} left  '
          f'{rate:.2f} s/neuron  elapsed {el / 3600:.1f}h  ETA {left_str} '
          f'(~{when})  '
          + '  '.join(f'{k}={v}' for k, v in sorted(counts.items())), flush=True)


def summarise(recs, elapsed, workers, report_path=None):
    df = pd.DataFrame(recs)
    if report_path:
        df.drop(columns=['traceback'], errors='ignore').to_csv(report_path, index=False)
        print(f'\nreport -> {report_path}')
    print(f'\n{"=" * 72}\n{len(df):,} neurons in {elapsed / 60:.1f} min '
          f'({elapsed / max(len(df), 1):.2f} s/neuron, {workers} workers)\n{"=" * 72}')
    for k, v in df.status.value_counts().sort_index().items():
        print(f'  {k:18s} {v:7,}')
    print('\n  SWC source used:')
    for k, v in df.swc_source.value_counts().items():
        print(f'    {k:22s} {v:7,}')
    wrote = df[df.status.isin(['replaced', 'created'])]
    if len(wrote):
        print(f'\n  wrote: nodes median {wrote.nodes.median():,.0f}  '
              f'faces median {wrote.faces.median():,.0f}')
    if 'obj_faces' in df:
        dec = df[df.obj_faces.notna() & (df.obj_faces < df.faces)]
        n_obj = int(df.obj_faces.notna().sum())
        print(f'\n  OBJ decimation: {len(dec):,} of {n_obj:,} written meshes reduced '
              f'(the rest needed no reduction)')
        if len(dec):
            print(f'    median {dec.faces.median():,.0f} -> {dec.obj_faces.median():,.0f} '
                  f'faces  ({100 * (1 - dec.obj_faces.sum() / dec.faces.sum()):.0f}% of '
                  f'faces removed overall)')
    errs = df[df.status == 'error']
    if len(errs):
        print(f'\n  {len(errs):,} error(s) — these are RETRIED on the next run '
              f'(never recorded as terminal). Most common:')
        for note, n in errs.note.value_counts().head(5).items():
            print(f'    {n:6,}  {str(note)[:96]}')
    return df


def main(argv=None):
    args = parse_args(argv)
    products = [p.strip() for p in args.products.split(',') if p.strip()]
    unknown = set(products) - set(PRODUCTS)
    if unknown:
        raise SystemExit(f'unknown product(s): {sorted(unknown)}')
    regions = ['brain', 'vnc'] if args.region == 'both' else [args.region]

    preflight(args, regions)
    tasks = build_tasks(args, regions)
    print(f'to process: {len(tasks):,}   products={products}   mode={args.mode}   '
          f'workers={args.workers}', flush=True)
    if args.dry_run:
        print(f'{"root":20s} {"region":7s} folder')
        for root, folder, name in tasks[:5]:
            print(f'{root:20s} {name:7s} {folder}')
        return 0
    if not tasks:
        # A fully-resumed shard has nothing left. That is success, and it must exit 0 so a
        # Jenkins array task that is simply already done goes green.
        print('nothing to do — every neuron in this selection is already recorded as '
              'finished in the ledger')
        return 0

    settings = Settings(
        connectome=args.connectome,
        products=products, mode=args.mode,
        delete_spurious=not args.no_delete_spurious,
        min_nodes=args.min_nodes, min_faces=args.min_faces,
        mesh_density=args.mesh_density,
        budget=sizing.Budget(max_mb=args.mesh_budget_mb, skip_mb=args.mesh_skip_mb,
                             ceiling_f_per_um2=args.mesh_ceiling),
        field_dir=args.field_dir, skeleton_dir=args.skeleton_dir,
        archive_dir=args.archive, mmap=not args.no_mmap)

    t0, recs, counts = time.time(), [], {}
    pool = None
    if args.workers > 1:
        # maxtasksperchild recycles workers so per-neuron allocations cannot accumulate
        # across a long run.
        pool = Pool(args.workers, initializer=worker_init, initargs=(settings,),
                    maxtasksperchild=200)
        results = pool.imap_unordered(process, tasks, chunksize=1)
    else:
        worker_init(settings)
        results = (process(t) for t in tasks)

    with Ledger(args.ledger) as ledger:
        for i, rec in enumerate(results, 1):
            recs.append(rec)
            counts[rec['status']] = counts.get(rec['status'], 0) + 1
            ledger.record(rec)
            if not args.quiet:
                print(neuron_line(rec, args.write_root), flush=True)
            if rec['status'] == 'error':
                print(f"  ERROR {rec['root']} {rec['region']}: {rec['note']}", flush=True)
                # Print the traceback for the first few only. One line is not enough to
                # debug from, but a long run with a systematic fault would otherwise
                # flood the console with thousands of identical stacks.
                n_err = counts.get('error', 0)
                if n_err <= args.tracebacks and rec.get('traceback'):
                    print('  ' + rec['traceback'].replace('\n', '\n  ').rstrip(),
                          flush=True)
                elif n_err == args.tracebacks + 1:
                    print(f'  (further tracebacks suppressed; --tracebacks '
                          f'{args.tracebacks}. Full notes are in --report)', flush=True)
            if i % args.progress_every == 0 or i == len(tasks):
                report_progress(i, len(tasks), t0, counts)
    if pool:
        pool.close()
        pool.join()

    summarise(recs, time.time() - t0, args.workers, args.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
