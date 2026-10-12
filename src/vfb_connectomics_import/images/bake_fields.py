#!/usr/bin/env python
"""Bake a Region's declared transform chain onto a dense grid, for `chain.py` to consume.

    export PATH="$HOME/opt/elastix/bin:$HOME/opt/usr/local/lib/cmtk/bin:$PATH"
    export DYLD_LIBRARY_PATH="$HOME/opt/elastix/lib:$DYLD_LIBRARY_PATH"   # Linux: LD_
    python -m vfb_connectomics_import.images.bake_fields --connectome malecns --region brain

Why bake at all
---------------
Two different costs, both fatal at whole-dataset scale, and baking removes both:

* **Binary hops.** ElastixTransform (all BANC legs) and CMTKtransform (the maleCNS VNC
  legs) spawn `transformix`/`streamxform` per call with text point files. Measured:
  elastix ~0.35 s fixed + 9.8 us/point; CMTK 11-36 ms fixed + 15.8-23.8 us/point.
* **H5 hops.** Not free either, and NOT in the way TRANSFORMS.md's "11 us/point" implies.
  Measured 2026-08-28 on maleCNS: ~0.4-1.0 s of FIXED cost per call per hop, which does
  **not** amortise across neurons because each neuron reads a different region of the
  deformation field. Ten different neurons through one warm TransformSequence: median
  440 ms, APL's 43,737 nodes 4.1 s, and MBON03's 4.59 M-vertex lod0 mesh **5.53 s**.

A baked field is 0.2-0.35 us/point with no fixed cost, memory-mapped so the OS page cache
shares one copy across every worker, and it replaces the binaries and the H5 files
outright: maleCNS goes from 4.4 GB of H5 plus a CMTK install to ~230 MB of `.npy`.

What is baked is decided per region in `connectomes.py`, not here. BANC bakes only its
elastix span and keeps the JRC tail live; maleCNS bakes all the way to the U templates.

`affine_fallback=False` — deliberate
------------------------------------
`TransformSequence.xform` defaults `affine_fallback=True`, which makes H5transform return
an *affine approximation* for points outside the deformation field's support. Baking that
in would freeze a plausible-looking approximation into the field, permanently
indistinguishable from real support. We bake with it off, so out-of-support grid nodes are
NaN, which is what `BakedField` already returns outside its own grid — the two then agree,
and out-of-domain stays detectable. See the "NaN outside the grid" note in TRANSFORMS.md.

Memory
------
Baked in slabs into a `np.lib.format.open_memmap` output, so peak RAM is one slab rather
than the whole grid. The previous version transformed all 18.6 M BANC nodes in a single
call and wanted ~15 GB.
"""
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))          # -> src/
from vfb_connectomics_import.images import chain            # noqa: E402
from vfb_connectomics_import.images import connectomes as C  # noqa: E402

MARGIN = 20_000.0          # source units; trilinear lookup needs neighbours at the cut face


def grid_axes(region, connectome, step, margin=MARGIN):
    """(lo, n) per axis: the region's anatomy plus a margin, clipped to the real volume."""
    if region.extent is None:
        raise SystemExit(
            f'{region.name}: no `extent` declared in connectomes.py, so the grid cannot be '
            f'sized. Add the region\'s source-space anatomical bounds (and say where they '
            f'came from in `extent_from`).')
    lo = np.asarray(region.extent[0], float) - margin
    hi = np.asarray(region.extent[1], float) + margin
    if connectome.volume:
        lo = np.maximum(lo, np.asarray(connectome.volume[0], float))
        hi = np.minimum(hi, np.asarray(connectome.volume[1], float))
    # ceil, not floor: the grid must SPAN [lo, hi]. With floor the top node lands below
    # `hi`, and wherever the volume clamp has already eaten the margin that shortfall is
    # real anatomy — it cost ~1 um at the caudal tip of the maleCNS abdominal neuromere,
    # which would have come back as NaN and been trimmed without complaint.
    n = np.ceil((hi - lo) / step).astype(int) + 1
    return lo, n


def bake(connectome, region, out_dir, step=None, chunk_points=2_000_000, verbose=True):
    b = region.bake
    if b is None:
        raise SystemExit(f'{connectome.id}/{region.name} declares no `bake` in connectomes.py')
    step = float(step or b.step_nm)
    lo, n = grid_axes(region, connectome, step)
    shape = tuple(int(x) for x in n)
    total = int(np.prod(shape))

    seq, described = chain.resolve(region, use_baked=False, verbose=False)
    if verbose:
        print(f'{connectome.id}/{region.name}: baking {b.frm} -> {b.to}')
        for d in described:
            print(f'    {d}')
        print(f'  grid {shape} @ {step:.0f} {connectome.units}  = {total/1e6:.2f} M nodes '
              f'({total*12/1e6:.0f} MB)')
        print(f'  lo {np.round(lo).astype(np.int64).tolist()}  '
              f'hi {np.round(lo + (n-1)*step).astype(np.int64).tolist()}', flush=True)

    os.makedirs(out_dir, exist_ok=True)
    npy = os.path.join(out_dir, b.stem + '.npy')
    tmp = npy + '.partial'
    field = np.lib.format.open_memmap(tmp, mode='w+', dtype=np.float32, shape=shape + (3,))

    ax = [lo[i] + step * np.arange(shape[i]) for i in range(3)]
    per_plane = shape[1] * shape[2]
    planes = max(1, int(chunk_points // max(per_plane, 1)))
    t0, n_nan = time.time(), 0
    for i0 in range(0, shape[0], planes):
        i1 = min(i0 + planes, shape[0])
        g = np.stack(np.meshgrid(ax[0][i0:i1], ax[1], ax[2], indexing='ij'), -1)
        out = chain.xform(seq, g.reshape(-1, 3), affine_fallback=False)
        n_nan += int(np.isnan(out).any(1).sum())
        field[i0:i1] = out.reshape(i1 - i0, shape[1], shape[2], 3).astype(np.float32)
        if verbose:
            done = i1 / shape[0]
            el = time.time() - t0
            print(f'    x {i1:4d}/{shape[0]}  {100*done:5.1f}%  {el/60:5.1f} min '
                  f'(eta {el/done*(1-done)/60:5.1f} min)', flush=True)
    field.flush()
    del field
    os.replace(tmp, npy)
    dt = time.time() - t0

    meta = dict(
        connectome=connectome.id, region=region.name,
        source=b.frm, target=b.to,
        lo=[float(x) for x in lo], step=[step] * 3,
        shape=list(shape) + [3], dtype='float32', units=connectome.units,
        chain=described, affine_fallback=False,
        out_of_support_frac=round(n_nan / total, 6),
        extent_from=region.extent_from, margin=MARGIN,
        cut=dict(axis=int(region.cut.axis), at=float(region.cut.at),
                 keep=int(region.cut.keep), derived_from=region.cut.derived_from),
        built=time.strftime('%Y-%m-%d'), build_seconds=round(dt, 1),
        note='Full declared chain, baked. Out-of-support nodes are NaN, NOT affine-'
             'extrapolated (affine_fallback=False). Compose nothing downstream unless '
             '`target` is short of the final template.')
    with open(os.path.splitext(npy)[0] + '.json', 'w') as fh:
        json.dump(meta, fh, indent=1)
    if verbose:
        print(f'  {dt/60:.1f} min -> {npy} ({os.path.getsize(npy)/1e6:.0f} MB)')
        print(f'  out of support: {n_nan:,}/{total:,} nodes '
              f'({100*n_nan/total:.2f}%) -> NaN', flush=True)
    return npy


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--connectome', required=True, choices=sorted(C.CONNECTOMES))
    ap.add_argument('--region', required=True, help='brain | vnc | both')
    ap.add_argument('--out', default=os.environ.get(
        'BANC_FIELD_DIR', os.path.expanduser('~/Documents/banc_transform_fields')))
    ap.add_argument('--step-nm', type=float, default=None,
                    help='grid spacing in source units (default: the region\'s Bake.step_nm)')
    ap.add_argument('--chunk-points', type=int, default=2_000_000,
                    help='points per transform call; caps peak RAM (default 2M)')
    args = ap.parse_args(argv)

    import navis, flybrains
    navis.set_pbars(hide=True)
    flybrains.register_transforms()

    c = C.get(args.connectome)
    regions = ['brain', 'vnc'] if args.region == 'both' else [args.region]
    for rn in regions:
        bake(c, c.region(rn), args.out, step=args.step_nm,
             chunk_points=args.chunk_points)
    print(f'\ndone -> {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
