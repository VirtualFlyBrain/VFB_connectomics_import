#!/usr/bin/env python
"""How much of each served mesh actually lies inside the template neuropil.

The bbox trim both pipelines apply only proves a point is in the *box*. IMG-3 is
precisely the case where misplaced material lands inside the box and outside the brain,
so the box cannot be the test. This fills the template surface into an occupancy grid and
asks what fraction of each mesh's SURFACE AREA falls inside it — area-weighted by
sampling the surface, not counting vertices, so a dense blob cannot dominate.

4 µm pitch, i.e. coarser than the templates' own display grids. That is deliberate: it
errs toward calling material "inside", so a low number is strong evidence and a high one
is only weak evidence. Good enough to separate 3% from 97%, which is the whole question.

Measured on the FULL-RESOLUTION meshes, never the display copies. The display meshes are
decimated to a fixed 20,000 faces, so an 11.97 M-face served mesh is reduced 600x while
its 2.07 M-face replacement is reduced 100x — and decimation moves the surface. Comparing
those two would be measuring the display reduction, not the pipelines.
"""
import json, os, sys
import numpy as np, trimesh
import warnings; warnings.filterwarnings('ignore')
import flybrains

SP = os.path.dirname(os.path.abspath(__file__))
N_SAMPLE = 60_000
PITCH = 4.0
TEMPLATE = {'brain': 'JRC2018U', 'vnc': 'JRCVNC2018U'}


def grid(name):
    m = getattr(flybrains, name).mesh
    tm = trimesh.Trimesh(vertices=np.asarray(m.vertices), faces=np.asarray(m.faces),
                         process=True)
    tm.fix_normals(); tm.fill_holes()
    return tm.voxelized(pitch=PITCH).fill()


GRIDS = {k: grid(v) for k, v in TEMPLATE.items()}


def inside_frac(path, region):
    if not os.path.exists(path):
        return None
    m = trimesh.load(path, process=False, force='mesh')
    pts, _ = trimesh.sample.sample_surface(m, N_SAMPLE)
    out = round(100.0 * float(GRIDS[region].is_filled(pts).mean()), 1)
    del m
    return out


def main():
    rows = json.load(open(os.path.join(SP, 'display_index.json')))
    for row in rows:
        for region in ('brain', 'vnc'):
            e = row['regions'].get(region, {})
            paths = {'old': os.path.join(SP, 'old', f"{row['accession']}_{region}.obj"),
                     'new': os.path.join(SP, 'new', f"{row['accession']}_{region}.obj")}
            for which in ('old', 'new'):
                if e.get(which):
                    e[which]['inside_pct'] = inside_frac(paths[which], region)
            o = e.get('old', {}).get('inside_pct')
            n = e.get('new', {}).get('inside_pct')
            print(f"{row['label']:20s} {region:5s}  old {str(o)+'%':>7s}   "
                  f"new {(str(n)+'%' if n is not None else 'empty'):>7s}")
    json.dump(rows, open(os.path.join(SP, 'display_index.json'), 'w'), indent=1)
    print('\nwritten back to display_index.json')


if __name__ == '__main__':
    main()
