#!/usr/bin/env python
"""Write BANC v888 neuron images (SWC + OBJ + NRRD) onto the VFB templates.

Replaces the ad-hoc maleCNS-style loader that lived only inside a Jenkins job. Same output
contract — `volume.swc`, `volume_man.obj`, `volume.nrrd` written into the KB-supplied
folder — but BANC-specific and version-controlled.

The filesystem contract (what is written, swapped and deleted) lives in
[`io.py`](io.py). It is separate because it is the part that can
destroy a served image, and it needs no network or transform, so it can be read closely and
tested outright. This module owns fetching, geometry, transforms and orchestration.

Usage
-----
    export BANC_FIELD_DIR=/local/banc_transform_fields      # required, see docs/TRANSFORMS.md
    export KB_USER=... KB_PASSWORD=...
    vfb-banc-images --region brain --workers 8 --ledger run.jsonl
    # or, uninstalled: PYTHONPATH=src python -m vfb_connectomics_import.images.loader

    # Jenkins/SLURM array: split the work list N ways, one ledger per task
    vfb-banc-images --region brain --shard $I --of $N --ledger shard-$I.jsonl

    # stage skeletons in bulk first (strongly recommended, see --skeleton-dir)
    gsutil -m rsync -r \
      gs://lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/banc_banc_space_swc \
      /local/banc_swc

Replace in place, one neuron at a time (`--mode replace`, the default)
---------------------------------------------------------------------
Almost every BANC neuron **already has** a v626-era image. This job replaces them, and it
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
* Files left over from the previous alignment are swept *after* a successful swap — stale
  `thumbnail*`, and any product no longer in `--products`.

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
1. Fetch the mesh (cloudvolume, anonymous HTTPS) and a skeleton. Skeleton preference:
     a. the published `<root>_skeleton.swc`  (full resolution, 57.5% of neurons)
     b. **skeletonised from the mesh** for the `_l2`-only 40.7%. Measured ~5 us/face
        (0.10-0.44 s), cheaper than the mesh fetch we already pay, and 20-27x more nodes
        than the published `_l2` (468 vs 21, 1467 vs 46, 2560 vs 95).
     c. the coarse `<root>_l2.swc`, only if skeletonisation fails.
2. Cut at the NEUROPIL boundary — brain y < 305,801 nm, vnc y > 549,946 nm. The 244 um of
   neck connective between them is dropped from both halves: registration support runs
   ~200 um past each neuropil with no anatomy to constrain it, so material there warps into
   plausible coordinates that pass a bbox check (docs/ISSUES.md IMG-3).
3. Transform with the pre-baked fields (`banc_baked`) — no elastix, no `via`/`avoid`.
4. Trim to the target template bounding box.
5. Decide: swap the new set in, delete a spurious old one, or keep what is there.
6. Decimate for the OBJ only, to hemibrain's 37 faces/um2 (docs/ISSUES.md IMG-1). The NRRD
   keeps the full-resolution mesh: it voxelises onto a ~0.5 um grid, so it neither gains from the
   fine mesh nor suffers from the coarse one.

BANC publishes only LOD 0, so there is no coarser mesh to fetch and the step-6 decimation
is ours. Neuroglancer remains the long-term answer for serving.

See docs/TRANSFORMS.md (transform paths, staging, the `use_https` trap) and docs/ISSUES.md
(IMG-1/IMG-3/IMG-4).
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
from vfb_connectomics_import.images.io import (          # noqa: E402
    PRODUCTS, TERMINAL, Ledger, OutputSet, partial_path)

BUCKET = 'lee-lab_brain-and-nerve-cord-fly-connectome'
MAT = '888'
SWC_PREFIX = f'compiled_data/banc_{MAT}/banc_banc_space_swc'
KB_ENDPOINT = os.environ.get('KB_ENDPOINT', 'http://kb.virtualflybrain.org:80')
DATASET = 'Bates2026'             # Bates2026 = BANC v888
SITE = 'BANC888'                  # the Site/Connectome node carrying v888 accessions
#: SWC files in the bucket's banc_banc_space_swc/ as of 2026-08-25 — 108,483
#: `_skeleton` + 76,797 `_l2`, mutually exclusive, one per v888 root that has one.
#: Used only to judge whether a staged mirror is complete.
EXPECTED_SWC = 185_280
VFB_URL_PREFIXES = ('http://www.virtualflybrain.org/data/',
                    'https://www.virtualflybrain.org/data/')


# ------------------------------------------------------------------------------- regions
@dataclass
class Region:
    """One template and everything that differs about it.

    `grid`/`spacing` are VFB's *display* grid, read from the template NRRD headers on the
    VFB file server — NOT flybrains' native grid (0.38 um isotropic for JRC2018U). The NRRD
    must align with the stack VFB already serves. `bounds` is `(grid - 1) * spacing`, which
    is exactly how the maleCNS script's constants (627.3695649, 293.1875965, 173) decode.

    `cut_y` is the BANC neuropil boundary in nanometres and `keep` which side to keep:
    -1 for y below it (brain, BANC_brain.ply y max), +1 for above (vnc, BANC_vnc.ply y min).
    """
    name: str
    template: str
    channel: str
    grid: Sequence[int]
    spacing: Sequence[float]
    cut_y: float
    keep: int
    bounds: list = field(init=False)

    def __post_init__(self):
        self.bounds = [[0.0, (n - 1) * s] for n, s in zip(self.grid, self.spacing)]

    def bb(self):
        return np.asarray(self.bounds, float)

    def cut_swc(self, arr):
        col_y = arr[:, 3]
        return arr[col_y < self.cut_y] if self.keep < 0 else arr[col_y > self.cut_y]

    def cut_mesh(self, mesh):
        """Open cut (cap=False) at the neuropil boundary. None if nothing remains."""
        try:
            h = mesh.slice_plane(plane_origin=np.array([0.0, self.cut_y, 0.0]),
                                 plane_normal=np.array([0.0, float(self.keep), 0.0]),
                                 cap=False)
        except BaseException:
            return None
        return h if (h is not None and len(h.faces)) else None


REGIONS = {
    'brain': Region('brain', 'JRC2018U', 'VFBc_00101567',
                    grid=(1210, 566, 174), spacing=(0.5189161, 0.5189161, 1.0),
                    cut_y=305_801.0, keep=-1),
    'vnc': Region('vnc', 'JRCVNC2018U', 'VFBc_00200000',
                  grid=(660, 1290, 382), spacing=(0.4, 0.4, 0.4),
                  cut_y=549_946.0, keep=+1),
}


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
MESH_DENSITY = 37.0          # faces per um2 of surface area; hemibrain-matched
MESH_BUDGET_MB = 4.0         # leave a mesh alone if it is already this small on the wire
OBJ_DP = 3                   # 1 nm quantisation; worst vertex moves 0.86 nm (IMG-1)


@dataclass
class Settings:
    """Everything a worker needs that does not vary per neuron.

    Passed once to the pool initializer rather than threaded through each task — the task
    is then just (root, folder, region), which is what it should have been all along.
    """
    products: Sequence[str] = ('swc', 'obj', 'nrrd')
    mode: str = 'replace'                    # 'replace' | 'fill'
    delete_spurious: bool = True
    min_nodes: int = 10
    min_faces: int = 100
    mesh_density: float = MESH_DENSITY
    mesh_budget_mb: float = MESH_BUDGET_MB
    field_dir: Optional[str] = None
    skeleton_dir: Optional[str] = None
    archive_dir: Optional[str] = None
    mmap: bool = True


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
    seq = {}
    cv = None


_W = _Worker()


def worker_init(settings):
    import navis
    import flybrains
    from vfb_connectomics_import.images import transforms as banc_baked

    flybrains.register_transforms()
    navis.set_pbars(hide=True)
    banc_baked.register(field_dir=settings.field_dir, mmap=settings.mmap,
                        verbose=False)                     # raises if absent

    _W.navis = navis
    _W.settings = settings
    _W.seq = {}
    _W.cv = None


def _seq(region):
    """TransformSequence for this region, built on first use inside this worker."""
    if region.name not in _W.seq:
        from navis.transforms.base import TransformSequence
        path, trs = _W.navis.transforms.registry.find_bridging_path('BANC', region.template)
        if any('Elastix' in type(t).__name__ for t in trs):
            raise RuntimeError(
                f'elastix is in the BANC -> {region.template} path '
                f'({" -> ".join(path)}); the baked fields are not being used. '
                f'Check $BANC_FIELD_DIR.')
        _W.seq[region.name] = TransformSequence(*trs, copy=False)
    return _W.seq[region.name]


def _cv():
    """cloudvolume handle. `use_https=True` is mandatory: without it cloudvolume falls
    through to google-cloud-python and dies with DefaultCredentialsError on any machine
    without application-default credentials — i.e. on every Jenkins agent."""
    if _W.cv is None:
        from cloudvolume import CloudVolume
        _W.cv = CloudVolume(f'precomputed://gs://{BUCKET}/neuron_meshes',
                            use_https=True, progress=False)
    return _W.cv


# ------------------------------------------------------------------------------- fetching
@dataclass
class Sources:
    """What we managed to fetch for one neuron, in BANC nanometres."""
    mesh: object = None
    swc: object = None
    swc_source: str = 'none'

    @property
    def usable(self):
        """False means we have no basis for judging this neuron — and therefore no right
        to delete anything (see decide())."""
        return self.mesh is not None or self.swc is not None


def fetch_mesh(root):
    """BANC mesh as a trimesh, in BANC nanometres. None if absent.

    Mesh coverage is incomplete upstream — 94.4% of `_skeleton` roots and 68.8% of
    `_l2`-only roots (docs/ISSUES.md IMG-4) — because bancpipeline wraps each mesh in `try()`
    and swallows failures. So a missing mesh is expected, not exceptional.
    """
    import trimesh
    try:
        m = _cv().mesh.get(int(root))
    except Exception:
        return None
    mm = m[int(root)] if isinstance(m, dict) else m
    return trimesh.Trimesh(vertices=np.asarray(mm.vertices, np.float64),
                           faces=np.asarray(mm.faces, np.int64), process=False)


def fetch_published_swc(root, suffix):
    """`<root>_{skeleton,l2}.swc` from the staged local dir, else the bucket. None if absent."""
    name = f'{root}_{suffix}.swc'
    d = _W.settings.skeleton_dir
    if d:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            return None          # a staged dir is authoritative: it is a full mirror
        with open(p) as fh:
            return np.loadtxt(io.StringIO(fh.read()), comments='#', ndmin=2)
    try:
        raw = urllib.request.urlopen(
            f'https://storage.googleapis.com/{BUCKET}/{SWC_PREFIX}/{name}',
            timeout=300).read().decode()
    except Exception:
        return None
    return np.loadtxt(io.StringIO(raw), comments='#', ndmin=2)


def as_mesh_neuron(tm, name):
    """MeshNeuron with units set. This matters: a MeshNeuron built from a bare trimesh is
    dimensionless, and navis.voxelize then cannot parse a pitch in microns."""
    mn = _W.navis.MeshNeuron(tm, units='microns')
    mn.id = mn.name = str(name)
    return mn


def skeleton_from_mesh(root, mesh):
    """Skeletonise the mesh into an SWC array, or None. This is what upstream did to make
    the published `_skeleton` files (skeletor), so it is the same operation rather than a
    substitute — and it beats the 125x-coarser published `_l2`."""
    if mesh is None or not len(mesh.faces):
        return None
    try:
        n = _W.navis.skeletonize(as_mesh_neuron(mesh, root)).nodes
    except Exception:
        return None
    arr = np.column_stack([
        n.node_id.values, np.zeros(len(n)),
        n.x.values, n.y.values, n.z.values,
        n.radius.values if 'radius' in n else np.zeros(len(n)),
        n.parent_id.values])
    return arr if len(arr) > 1 else None


def load_sources(root):
    """Mesh + best available skeleton, in preference order (see the module docstring)."""
    mesh = fetch_mesh(root)
    for arr, label in ((fetch_published_swc(root, 'skeleton'), 'published_skeleton'),
                       (skeleton_from_mesh(root, mesh), 'skeletonised_mesh'),
                       (fetch_published_swc(root, 'l2'), 'published_l2')):
        if arr is not None and len(arr) > 1:
            return Sources(mesh=mesh, swc=arr, swc_source=label)
    return Sources(mesh=mesh, swc=None, swc_source='none')


# ----------------------------------------------------------------------- transform + trim
def _inside(pts, bb):
    return ~np.isnan(pts).any(1) & ~((pts < bb[:, 0]) | (pts > bb[:, 1])).any(1)


def xform(pts, region):
    return np.asarray(_seq(region).xform(np.asarray(pts, float).copy()), float)


def transform_swc(arr, region):
    """Cut, transform and trim an SWC array. Microns out, radius in microns. None if empty."""
    if arr is None:
        return None
    arr = region.cut_swc(arr)
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
    mesh = region.cut_mesh(mesh)
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
    return Halves(swc=transform_swc(sources.swc, region),
                  mesh=transform_mesh(sources.mesh, region))


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


def clip_into(obj, region):
    """Clamp coordinates into the voxel grid so voxelize can never see an out-of-range
    point. The trim uses the same bounds, so this only ever moves a point by
    floating-point noise."""
    bb = region.bb()
    if hasattr(obj, 'vertices'):
        obj.vertices = np.clip(np.asarray(obj.vertices), bb[:, 0], bb[:, 1])
    return obj


def write_nrrd(obj, region, path):
    """Voxelise onto VFB's display grid and write a gzipped uint8 NRRD.

    Memory: the brain grid is 1210 x 566 x 174 = 119 M voxels, so ~119 MB as bool plus
    ~119 MB as uint8 — roughly 250-350 MB peak per worker, and the single largest
    allocation in this loader. Size worker count against that, not against the meshes.
    """
    vx = _W.navis.voxelize(obj, pitch=[f'{s} microns' for s in region.spacing],
                           bounds=region.bounds, parallel=False)
    vx.grid = vx.grid.astype('uint8') * 255
    _W.navis.write_nrrd(vx, filepath=path, compression_level=9)
    del vx


def _surface_area(mesh):
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    return float(np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]],
                                         v[f[:, 2]] - v[f[:, 0]]), axis=1).sum() / 2)


def decimate_mesh(mesh, density=MESH_DENSITY, budget_mb=MESH_BUDGET_MB):
    """Quadric-decimate to `density` faces/um2. Returns (mesh, note).

    Skipped when the mesh is already at or below the target density, and when it is small
    enough that reducing it buys nothing -- most BANC neurons are a few MB and there is no
    reason to spend fidelity on them. Wire size is estimated at ~9 bytes/face, which is
    what 3 dp OBJ gzips to across every mesh measured.
    """
    import trimesh
    if not density or density <= 0:
        return mesh, 'decimation disabled'
    n = len(mesh.faces)
    if n < 1000:
        return mesh, 'too small to decimate'
    if n * 9 / 1e6 <= budget_mb:
        return mesh, f'{n * 9 / 1e6:.2f} MB est <= {budget_mb} MB budget'
    area = _surface_area(mesh)
    target = int(density * area)
    if target >= 0.95 * n:                 # already at the target; not worth a rewrite
        return mesh, f'already {n / area:.0f} f/um2 <= {density:.0f}'
    import fast_simplification
    v, f = fast_simplification.simplify(np.asarray(mesh.vertices, np.float32),
                                        np.asarray(mesh.faces, np.int32),
                                        target_reduction=1 - target / n)
    out = trimesh.Trimesh(vertices=np.asarray(v, float), faces=np.asarray(f, int),
                          process=False)
    return out, f'{n:,} -> {len(out.faces):,} faces ({n / area:.0f} -> {density:.0f} f/um2)'


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
        mesh_neuron = as_mesh_neuron(clip_into(halves.mesh, region), root)
        if 'obj' in out.products:
            dec, note = decimate_mesh(halves.mesh, st.mesh_density, st.mesh_budget_mb)
            rec['obj_faces'], rec['obj_note'] = len(dec.faces), note
            tmp = partial_path(out.paths['obj'])
            write_obj(dec, tmp)
            built[tmp] = out.paths['obj']
            del dec

    if 'nrrd' in out.products:
        # Prefer the mesh for NRRD detail, fall back to the skeleton — same preference
        # order as the maleCNS loader this replaces.
        src = mesh_neuron
        if src is None and halves.swc is not None:
            src = clip_into(to_tree_neuron(halves.swc, str(root)), region)
        if src is not None:
            tmp = partial_path(out.paths['nrrd'])
            write_nrrd(src, region, tmp)
            built[tmp] = out.paths['nrrd']
    return built


# ------------------------------------------------------------------------------ per neuron
def process(task):
    """One neuron, one region. Never raises: failures come back as status='error'."""
    root, folder, region_name = task
    region, st = REGIONS[region_name], _W.settings
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
        rec['nodes'], rec['faces'] = halves.nodes, halves.faces
        del sources.mesh                     # the big allocation; drop it early

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
                            'note', 'old_files', 'new_files', 'had_existing', 'seconds')},
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


def kb_worklist(region_name, dataset, site=SITE, endpoint=KB_ENDPOINT):
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
    rows = kb_query(
        f"MATCH (d:DataSet {{short_form:'{dataset}'}})<-[:has_source]-(i:Individual)"
        f"<-[:depicts]-(ic:Individual)-[r:in_register_with]"
        f"->(tc:Template {{short_form:'{REGIONS[region_name].channel}'}}) "
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
        rows = kb_worklist(name, args.dataset, site=args.site)
        print(f'{name}: {len(rows):,} channels in {args.dataset}', flush=True)
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
        missing = wanted - {t[0] for t in tasks}
        print(f'--roots: {len(tasks):,} of {len(wanted):,} requested roots are in this '
              f'selection' + (f'; not found: {sorted(missing)[:5]}' if missing else ''))
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
    ap.add_argument('--ledger', default=os.environ.get('BANC_LEDGER'),
                    help='append-only JSONL of finished neurons. REQUIRED for a meaningful '
                         'resume in replace mode: existing files cannot indicate progress '
                         'because almost every neuron already has them. Errors are retried.')
    ap.add_argument('--workers', type=int, default=8,
                    help='processes; ~350 MB peak each from voxelisation (default 8)')
    ap.add_argument('--field-dir', default=None,
                    help='baked fields; default $BANC_FIELD_DIR (see docs/TRANSFORMS.md)')
    ap.add_argument('--skeleton-dir', default=os.environ.get('BANC_SWC_DIR'),
                    help='local mirror of banc_banc_space_swc/ — strongly recommended, it '
                         'removes ~0.5 s of per-neuron request latency')
    ap.add_argument('--write-root', default=os.environ.get('IMAGE_WRITE', '/IMAGE_WRITE/'),
                    help='local path that replaces the VFB data URL prefix')
    ap.add_argument('--dataset', default=DATASET, help=f'VFB DataSet (default {DATASET})')
    ap.add_argument('--site', default=SITE,
                    help=f'Site node whose accession is the root id (default {SITE})')
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
                    help='decimate the OBJ to this many faces per um2 of surface area '
                         '(default 37, the hemibrain density that displays acceptably). '
                         '0 disables decimation.')
    ap.add_argument('--mesh-budget-mb', type=float, default=MESH_BUDGET_MB,
                    help='leave a mesh undecimated if its estimated gzipped size is '
                         'already under this (default 4 MB)')
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


#: region -> the H5 bridging registration its tail hop needs, and the flybrains downloader
#: that fetches it. The BANC -> JRC2018F/JRCVNC2018F hop is our baked field; this is the
#: JRC2018F -> JRC2018U (or VNC equivalent) hop, which stays a live H5 read.
H5_DEPS = {
    'brain': ('JRC2018U_JRC2018F.h5', 'download_jrc_transforms'),
    'vnc': ('JRCVNC2018U_JRCVNC2018F.h5', 'download_jrc_vnc_transforms'),
}


def ensure_h5(regions, download=True):
    """Make sure the tail-hop H5 files are on this machine.

    The old maleCNS job called `download_jrc_transforms()` / `download_jrc_vnc_transforms()`
    unconditionally at startup; without something equivalent a fresh agent with an empty
    `$FLYBRAINS_DATA` fails on the first neuron instead of at preflight. Only the regions
    actually being processed are fetched: a brain-only run has no need for the VNC set,
    which includes a 1 GB `JRCVNC2018M_MANC.h5` we never touch.
    """
    import flybrains
    from flybrains.download import get_data_home
    home = get_data_home()
    for region in regions:
        fname, fn = H5_DEPS[region]
        path = os.path.join(home, fname)
        if os.path.exists(path):
            print(f'h5 for {region}: {path} ({os.path.getsize(path) / 1e6:.0f} MB)')
            continue
        if not download:
            raise SystemExit(
                f'{fname} not found in {home} and --no-download was given. The '
                f'{region} tail hop cannot run. Fetch it with '
                f'flybrains.{fn}() or set $FLYBRAINS_DATA.')
        print(f'h5 for {region}: {fname} absent — downloading via flybrains.{fn}()',
              flush=True)
        getattr(flybrains, fn)()
        if not os.path.exists(path):
            raise SystemExit(f'flybrains.{fn}() ran but {path} is still missing')


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
    from vfb_connectomics_import.images import transforms as banc_baked
    navis.set_pbars(hide=True)

    # 1. Cheapest check first. Locating our own fields is an instant stat; the H5 step
    #    below may download 717 MB. Checking in the other order meant a misconfigured
    #    agent paid for the download and *then* failed.
    d, how = banc_baked.resolve_field_dir(args.field_dir)
    print(f'baked fields: {d}  (chosen by {how})', flush=True)
    absent = banc_baked.missing_fields(args.field_dir)
    if absent:
        raise banc_baked._missing_error(args.field_dir)

    # 2. Now the possibly-expensive one. flybrains only registers an H5 edge for a file
    #    that exists, so register_transforms() has to run AFTER any download or the
    #    path assertion in step 3 would find no route at all.
    ensure_h5(regions, download=not args.no_download)
    flybrains.register_transforms()

    # 3. Full check: fields load, reject out-of-domain, and elastix is out of the path.
    banc_baked.register(field_dir=args.field_dir, mmap=not args.no_mmap,
                        verbose=True)
    banc_baked.self_check(field_dir=args.field_dir, verbose=True)

    if args.skeleton_dir and os.path.isdir(args.skeleton_dir):
        n = len([f for f in os.listdir(args.skeleton_dir) if f.endswith('.swc')])
        pct = 100.0 * n / EXPECTED_SWC
        print(f'staged skeletons: {args.skeleton_dir} ({n:,} files, '
              f'{pct:.1f}% of the expected {EXPECTED_SWC:,})')
        if n < 0.95 * EXPECTED_SWC:
            # A staged dir is authoritative — a miss does NOT fall back to the bucket, it
            # falls through to skeletonising the mesh. So a half-finished rsync silently
            # downgrades published skeletons instead of failing, which is worth shouting
            # about rather than printing a number nobody reads.
            print(f'  *** WARNING: the mirror looks INCOMPLETE ({EXPECTED_SWC - n:,} '
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
        bits.append(f'{rec["nodes"]}n/{rec["faces"]}f')
    detail = (' '.join(bits) or rec['note'])[:34]
    return (f'  {rec["status"]:16s} {rec["root"]:20s} {rec["region"]:5s} '
            f'{rec["seconds"]:5.1f}s  {detail:34s} '
            f'{to_url(rec["folder"], write_root)}')


def report_progress(i, total, t0, counts):
    el = time.time() - t0
    rate, left = el / i, total - i
    eta = left * rate
    print(f'  [{i:,}/{total:,}  {100.0 * i / total:5.1f}%]  {left:,} left  '
          f'{rate:.2f} s/neuron  elapsed {el / 60:.1f}m  ETA {eta / 60:.0f}m '
          f'(~{time.strftime("%H:%M", time.localtime(time.time() + eta))})  '
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
        products=products, mode=args.mode,
        delete_spurious=not args.no_delete_spurious,
        min_nodes=args.min_nodes, min_faces=args.min_faces,
        mesh_density=args.mesh_density, mesh_budget_mb=args.mesh_budget_mb,
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
