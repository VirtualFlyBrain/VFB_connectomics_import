#!/usr/bin/env python
"""Build the baked BANC->template deformation fields consumed by `banc_baked.py`.

Run once. Needs `transformix` on PATH (see below) and ~15 GB of free RAM at peak.
Takes ~30 min: 3.4 min for the brain field, ~28 min for the VNC one.

    export PATH="$HOME/opt/elastix/bin:$PATH"
    export DYLD_LIBRARY_PATH="$HOME/opt/elastix/lib:$DYLD_LIBRARY_PATH"   # Linux: LD_LIBRARY_PATH
    python bake_banc_fields.py [--out DIR] [--step-nm 2000]

What it does
------------
1. Probes where each BANC registration actually has support, by detecting elastix's
   identity fallback (a point outside the B-spline valid region comes back unchanged).
2. Sizes each field's grid to that support plus a margin.
3. Samples the elastix hop onto the grid and writes `.npy` + a sidecar `.json`.

Only the elastix hop is baked (BANC -> JRC2018F / JRCVNC2018F). The downstream H5 hops are
already dense fields distributed by the Saalfeld lab and stay as navis transforms.

`.npy` rather than `.npz` so it can be memory-mapped; the sidecar json carries `lo`/`step`
so the grid can never be orphaned from its array.
"""
import argparse
import json
import os
import time

import numpy as np
import navis
import flybrains
from navis.transforms.base import TransformSequence

# whole-BANC bounding box, nanometres (flybrains.BANC.boundingbox)
BANC_LO = np.array([79342., 35563., 43.])
BANC_HI = np.array([966128., 1131156., 315520.])
PROBE_STEP = 4000.
MARGIN = 20_000.

TARGETS = (('brain', 'JRC2018F'), ('vnc', 'JRCVNC2018F'))


def _seq(target):
    path, trs = navis.transforms.registry.find_bridging_path('BANC', target)
    return path, TransformSequence(*trs, copy=False), TransformSequence(*trs[:1], copy=False)


def support_band(target, verbose=True):
    """Where does this registration have real (non-identity) support? BANC nm."""
    gx = [np.arange(BANC_LO[i], BANC_HI[i] + PROBE_STEP, PROBE_STEP) for i in range(3)]
    grid = np.stack(np.meshgrid(*gx, indexing='ij'), -1).reshape(-1, 3)
    path, seq, pre = _seq(target)
    if verbose:
        print(f'  {target}: {" -> ".join(path)}  probing {len(grid)/1e6:.2f}M nodes',
              flush=True)
    t0 = time.time()
    um = pre.xform(grid)          # BANC nm -> BANCum, so identity is detectable
    out = seq.xform(grid)
    ident = np.linalg.norm(out - um, axis=1) < 1e-3
    ok = ~ident & ~np.isnan(out).any(axis=1)
    sup = grid[ok]
    band = dict(y_lo=float(sup[:, 1].min()), y_hi=float(sup[:, 1].max()),
                x_lo=float(sup[:, 0].min()), x_hi=float(sup[:, 0].max()),
                z_lo=float(sup[:, 2].min()), z_hi=float(sup[:, 2].max()),
                in_domain_frac=float(ok.mean()), probe_seconds=round(time.time() - t0, 1))
    if verbose:
        print(f'    in-domain {100*ok.mean():.1f}%   supported y '
              f'{band["y_lo"]/1000:.0f}..{band["y_hi"]/1000:.0f} um', flush=True)
    return band


def bake(target, lo, hi, step, out_dir, stem, verbose=True):
    gx = [np.arange(lo[i], hi[i] + step, step) for i in range(3)]
    shape = tuple(len(g) for g in gx)
    grid = np.stack(np.meshgrid(*gx, indexing='ij'), -1).reshape(-1, 3)
    _, seq, _ = _seq(target)
    if verbose:
        print(f'  baking {stem}: grid {shape} = {len(grid)/1e6:.2f}M nodes '
              f'({np.prod(shape)*12/1e6:.0f} MB)', flush=True)
    t0 = time.time()
    field = seq.xform(grid).reshape(*shape, 3).astype(np.float32)
    dt = time.time() - t0
    os.makedirs(out_dir, exist_ok=True)
    npy = os.path.join(out_dir, stem + '.npy')
    np.save(npy, field)
    json.dump(dict(lo=list(map(float, lo)), step=[float(step)] * 3, target=target,
                   shape=list(field.shape), dtype=str(field.dtype), banc_space='nm',
                   built=time.strftime('%Y-%m-%d'), build_seconds=round(dt, 1),
                   note='elastix hop only; compose with the JRC H5 transforms downstream'),
              open(os.path.splitext(npy)[0] + '.json', 'w'), indent=1)
    if verbose:
        print(f'    {dt/60:.1f} min -> {npy} ({os.path.getsize(npy)/1e6:.0f} MB)',
              flush=True)
    return npy


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.environ.get(
        'BANC_FIELD_DIR', os.path.expanduser('~/Documents/banc_transform_fields')))
    ap.add_argument('--step-nm', type=float, default=2000.,
                    help='grid spacing in BANC nm (default 2000 = 2 um)')
    args = ap.parse_args()

    flybrains.register_transforms()
    navis.set_pbars(hide=True)

    print('1. probing registration support', flush=True)
    bands = {tag: support_band(tgt) for tag, tgt in TARGETS}

    print('\n2. baking', flush=True)
    for tag, tgt in TARGETS:
        b = bands[tag]
        lo = np.maximum(BANC_LO, [b['x_lo'] - MARGIN, b['y_lo'] - MARGIN, b['z_lo'] - MARGIN])
        hi = np.minimum(BANC_HI, [b['x_hi'] + MARGIN, b['y_hi'] + MARGIN, b['z_hi'] + MARGIN])
        bake(tgt, lo, hi, args.step_nm, args.out, f'banc_{tag}_2um')

    json.dump(bands, open(os.path.join(args.out, 'support.json'), 'w'), indent=1)
    print(f'\ndone -> {args.out}', flush=True)
    print('Verify with:  python -c "from vfb_connectomics_import.images import transforms as banc_baked; '
          'banc_baked.self_check()"')


if __name__ == '__main__':
    main()
