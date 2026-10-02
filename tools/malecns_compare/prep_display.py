#!/usr/bin/env python
"""Decimate every old/new mesh to a display budget and cache as npz.

Display-only reduction. The pipeline's own output is `new/*.obj` and is NOT what gets
plotted at full resolution -- a 11.97 M-face served mesh cannot go into a plotly scene.
Face budget is per mesh, chosen so the whole page stays openable; it is far above what is
needed to judge placement and the brain/VNC split, which is what these pictures are for.
"""
import json, os, sys, time
import numpy as np, trimesh, fast_simplification

SP = os.path.dirname(os.path.abspath(__file__))
DISPLAY_FACES = 20_000
OUT = os.path.join(SP, 'display'); os.makedirs(OUT, exist_ok=True)


def shrink(v, f, budget=DISPLAY_FACES):
    n = len(f)
    if n <= budget:
        return np.asarray(v, float), np.asarray(f, int)
    vv, ff = fast_simplification.simplify(np.asarray(v, np.float32),
                                          np.asarray(f, np.int32),
                                          target_reduction=1 - budget / n)
    return np.asarray(vv, float), np.asarray(ff, int)


def cache(tag, path):
    out = os.path.join(OUT, tag + '.npz')
    if os.path.exists(out):
        return json.load(open(out + '.json'))
    t0 = time.perf_counter()
    m = trimesh.load(path, process=False, force='mesh')
    v, f = np.asarray(m.vertices), np.asarray(m.faces)
    full = len(f)
    v2, f2 = shrink(v, f)
    np.savez_compressed(out, v=np.round(v2, 2).astype(np.float32), f=f2.astype(np.int32))
    meta = {'full_faces': int(full), 'display_faces': int(len(f2)),
            'bbox_lo': v.min(0).round(2).tolist(), 'bbox_hi': v.max(0).round(2).tolist(),
            'seconds': round(time.perf_counter() - t0, 1)}
    json.dump(meta, open(out + '.json', 'w'))
    del m, v, f
    return meta


def main():
    res = json.load(open(os.path.join(SP, 'new_results.json')))
    index = []
    for e in res:
        acc = e['accession']
        row = {'label': e['label'], 'accession': acc, 'kind': e['kind'], 'regions': {}}
        for region in ('brain', 'vnc'):
            r = e['regions'].get(region, {})
            entry = {'status': r.get('status')}
            old_path = os.path.join(SP, 'old', f'{acc}_{region}.obj')
            if os.path.exists(old_path):
                entry['old'] = cache(f'old_{acc}_{region}', old_path)
                entry['old']['wire_mb'] = round(os.path.getsize(old_path) / 1e6, 2)
                print(f"old {e['label']:20s} {region:5s} {entry['old']['full_faces']:>10,} f "
                      f"-> {entry['old']['display_faces']:,}  [{entry['old']['seconds']}s]")
            if r.get('status') == 'ok':
                entry['new'] = cache(f'new_{acc}_{region}', r['path'])
                entry['new'].update({k: r[k] for k in
                                     ('lod', 'faces', 'f_per_um2', 'area_um2', 'obj_raw_mb',
                                      'obj_gz_mb', 'decimated', 'lod_if_raw_budget')})
                entry['new']['plan'] = r['plan']
                entry['new']['tried'] = r['tried']
                print(f"new {e['label']:20s} {region:5s} {entry['new']['full_faces']:>10,} f "
                      f"-> {entry['new']['display_faces']:,}  lod{r['lod']}")
            row['regions'][region] = entry
        index.append(row)
        json.dump(index, open(os.path.join(SP, 'display_index.json'), 'w'), indent=1)
    print('done')


if __name__ == '__main__':
    main()
