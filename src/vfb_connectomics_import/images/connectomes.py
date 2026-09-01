"""Per-connectome image-build registry: identity, regions, cut planes and transform chains.

This is the "you cannot just run a new connectome" file. Adding a dataset means working
out four things that nothing can infer for you — which templates it writes to, where its
brain/VNC cut plane sits *in its own source space*, which exact transform hops reach each
template, and where its geometry lives — and this module is where those answers are
recorded once, with their provenance, instead of being spread across module constants in
`loader.py`, `FIELDS` in `transforms.py` and `connectomes.yaml` in the dashboard.

Why the chain is declared rather than searched
----------------------------------------------
`navis.transforms.registry.find_bridging_path` runs Dijkstra over a graph that every
registered dataset mutates, so the route between two spaces is a function of what else is
installed. That is not a theoretical worry:

* `JRCFIB2022M -> JRCVNC2018U` unrouted resolves *today* to
  `JRCFIB2022M -> BANC -> BANCum -> JRCVNC2018F -> JRCVNC2018U` — a male CNS pushed
  through a female CNS into the female VNC template. Nothing errors (docs/ISSUES.md CODE-1).
* Registering the baked BANC fields at `weight=0.1` makes BANC-routed paths cheaper for
  *every other* dataset in the process, so it breaks maleCNS **brain** too.
* `via=`/`avoid=` do not fix it: they abandon the weighted search entirely and return the
  first DFS match, which is how the two `via=` calls elsewhere in this repo resolve to
  16- and 19-hop routes (docs/ISSUES.md CODE-4).

So a `Region` names its hops. Each hop is resolved as a **single named edge** of a declared
transform type — a dictionary lookup on the registry graph, not a path search — and a
missing or retyped edge is an immediate loud failure rather than a silent reroute. Verified
2026-08-28: edge lookup and path search give bit-identical output (max |diff| = 0.0 over
4,388 nodes) when the path search happens to pick the right route.

The other consequence is that `transforms.register()` becomes an interactive convenience
only. Loaders never need the baked fields in the global graph, so they no longer perturb
routing for anything else sharing the process.
"""
from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

import numpy as np


# ------------------------------------------------------------------------------ templates
@dataclass(frozen=True)
class Template:
    """A VFB template channel and the display grid images must land on.

    `grid`/`spacing` are VFB's *display* grid, read from the template NRRD headers on the
    VFB file server — NOT flybrains' native grid (0.38 um isotropic for JRC2018U). The
    NRRD must align with the stack VFB already serves. These belong to the template, not
    to any one connectome: every EM dataset writes to the same two, so they are defined
    once here rather than copied into each connectome and left to drift.
    """
    name: str
    channel: str
    grid: Sequence[int]
    spacing: Sequence[float]

    @property
    def bounds(self):
        return [[0.0, (n - 1) * s] for n, s in zip(self.grid, self.spacing)]

    def bb(self):
        return np.asarray(self.bounds, float)


TEMPLATES = {
    'JRC2018U': Template('JRC2018U', 'VFBc_00101567',
                         grid=(1210, 566, 174), spacing=(0.5189161, 0.5189161, 1.0)),
    'JRCVNC2018U': Template('JRCVNC2018U', 'VFBc_00200000',
                            grid=(660, 1290, 382), spacing=(0.4, 0.4, 0.4)),
}


# ----------------------------------------------------------------------------- cut planes
@dataclass(frozen=True)
class Cut:
    """One plane in SOURCE space, and which side of it this region keeps.

    Cutting in source space is mandatory and cannot be replaced by the target-template
    bbox trim that follows it: registration support runs well past each neuropil with no
    anatomy to constrain it, so material in the gap warps into plausible coordinates that
    *pass* a bbox check. Measured on BANC: 42/420 brain fragments leaked into the VNC
    bbox, versus 0/378 the other way (docs/ISSUES.md IMG-3). Support is not validity.

    `axis` is the index into (x, y, z) — BANC separates on y, maleCNS on z. `keep` is -1
    to keep coordinates below `at` and +1 to keep those above. `derived_from` records how
    the number was obtained, because that is the expensive part to reconstruct.
    """
    axis: int
    at: float
    keep: int
    derived_from: str

    def mask(self, xyz):
        """Boolean keep-mask for an (n, 3) array of SOURCE-space coordinates."""
        col = np.asarray(xyz, float)[:, self.axis]
        return col < self.at if self.keep < 0 else col > self.at


# ---------------------------------------------------------------------- transform chains
@dataclass(frozen=True)
class Hop:
    """One leg of a transform chain.

    Either a **native** edge — resolved from the navis registry as the single edge
    `source -> target` whose transform is of type `expect` — or a **baked** field of ours,
    which may span several native edges at once (BANC's covers `BANC -> BANCum ->
    JRC2018F`, which was never a single edge).

    `expect` is not decoration. The registry is a MultiDiGraph and some space pairs carry
    parallel edges, so the type is what makes the pick deterministic; and asserting it
    turns the next flybrains upgrade from a silent reroute into a failed preflight.
    """
    source: str
    target: str
    expect: Optional[str] = None
    baked: Optional[str] = None

    def __str__(self):
        what = f'baked:{self.baked}' if self.baked else self.expect
        return f'{self.source} -> {self.target} [{what}]'


@dataclass(frozen=True)
class Bake:
    """A baked field: which span of the native chain it replaces, and at what spacing.

    `stem` is the `.npy`/`.json` basename. `frm`/`to` are the spaces it maps between —
    `to` is asserted against the sidecar so a field can never be silently consumed as the
    wrong leg. `step_nm` is the grid spacing in source units.
    """
    stem: str
    frm: str
    to: str
    step_nm: float = 2000.0


@dataclass(frozen=True)
class Region:
    """One template's worth of a connectome: what to cut, and how to get there.

    `native` is the full binary-and-H5 chain as flybrains supplies it — the thing the bake
    samples, and the reference the baked field is validated against. `bake`, when set, is
    what production actually uses.
    """
    name: str
    template: Template
    cut: Cut
    native: Tuple[Hop, ...]
    bake: Optional[Bake] = None
    #: anatomical extent of THIS region in source units, before margin: ((lo3), (hi3)).
    #: Sizes the baked grid. Taken from published compartment/neuropil surfaces, so it is
    #: anatomy rather than a guess at where the registration happens to be defined.
    extent: Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = None
    extent_from: str = ''

    def hops(self, use_baked=True):
        """The chain to actually run, with the baked span collapsed to one hop."""
        if not (use_baked and self.bake):
            return self.native
        b = self.bake
        tail = []
        seen_end = False
        for h in self.native:
            if h.source == b.to:
                seen_end = True
            if seen_end:
                tail.append(h)
        if self.native[0].source != b.frm:
            raise ValueError(f'{self.name}: bake starts at {b.frm!r} but the native chain '
                             f'starts at {self.native[0].source!r}')
        if not seen_end and self.native[-1].target != b.to:
            raise ValueError(f'{self.name}: bake ends at {b.to!r}, which is not a space in '
                             f'the native chain')
        return (Hop(b.frm, b.to, baked=b.stem),) + tuple(tail)

    def bb(self):
        return self.template.bb()


# ------------------------------------------------------------------------------ datasets
@dataclass(frozen=True)
class Connectome:
    """One EM dataset as the image job sees it."""
    id: str
    label: str
    dataset: str                 # VFB DataSet short_form
    site: str                    # VFB Site short_form; its xref accession is the neuron id
    space: str                   # navis/flybrains space the geometry is fetched in
    units: str                   # units of that space
    regions: dict
    #: full source volume bounds in `units`, used to clamp a baked grid to real data
    volume: Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = None
    notes: str = ''

    def region(self, name):
        try:
            return self.regions[name]
        except KeyError:
            raise SystemExit(f'{self.id}: unknown region {name!r}; '
                             f'have {sorted(self.regions)}')


# --------------------------------------------------------------------------------- BANC
# Cut provenance: flybrains ships BANC_brain.ply and BANC_vnc.ply in BANC nanometres,
# disjoint in y with a 244 um gap that is the neck connective. An earlier version cut at
# BANC's own neck_connective_y92500 annotation (y = 370,000); that was wrong, because
# registration support extends ~200 um past each neuropil (brain y 36-540 um, vnc
# y 340-1132 um) and material in the overlap warps into coordinates that pass a bbox
# check. See docs/ISSUES.md IMG-3.
BANC = Connectome(
    id='banc', label='BANC v888',
    dataset='Bates2026', site='BANC888',
    space='BANC', units='nm',
    volume=((79342., 35563., 43.), (966128., 1131156., 315520.)),   # flybrains.BANC.boundingbox
    regions={
        'brain': Region(
            name='brain', template=TEMPLATES['JRC2018U'],
            cut=Cut(axis=1, at=305_801.0, keep=-1,
                    derived_from='BANC_brain.ply y max (flybrains bundled mesh)'),
            native=(Hop('BANC', 'BANCum', 'AffineTransform'),
                    Hop('BANCum', 'JRC2018F', 'ElastixTransform'),
                    Hop('JRC2018F', 'JRC2018U', 'H5transform')),
            bake=Bake('banc_brain_2um', frm='BANC', to='JRC2018F')),
        'vnc': Region(
            name='vnc', template=TEMPLATES['JRCVNC2018U'],
            cut=Cut(axis=1, at=549_946.0, keep=+1,
                    derived_from='BANC_vnc.ply y min (flybrains bundled mesh)'),
            native=(Hop('BANC', 'BANCum', 'AffineTransform'),
                    Hop('BANCum', 'JRCVNC2018F', 'ElastixTransform'),
                    Hop('JRCVNC2018F', 'JRCVNC2018U', 'H5transform')),
            bake=Bake('banc_vnc_2um', frm='BANC', to='JRCVNC2018F')),
    },
    notes='Baked to the F templates only; the JRC tail hop stays live. Do not re-bake '
          'while a production run is in flight.')


# ------------------------------------------------------------------------------- maleCNS
# Cut provenance, established 2026-08-28. gs://flyem-male-cns/rois/malecns-major-
# compartments-v2/mesh/ publishes five labelled compartment meshes in maleCNS nanometres —
# CentralBrain, Optic(L), Optic(R), CV, VNC — where CV is the cervical connective. Their
# z extents (nm):
#     CentralBrain    63,489 ..  415,232
#     Optic(L)       123,454 ..  349,184
#     Optic(R)       157,898 ..  355,841
#     CV             348,672 ..  481,792
#     VNC            481,792 .. 1,077,248
# Independently, over all 139 neuprint super-level ROI meshes, the caudal-most brain
# neuropil is ME(R) at z 340,544 and the rostral-most VNC neuropil is LegNp(T1)(L) at
# z 527,616. Cutting at the NEUROPIL bounds drops 187.1 um and strictly contains FlyEM's
# own CV label on both sides, which is the same relationship BANC's 244 um gap has to its
# neck connective — so this follows the IMG-3 rule rather than reinventing one.
MALECNS = Connectome(
    id='malecns', label='male-CNS v1.0',
    dataset='Berg2025a', site='male-cns_v1_0',
    space='JRCFIB2022M', units='nm',
    volume=((0., 0., 0.), (752_704., 626_536., 1_076_608.)),        # 94088x78317x134576 @ 8 nm
    regions={
        'brain': Region(
            name='brain', template=TEMPLATES['JRC2018U'],
            cut=Cut(axis=2, at=340_544.0, keep=-1,
                    derived_from='max z of brain neuropil ROIs, ME(R) (neuprint male-cns:v1.0 '
                                 'ROI meshes); inside FlyEM CV min 348,672'),
            native=(Hop('JRCFIB2022M', 'JRCFIB2022Mum', 'AffineTransform'),
                    Hop('JRCFIB2022Mum', 'JRC2018M', 'H5transform'),
                    Hop('JRC2018M', 'JRC2018U', 'H5transform')),
            bake=Bake('malecns_brain_2um', frm='JRCFIB2022M', to='JRC2018U'),
            extent=((17_920., 36_866., 63_489.), (751_104., 433_150., 340_544.)),
            extent_from='CentralBrain + Optic(L) + Optic(R) compartment meshes, z capped '
                        'at the cut plane'),
        'vnc': Region(
            name='vnc', template=TEMPLATES['JRCVNC2018U'],
            cut=Cut(axis=2, at=527_616.0, keep=+1,
                    derived_from='min z of VNC neuropil ROIs, LegNp(T1)(L) (neuprint '
                                 'male-cns:v1.0 ROI meshes); inside FlyEM CV max 481,792'),
            # Two CMTK hops via an intermediate "(post)" node — these shell out to
            # streamxform, which is why this half must be baked (cf. BANC's elastix).
            native=(Hop('JRCFIB2022M', 'JRCFIB2022Mum', 'AffineTransform'),
                    Hop('JRCFIB2022Mum', 'MANCum-JRCFIB2022Mum(post)', 'CMTKtransform'),
                    Hop('MANCum-JRCFIB2022Mum(post)', 'MANCum', 'CMTKtransform'),
                    Hop('MANCum', 'JRCVNC2018M', 'H5transform'),
                    Hop('JRCVNC2018M', 'JRCVNC2018U', 'H5transform')),
            bake=Bake('malecns_vnc_2um', frm='JRCFIB2022M', to='JRCVNC2018U'),
            extent=((237_093., 307_318., 527_616.), (552_812., 577_751., 1_077_248.)),
            extent_from='VNC compartment mesh, z floored at the cut plane'),
    },
    notes='Baked all the way to the U templates: unlike BANC the tail hops are NOT cheap '
          '(~0.4-1.0 s FIXED per neuron per H5 hop, which does not amortise), and baking '
          'through removes 4.4 GB of H5 plus the CMTK binary from the agent entirely.')


CONNECTOMES = {c.id: c for c in (BANC, MALECNS)}


def get(cid):
    try:
        return CONNECTOMES[cid]
    except KeyError:
        raise SystemExit(f'unknown connectome {cid!r}; have {sorted(CONNECTOMES)}')
