#!/usr/bin/env python
"""Run the NEW maleCNS image pipeline over the comparison panel, mesh products only.

Prototype of the geometry path a generalised `loader.py` would run: it drives
`connectomes.MALECNS` + `sources.MaleCnsBucket` + `chain.resolve` directly, so the cut
planes, declared transform chain and baked fields are exactly production's, and the
LOD rule of docs/MESH_SIZING.md is implemented here for the first time.

Per neuron per region:
  1. coarsest rung -> cut (SOURCE space) -> transform (baked) -> trim -> template area
  2. predict every rung at `area x density x 9 bytes`, discard any above the ceiling,
     pick the finest predicted to fit the budget
  3. fetch it, rebuild, and MEASURE. Bust the budget -> step down and repeat.
"""
import gzip, io, json, os, sys, time
import numpy as np

SP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SP, 'gil', 'src'))
os.environ.setdefault('BANC_FIELD_DIR', os.path.expanduser('~/Documents/banc_transform_fields'))

import warnings; warnings.filterwarnings('ignore')
import logging; logging.getLogger('navis').setLevel(logging.ERROR)
import navis, flybrains, trimesh
flybrains.register_transforms()

from vfb_connectomics_import.images import connectomes, chain, sources

CX = connectomes.MALECNS

# ---------------------------------------------------------------- the ladder (MESH_SIZING)
# f/um2 in TEMPLATE space, from the 100-neuron calibration: lod2 median 32.2, lod3 6.78;
# lod1 196 is the figure the doc predicts with, lod0 ~1292. Belongs in connectomes.py next
# to Cut and Hop; it lives here only because this is a prototype.
LADDER = {0: 1292.0, 1: 196.0, 2: 32.2, 3: 6.78}
CEILING_F_PER_UM2 = 200.0
BUDGET_MB = 20.0
BYTES_PER_FACE = 9.0
#: measured on the OBJs this script writes. The policy's budget is in GZIPPED bytes, but
#: www.virtualflybrain.org serves volume_man.obj as application/octet-stream with no
#: Content-Encoding even when gzip/br are offered (checked 2026-10-02, nginx/1.20.2), so
#: the wire cost is the RAW size. Recorded alongside, not acted on — changing the basis of
#: the budget is a decision, not a bug fix.
BYTES_PER_FACE_RAW = 35.2
OBJ_DP = 3
COARSEST = 3


def cut_mesh(mesh, cut):
    """Open cut on `cut.axis` in SOURCE space. None if nothing remains."""
    normal = np.zeros(3); normal[cut.axis] = float(cut.keep)
    origin = np.zeros(3); origin[cut.axis] = cut.at
    try:
        h = mesh.slice_plane(plane_origin=origin, plane_normal=normal, cap=False)
    except BaseException:
        return None
    return h if (h is not None and len(h.faces)) else None


def build(mesh, region, seq):
    """Cut, transform, trim to the template bbox. Template microns out, or None."""
    if mesh is None:
        return None
    half = cut_mesh(mesh, region.cut)
    if half is None:
        return None
    xyz = chain.xform(seq, np.asarray(half.vertices))
    bb = region.bb()
    bad = ~np.all((xyz >= bb[:, 0]) & (xyz <= bb[:, 1]), axis=1)   # NaN -> bad, correctly
    faces = np.asarray(half.faces)
    if bad.any():
        faces = faces[~bad[faces].any(1)]
        if not len(faces):
            return None
    out = trimesh.Trimesh(vertices=xyz, faces=faces, process=False)
    out.remove_unreferenced_vertices()
    return out if len(out.faces) else None


def area_um2(mesh):
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    return float(np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]],
                                         v[f[:, 2]] - v[f[:, 0]]), axis=1).sum() / 2)


def obj_bytes(mesh, dp=OBJ_DP):
    """Exact bytes of the OBJ we would write, raw and gzipped."""
    buf = io.BytesIO()
    v, f = np.asarray(mesh.vertices, float), np.asarray(mesh.faces, int) + 1
    np.savetxt(buf, v, fmt=f'v %.{dp}f %.{dp}f %.{dp}f')
    np.savetxt(buf, f, fmt='f %d %d %d')
    raw = buf.getvalue()
    return len(raw), len(gzip.compress(raw, 6)), raw


def choose(area, served_rungs):
    """Rungs admissible by the ceiling, finest first, with their predicted size."""
    rungs = [r for r in sorted(served_rungs) if LADDER[r] <= CEILING_F_PER_UM2]
    return [(r, area * LADDER[r], area * LADDER[r] * BYTES_PER_FACE / 1e6) for r in rungs]


def run_one(src, acc, region_name, seq_cache, log):
    region = CX.region(region_name)
    if region_name not in seq_cache:
        seq_cache[region_name], desc = chain.resolve(region, use_baked=True)
        log(f'  chain[{region_name}]: ' + ' | '.join(desc))
    seq = seq_cache[region_name]

    t0 = time.perf_counter()
    coarse_src = src.mesh(acc, lod=COARSEST)
    if coarse_src is None:
        return {'status': 'no-source'}
    coarse = build(coarse_src, region, seq)
    if coarse is None:
        return {'status': 'empty', 'coarse_faces_src': int(len(coarse_src.faces))}
    area = area_um2(coarse)

    plan = choose(area, served_rungs=[0, 1, 2, 3])
    raw_fits = [r for r, pf, _ in plan if pf * BYTES_PER_FACE_RAW / 1e6 <= BUDGET_MB]
    rec = {'status': 'ok', 'area_um2': round(area, 1),
           'plan': [{'lod': r, 'pred_faces': int(pf), 'pred_mb': round(pm, 2),
                     'pred_raw_mb': round(pf * BYTES_PER_FACE_RAW / 1e6, 2)}
                    for r, pf, pm in plan],
           'ceiling_excluded': [r for r in (0, 1, 2, 3) if LADDER[r] > CEILING_F_PER_UM2],
           'lod_if_raw_budget': min(raw_fits) if raw_fits else None}

    # Rungs run finest -> coarsest, i.e. ascending lod number. Start at the finest
    # PREDICTED to fit (or, if none does, the finest admissible) and step down from there.
    admissible = [r for r, _, _ in plan]
    fits = [r for r, _, pm in plan if pm <= BUDGET_MB]
    start = min(fits) if fits else min(admissible)
    order = [r for r in admissible if r >= start]

    tried = []
    for lod in order:
        m_src = src.mesh(acc, lod=lod)
        if m_src is None:
            tried.append({'lod': lod, 'result': 'absent'}); continue
        m = build(m_src, region, seq)
        if m is None:
            tried.append({'lod': lod, 'result': 'empty'}); continue
        n = len(m.faces)
        est_mb = n * BYTES_PER_FACE / 1e6
        tried.append({'lod': lod, 'faces': int(n), 'est_mb': round(est_mb, 2),
                      'f_per_um2': round(n / area, 1)})
        if est_mb <= BUDGET_MB:
            raw, gz, blob = obj_bytes(m)
            rec.update({'lod': lod, 'faces': int(n), 'f_per_um2': round(n / area, 1),
                        'obj_raw_mb': round(raw / 1e6, 2), 'obj_gz_mb': round(gz / 1e6, 2),
                        'decimated': False, 'tried': tried,
                        'seconds': round(time.perf_counter() - t0, 1)})
            return rec, m, blob
        del m, m_src

    # Nothing the publisher ships fits — the only path that reprocesses.
    finest = min(r for r, _, _ in plan)
    m = build(src.mesh(acc, lod=finest), region, seq)
    import fast_simplification
    n = len(m.faces); target = int(BUDGET_MB * 1e6 / BYTES_PER_FACE)
    v, f = fast_simplification.simplify(np.asarray(m.vertices, np.float32),
                                        np.asarray(m.faces, np.int32),
                                        target_reduction=1 - target / n)
    m = trimesh.Trimesh(vertices=np.asarray(v, float), faces=np.asarray(f, int), process=False)
    raw, gz, blob = obj_bytes(m)
    rec.update({'lod': finest, 'faces': int(len(m.faces)), 'f_per_um2': round(len(m.faces) / area, 1),
                'obj_raw_mb': round(raw / 1e6, 2), 'obj_gz_mb': round(gz / 1e6, 2),
                'decimated': True, 'decimated_from': int(n), 'tried': tried,
                'seconds': round(time.perf_counter() - t0, 1)})
    return rec, m, blob


def main():
    panel = json.load(open(os.path.join(SP, 'panel.json')))
    out_dir = os.path.join(SP, 'new'); os.makedirs(out_dir, exist_ok=True)
    src = sources.MaleCnsBucket()
    seq_cache = {}
    results = []
    logf = open(os.path.join(SP, 'newpipe.log'), 'w')
    def log(s):
        print(s); logf.write(s + '\n'); logf.flush()

    log(f'maleCNS {CX.label}  ladder {LADDER}  ceiling {CEILING_F_PER_UM2} f/um2  '
        f'budget {BUDGET_MB} MB')
    for p in panel:
        log(f"\n=== {p['label']}  MaleCNS:{p['accession']}  (expected: {p['kind']})")
        entry = {**p, 'regions': {}}
        for region_name in ('brain', 'vnc'):
            r = run_one(src, p['accession'], region_name, seq_cache, log)
            if isinstance(r, dict):
                log(f"  {region_name:5s} -> {r['status']}")
                entry['regions'][region_name] = r
                continue
            rec, mesh, blob = r
            path = os.path.join(out_dir, f"{p['accession']}_{region_name}.obj")
            open(path, 'wb').write(blob)
            rec['path'] = path
            entry['regions'][region_name] = rec
            log(f"  {region_name:5s} -> lod{rec['lod']}  {rec['faces']:>9,} faces  "
                f"{rec['f_per_um2']:>6.1f} f/um2  area {rec['area_um2']:>9,.0f} um2  "
                f"raw {rec['obj_raw_mb']:>6.2f} MB  gz {rec['obj_gz_mb']:>5.2f} MB"
                f"{'  DECIMATED' if rec['decimated'] else ''}  [{rec['seconds']}s]")
            log(f"        plan: " + ', '.join(f"lod{d['lod']}~{d['pred_mb']}MB" for d in rec['plan'])
                + '  tried: ' + ', '.join(
                    f"lod{t['lod']}={t.get('est_mb', t.get('result'))}" for t in rec['tried']))
            del mesh, blob
        results.append(entry)
        json.dump(results, open(os.path.join(SP, 'new_results.json'), 'w'), indent=1)
    log('\ndone')


if __name__ == '__main__':
    main()
