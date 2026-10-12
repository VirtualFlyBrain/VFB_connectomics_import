#!/usr/bin/env python
"""Compare a baked field against the exact multi-step chain, on real neurons.

    export PATH="$HOME/opt/elastix/bin:$HOME/opt/usr/local/lib/cmtk/bin:$PATH"
    export DYLD_LIBRARY_PATH="$HOME/opt/elastix/lib:$DYLD_LIBRARY_PATH"
    python -m vfb_connectomics_import.images.verify_baked --connectome malecns --region brain

**Run this after every rebuild.** `bake_fields.py` writes the field and the sidecar json
proves it loads, but nothing else checks it is *correct*: a field built at the wrong
spacing, against the wrong target, or with a stale chain would pass every other check.
This is the only thing that would catch it, and it needs the binaries the production job
deliberately does not have — so it is a manual tool, not a CI test.

It reports three things, and all three matter:

* **Displacement error** on points that both routes resolve. This is the headline. Judge
  it against the source voxel (8 nm for both BANC and maleCNS) and the target voxel
  (~520 nm for JRC2018U, 400 nm for JRCVNC2018U) — anything in the micron range means the
  field does not match the registration it claims to.
* **Domain disagreement**: points where one route returns NaN and the other does not.
  Baked NaN comes from leaving the grid; native NaN from leaving the H5 support. These
  should very nearly coincide, and a point the baked field silently *keeps* when the exact
  chain rejects it is the dangerous direction.
* **How much real neuron material is out of support at all**, which is the number that
  says whether the grid extent was sized correctly.

Reference results
-----------------
BANC, against the exact elastix chain (2026-08-25, `verify_fields.py`):
    brain  mean 6.3 nm, p95 13.6, max 44.5
    vnc    mean 13.7 nm, p95 33.0, max 75.3
"""
import argparse
import os
import ssl
import sys
import warnings

import certifi
ssl._create_default_https_context = lambda *a, **k: ssl.create_default_context(
    cafile=certifi.where())
warnings.filterwarnings('ignore')

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))            # -> src/
from vfb_connectomics_import.images import chain              # noqa: E402
from vfb_connectomics_import.images import connectomes as C   # noqa: E402
from vfb_connectomics_import.images import sources            # noqa: E402

#: Sample neurons per connectome. Deliberately not random: each is a named cell whose
#: anatomy is known, and the set spans compact (MBON03), whole-brain (APL) and
#: brain-to-VNC crossing (DNa02) so a grid sized too small shows up.
SAMPLES = {
    'malecns': [(519373, 'MBON03_L'), (521526, 'MBON03_R'), (10540, 'APL_R'),
                (10977, 'APL_L'), (10360, 'DNa02_R'), (523769, 'DNa02_L'),
                # VNC-intrinsic and motor, so the VNC field is exercised by cells that
                # actually fill it rather than only by descending axons in its rostral tip
                (1051236875, 'AccTrFlexMN_L'), (1050088257, 'TiFlexMN_L'),
                (908762, 'TiFlexMN_L2'), (1051013755, 'IN13A073_L'),
                (909384, 'IN01B050b_L'), (910429, 'IN20A.22A081_L')],
    'banc': [(720575941394436502, 'MBON03'), (720575941514201932, 'crosser')],
}


def stats(a, b):
    """Per-point displacement between two (n,3) results, ignoring points either rejected."""
    ok = ~np.isnan(a).any(1) & ~np.isnan(b).any(1)
    only_a = int((~np.isnan(a).any(1) & np.isnan(b).any(1)).sum())
    only_b = int((np.isnan(a).any(1) & ~np.isnan(b).any(1)).sum())
    if not ok.any():
        return None, only_a, only_b, 0
    d = np.linalg.norm(a[ok] - b[ok], axis=1)
    return d, only_a, only_b, int(ok.sum())


def report(label, d, only_baked, only_native, n_ok, unit_nm=1000.0):
    if d is None:
        print(f'  {label:28s} no points resolved by both routes')
        return
    nm = d * unit_nm
    print(f'  {label:28s} n={n_ok:8,}  mean {nm.mean():7.1f} nm  median {np.median(nm):7.1f}'
          f'  p95 {np.percentile(nm, 95):7.1f}  max {nm.max():8.1f}'
          + (f'   [baked-only {only_baked}, native-only {only_native}]'
             if (only_baked or only_native) else ''))


def verify(cid, region_name, field_dir=None, lod=2, max_mesh_verts=400_000):
    c = C.get(cid)
    r = c.region(region_name)
    src = sources.for_connectome(cid)

    native, dn = chain.resolve(r, use_baked=False)
    baked, db = chain.resolve(r, use_baked=True, field_dir=field_dir)
    print(f'{cid}/{region_name}  cut {"xyz"[r.cut.axis]} '
          f'{"<" if r.cut.keep < 0 else ">"} {r.cut.at:,.0f} {c.units}')
    print('  native:', ' | '.join(dn))
    print('  baked :', ' | '.join(db), flush=True)

    all_d, tot_ob, tot_on, tot_n = [], 0, 0, 0
    for ident, name in SAMPLES.get(cid, []):
        for kind in ('skeleton', 'mesh'):
            if kind == 'skeleton':
                arr = src.skeleton(ident)
                pts = None if arr is None else arr[:, 2:5]
            else:
                m = src.mesh(ident, lod=lod)
                pts = None if m is None else np.asarray(m.vertices, float)
                if pts is not None and len(pts) > max_mesh_verts:
                    step = len(pts) // max_mesh_verts + 1
                    pts = pts[::step]
            if pts is None or not len(pts):
                print(f'  {name} {kind}: unavailable')
                continue
            keep = r.cut.mask(pts)
            pts = pts[keep]
            if len(pts) < 10:
                print(f'  {name:10s} {kind:8s} {int(keep.sum()):>8,} pts in region — skipped')
                continue
            a = chain.xform(baked, pts)
            b = chain.xform(native, pts)
            d, ob, on, n_ok = stats(a, b)
            report(f'{name} {kind} (lod{lod})' if kind == 'mesh' else f'{name} {kind}',
                   d, ob, on, n_ok)
            if d is not None:
                all_d.append(d)
                tot_ob += ob; tot_on += on; tot_n += n_ok
    if all_d:
        d = np.concatenate(all_d) * 1000.0
        print(f'\n  OVERALL  n={tot_n:,}  mean {d.mean():.1f} nm  median {np.median(d):.1f}'
              f'  p95 {np.percentile(d, 95):.1f}  p99 {np.percentile(d, 99):.1f}'
              f'  max {d.max():.1f} nm')
        print(f'  domain disagreement: baked kept but native rejected {tot_ob:,}; '
              f'native kept but baked rejected {tot_on:,}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--connectome', required=True, choices=sorted(C.CONNECTOMES))
    ap.add_argument('--region', required=True)
    ap.add_argument('--field-dir', default=None)
    ap.add_argument('--lod', type=int, default=2, help='mesh LOD to sample (maleCNS only)')
    args = ap.parse_args(argv)
    import navis, flybrains
    navis.set_pbars(hide=True)
    flybrains.register_transforms()
    return verify(args.connectome, args.region, args.field_dir, lod=args.lod)


if __name__ == '__main__':
    sys.exit(main())
