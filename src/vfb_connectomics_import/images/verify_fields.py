"""Verify the baked BANC fields against the exact elastix chain, on a real neuron.

    export PATH="$HOME/opt/elastix/bin:$PATH"
    export DYLD_LIBRARY_PATH="$HOME/opt/elastix/lib:$DYLD_LIBRARY_PATH"   # Linux: LD_
    python -m vfb_connectomics_import.images.verify_fields

**Run this after ever rebuilding the fields.** `bake_fields.py` builds them and
`transforms.self_check()` confirms they load and reject out-of-domain points — but nothing
else checks they are *correct*. A field rebuilt at the wrong spacing, or against the wrong
target, would sail through `self_check()`. This is the only thing that would catch it.

Needs the `transformix` binary, so it is a manual verification tool rather than a CI test
(the whole point of the bake is that the production job has no elastix dependency).

Expected, measured 2026-08-25 on the crosser below:
    brain  mean 6.3 nm, p95 13.6, max 44.5   against an 8 nm source voxel
    vnc    mean 13.7 nm, p95 33.0, max 75.3
Anything in the micron range means the fields do not match the registration they claim to.

It also reports the same neuron against the image VFB currently serves, which is a
different question — that comparison is ~3 um in the brain and ~22 um in the VNC, and the
VNC discrepancy is in VFB's image, not in these fields (docs/ISSUES.md IMG-3).
"""

import os, io, sys, time, warnings, logging, urllib.request, ssl
import certifi
ssl._create_default_https_context = lambda *a, **k: ssl.create_default_context(cafile=certifi.where())
warnings.filterwarnings('ignore'); logging.getLogger('navis').setLevel(logging.ERROR)

import numpy as np, pandas as pd, trimesh
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import navis, flybrains
from navis.transforms.base import TransformSequence

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))   # -> src/
from vfb_connectomics_import.images import transforms as banc_baked

flybrains.register_transforms()
navis.set_pbars(hide=True)

S = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(S, 'render_baked_vfb'); os.makedirs(OUT, exist_ok=True)
BUCKET = 'lee-lab_brain-and-nerve-cord-fly-connectome'
ROOT = '720575941514201932'
VFB_ID = 'VFB_00105soo'
VFB_FOLDER = 'http://www.virtualflybrain.org/data/VFB/i/0010/5soo'

BRAIN_MAX_Y = 305_801.0      # BANC_brain.ply y max
VNC_MIN_Y   = 549_946.0      # BANC_vnc.ply  y min

CFG = {
 'brain': dict(tmpl='JRC2018U',    vfb='VFB_00101567'),
 'vnc':   dict(tmpl='JRCVNC2018U', vfb='VFB_00200000'),
}
for h, c in CFG.items():
    bb = np.asarray(getattr(flybrains, c['tmpl']).boundingbox, float).reshape(3, 2)
    c['bb'] = bb
    print(f"{c['tmpl']:12s} bbox {np.round(bb.ravel(),1).tolist()}")

# ---- capture the EXACT (elastix) chain before the baked edges are registered ----
EXACT = {}
for h, c in CFG.items():
    p, t = navis.transforms.registry.find_bridging_path('BANC', c['tmpl'])
    EXACT[h] = TransformSequence(*t, copy=False)
    print(f"exact  {h:5s}: {' -> '.join(p)}   ({', '.join(type(x).__name__ for x in t)})")

# ---- register the baked fields; navis should now prefer them ----
print()
transforms.register()
transforms.self_check()
print()
BAKED = {}
for h, c in CFG.items():
    p, t = navis.transforms.registry.find_bridging_path('BANC', c['tmpl'])
    BAKED[h] = TransformSequence(*t, copy=False)
    print(f"baked  {h:5s}: {' -> '.join(p)}   ({', '.join(type(x).__name__ for x in t)})")
    assert not any('Elastix' in type(x).__name__ for x in t), 'elastix still in the path!'


def cable_um(arr):
    """SWC cable length in um, from nm coordinates."""
    if len(arr) < 2: return 0.0
    pos = {int(r[0]): r[2:5] for r in arr}
    return sum(float(np.linalg.norm(r[2:5] - pos[int(r[6])]))
               for r in arr if int(r[6]) in pos) / 1000.0


def to_neuron(a, name):
    return navis.TreeNeuron(pd.DataFrame({
        'node_id': a[:, 0].astype(int), 'parent_id': a[:, 6].astype(int),
        'x': a[:, 2], 'y': a[:, 3], 'z': a[:, 4], 'radius': a[:, 5]}),
        id=name, name=name, units='microns')


def neuropil_mesh(tmpl):
    tm = getattr(flybrains, tmpl).mesh
    if not isinstance(tm, trimesh.Trimesh):
        tm = trimesh.Trimesh(vertices=np.asarray(tm.vertices),
                             faces=np.asarray(tm.faces), process=False)
    return tm


def contains(tm, pts):
    """Fraction inside the neuropil mesh; None if trimesh cannot answer."""
    try:
        return tm.contains(pts)
    except BaseException:
        return None


# ---------------------------------------------------------------- source skeleton
url = (f'https://storage.googleapis.com/{BUCKET}/compiled_data/banc_888/'
       f'banc_banc_space_swc/{ROOT}_skeleton.swc')
t0 = time.time()
src = np.loadtxt(io.StringIO(urllib.request.urlopen(url, timeout=300).read().decode()),
                 comments='#', ndmin=2)
print(f'\nsource: {len(src)} nodes, fetched in {time.time()-t0:.1f} s')
print(f'  BANC y range {src[:,3].min():.0f} .. {src[:,3].max():.0f} nm')
inconn = (src[:, 3] >= BRAIN_MAX_Y) & (src[:, 3] <= VNC_MIN_Y)
nb, nv = int((src[:, 3] < BRAIN_MAX_Y).sum()), int((src[:, 3] > VNC_MIN_Y).sum())
print(f'  brain side  (y < {BRAIN_MAX_Y:.0f}) : {nb}')
print(f'  connective  (DROPPED)             : {inconn.sum()} nodes '
      f'({100*inconn.mean():.1f}%), {cable_um(src[inconn]):.0f} um cable')
print(f'  vnc side    (y > {VNC_MIN_Y:.0f}) : {nv}')

ours, vfbs, summary = {}, {}, {}
for half, c in CFG.items():
    print(f'\n{"="*78}\n{half.upper()}  ->  {c["tmpl"]}\n{"="*78}')
    sub = src[src[:, 3] < BRAIN_MAX_Y] if half == 'brain' else src[src[:, 3] > VNC_MIN_Y]
    if not len(sub):
        print('  no nodes on this side'); continue

    # --- baked transform (the production route) ---
    t0 = time.time(); xyz = np.asarray(BAKED[half].xform(sub[:, 2:5].copy()), float)
    t_baked = time.time() - t0
    # --- exact elastix chain, for a per-neuron accuracy figure ---
    try:
        t0 = time.time(); exact = np.asarray(EXACT[half].xform(sub[:, 2:5].copy()), float)
        t_exact = time.time() - t0
        err = np.linalg.norm(xyz - exact, axis=1) * 1000.0   # um -> nm
        acc = (f'baked vs exact elastix: mean {np.nanmean(err):.1f} nm, '
               f'p95 {np.nanpercentile(err,95):.1f}, max {np.nanmax(err):.1f}')
        spd = f'baked {t_baked*1000:.0f} ms vs elastix {t_exact:.2f} s ({t_exact/max(t_baked,1e-9):.0f}x)'
    except BaseException as e:
        acc = f'exact elastix unavailable ({type(e).__name__}) -- no cross-check'
        spd = f'baked {t_baked*1000:.0f} ms'
    print(f'  {len(sub)} nodes | {spd}')
    print(f'  {acc}')

    nan_out = np.isnan(xyz).any(1)
    bb = c['bb']
    keep = ~nan_out & ~((xyz < bb[:, 0]) | (xyz > bb[:, 1])).any(1)
    print(f'  outside the baked field (NaN): {nan_out.sum()}   '
          f'trimmed by {c["tmpl"]} bbox: {int((~nan_out & ~keep).sum())}   kept: {keep.sum()}')

    a = sub.copy(); a[:, 2:5] = xyz; a = a[keep]
    kid = set(a[:, 0].astype(np.int64))
    par = a[:, 6].astype(np.int64).copy(); par[~np.isin(par, list(kid))] = -1
    a[:, 6] = par; a[:, 5] = a[:, 5] / 1000.0
    ours[half] = to_neuron(a, f'ours_{half}')
    pts = a[:, 2:5]

    # spatial coherence -- did any stray fragment survive?
    if len(pts) > 1:
        pr = np.array(list(cKDTree(pts).query_pairs(r=5.0)))
        g = coo_matrix((np.ones(len(pr)), (pr[:, 0], pr[:, 1])), shape=(len(pts),) * 2)
        n, lab = connected_components(g, directed=False)
        sz = np.bincount(lab); o = np.argsort(-sz)
        print(f'  spatial clusters (5 um link): {n}, sizes {sz[o][:5].tolist()}')
        for k in o[1:4]:
            print(f'     stray {sz[k]} nodes at {np.round(pts[lab==k].mean(0),1)}')

    tm = neuropil_mesh(c['tmpl'])
    ins = contains(tm, pts)
    ours_in = None if ins is None else 100 * ins.mean()
    print(f'  OURS  inside the {c["tmpl"]} neuropil mesh: '
          + ('unavailable' if ins is None else f'{ins.sum()}/{len(pts)} ({ours_in:.1f}%)'))

    # ------------------------------------------------ VFB's existing image
    row = dict(half=half, tmpl=c['tmpl'], ours_nodes=len(pts), ours_in=ours_in)
    try:
        vr = urllib.request.urlopen(f'{VFB_FOLDER}/{c["vfb"]}/volume.swc', timeout=300).read()
        va = np.loadtxt(io.StringIO(vr.decode()), comments='#', ndmin=2)
        vfbs[half] = to_neuron(va, f'vfb_{half}')
        b = va[:, 2:5]
        d_ov = cKDTree(b).query(pts, k=1)[0]
        d_vo = cKDTree(pts).query(b, k=1)[0]
        vin = contains(tm, b)
        vfb_in = None if vin is None else 100 * vin.mean()
        print(f'  VFB existing image: {len(va)} nodes')
        print(f'    centroid offset      {np.linalg.norm(pts.mean(0)-b.mean(0)):.2f} um')
        print(f'    ours->VFB nearest    median {np.median(d_ov):.2f}  p95 {np.percentile(d_ov,95):.2f} um')
        print(f'    VFB->ours nearest    median {np.median(d_vo):.2f}  p95 {np.percentile(d_vo,95):.2f} um')
        print(f'    VFB  inside neuropil: '
              + ('unavailable' if vin is None else f'{vin.sum()}/{len(b)} ({vfb_in:.1f}%)'))
        row.update(vfb_nodes=len(va), vfb_in=vfb_in,
                   centroid=float(np.linalg.norm(pts.mean(0)-b.mean(0))),
                   med_ov=float(np.median(d_ov)), med_vo=float(np.median(d_vo)))
    except Exception as e:
        print(f'  VFB existing image: FAILED ({type(e).__name__}: {e})')
    summary[half] = row

# ---------------------------------------------------------------- render
for half in ours:
    c = CFG[half]
    tm = getattr(flybrains, c['tmpl']).mesh
    vol = navis.Volume(np.asarray(tm.vertices), np.asarray(tm.faces), name=half)
    vol.color = (0.85, 0.85, 0.85, 0.12)
    ours[half].color = (1, 0, 0)
    objs = [vol, ours[half]]
    if half in vfbs:
        vfbs[half].color = (0, 0.35, 1); objs.append(vfbs[half])
    fig, axes = plt.subplots(1, 3, figsize=(21, 7))
    for ax, (lbl, view) in zip(axes, [('frontal', ('x', '-y')), ('dorsal', ('x', '-z')),
                                      ('lateral', ('z', '-y'))]):
        navis.plot2d(objs, ax=ax, method='2d', view=view, linewidth=.5)
        ax.set_title(f'{half} / {c["tmpl"]} — {lbl}\nred = ours (baked + neuropil cut), '
                     f'blue = VFB existing')
        ax.set_aspect('equal')
    p = f'{OUT}/{half}_compare.png'; fig.savefig(p, dpi=90, bbox_inches='tight'); plt.close(fig)
    print(f'\nwrote {p}')
    try:
        import plotly.offline as po
        po.plot(navis.plot3d(objs, backend='plotly', inline=False),
                filename=f'{OUT}/{half}_3d.html', auto_open=False)
        print(f'wrote {OUT}/{half}_3d.html')
    except Exception as e:
        print(f'  plotly: {type(e).__name__}')

print('\n' + '='*78 + '\nSUMMARY\n' + '='*78)
print(f'{"half":6s} {"template":13s} {"ours":>7s} {"VFB":>7s} {"centroid":>9s} '
      f'{"o->V med":>9s} {"ours in":>8s} {"VFB in":>8s}')
for h, r in summary.items():
    f = lambda k, s='{:.2f}': ('n/a' if r.get(k) is None else s.format(r[k]))
    print(f'{h:6s} {r["tmpl"]:13s} {r["ours_nodes"]:7d} {r.get("vfb_nodes",0):7d} '
          f'{f("centroid"):>9s} {f("med_ov"):>9s} {f("ours_in","{:.1f}%"):>8s} '
          f'{f("vfb_in","{:.1f}%"):>8s}')
