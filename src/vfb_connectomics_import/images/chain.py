"""Build a TransformSequence from a Region's DECLARED hops. No path search, ever.

`navis.transforms.registry.find_bridging_path` picks a route by Dijkstra over a graph that
every registered dataset mutates, so "the" path between two spaces depends on what else is
installed in the process. `images/connectomes.py` explains why that is unsafe here; this
module is the mechanism that avoids it.

Each hop is resolved as a **single named edge** of a declared transform type — a dict
lookup on the registry's MultiDiGraph — so:

* a route cannot silently change when flybrains adds a dataset (CODE-1, CODE-4);
* baked fields need not be registered as graph edges at all, so consuming them no longer
  perturbs routing for other datasets sharing the process;
* `weight=` stops being load-bearing.

Verified 2026-08-28 on the maleCNS brain chain: edge lookup and path search produce
bit-identical output (max |diff| = 0.0 over 4,388 nodes) when the search happens to pick
the intended route.

Direction is navis's job, not ours. The file is `JRC2018U_JRC2018M.h5` but the graph holds
the reverse edge too, so `edge('JRC2018M', 'JRC2018U', 'H5transform')` returns an inverted
transform ready to use. Hand-rolling H5 direction would be a real footgun.
"""
import os

import numpy as np


class ChainError(RuntimeError):
    """A declared hop could not be resolved, or resolved to the wrong thing."""


def _graph():
    import navis
    return navis.transforms.registry.bridging_graph()


def edge(source, target, expect=None, graph=None):
    """The single registry edge `source -> target`, chosen by transform type.

    `expect` matters because the registry is a MultiDiGraph: some space pairs carry
    parallel edges (`JRCFIB2022M -> JRCFIB2022Mnm` has two AliasTransforms). Naming the
    type makes the pick deterministic AND turns a flybrains upgrade that retypes an edge
    into a loud failure instead of a silent substitution.
    """
    g = graph if graph is not None else _graph()
    data = g.get_edge_data(source, target)
    if not data:
        raise ChainError(
            f'no registry edge {source!r} -> {target!r}. Either flybrains is not '
            f'registered (call flybrains.register_transforms() first), the registration '
            f'file it needs is not downloaded, or the space names have changed upstream.')
    found = [d['transform'] for d in data.values()]
    if expect is None:
        if len(found) > 1:
            raise ChainError(
                f'{source!r} -> {target!r} has {len(found)} parallel edges '
                f'({sorted({type(t).__name__ for t in found})}); declare `expect` to '
                f'choose one.')
        return found[0]
    match = [t for t in found if type(t).__name__ == expect]
    if not match:
        raise ChainError(
            f'{source!r} -> {target!r} exists but no edge is a {expect}; found '
            f'{sorted({type(t).__name__ for t in found})}. flybrains has changed this '
            f'registration — do not "fix" this by relaxing the type until you know what '
            f'the new edge is and where it came from.')
    if len(match) > 1:
        raise ChainError(f'{source!r} -> {target!r} has {len(match)} parallel {expect} '
                         f'edges; cannot choose deterministically.')
    return match[0]


def _baked(stem, hop, field_dir, mmap=True):
    from vfb_connectomics_import.images.transforms import BakedField, resolve_field_dir
    d, how = resolve_field_dir(field_dir)
    path = os.path.join(d, stem + '.npy')
    if not os.path.exists(path):
        raise ChainError(
            f'baked field {stem!r} not found.\n  looked in : {d}\n  chosen by : {how}\n'
            f'  missing   : {path}\n  fix       : set $BANC_FIELD_DIR, or build it with '
            f'`python -m vfb_connectomics_import.images.bake_fields`.')
    bf = BakedField(path, mmap=mmap)
    if bf.target != hop.target:
        raise ChainError(
            f'{path}: sidecar says target={bf.target!r} but it is declared as the hop '
            f'{hop.source} -> {hop.target}. The fields have probably been swapped or '
            f'rebuilt against the wrong target.')
    src = bf.meta.get('source')
    if src and src != hop.source:
        raise ChainError(f'{path}: sidecar says source={src!r}, declared {hop.source!r}.')
    return bf


def resolve(region, field_dir=None, mmap=True, use_baked=True, verbose=False):
    """(TransformSequence, [description]) for a Region's chain."""
    from navis.transforms.base import TransformSequence
    from navis.transforms import FunctionTransform
    g = _graph()
    trs, described = [], []
    for hop in region.hops(use_baked=use_baked):
        if hop.baked:
            bf = _baked(hop.baked, hop, field_dir, mmap=mmap)
            trs.append(FunctionTransform(bf))
            described.append(f'{hop.source} -> {hop.target}  baked {os.path.basename(bf.path)}')
        else:
            t = edge(hop.source, hop.target, hop.expect, graph=g)
            trs.append(t)
            described.append(f'{hop.source} -> {hop.target}  {type(t).__name__}')
    if verbose:
        for line in described:
            print(f'    {line}')
    return TransformSequence(*trs, copy=False), described


def xform(seq, pts, affine_fallback=False):
    """Run a sequence. `affine_fallback=False` on purpose — see bake_fields.py."""
    pts = np.asarray(pts, float)
    if not len(pts):
        return pts
    return np.asarray(seq.xform(pts.copy(), affine_fallback=affine_fallback), float)
