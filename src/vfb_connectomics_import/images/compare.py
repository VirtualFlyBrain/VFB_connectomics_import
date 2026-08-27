#!/usr/bin/env python
"""Render old-vs-new 3D comparisons from a `vfb-banc-images --archive` directory.

    vfb-banc-images --region brain --limit 20 --archive $WORKSPACE/archive ...
    vfb-banc-compare --archive $WORKSPACE/archive --out $WORKSPACE/compare

Writes one interactive plotly HTML per neuron plus an `index.html` table, into the Jenkins
workspace — never into a live image folder. Each page shows, in the same template space:

    template surface, plus OLD skeleton + OLD mesh and NEW skeleton + NEW mesh.

Colours come from plotly's own legend — the page does not restate them, because a
hardcoded swatch drifts from whatever navis/plotly actually renders.

**A missing product is stated, not implied.** Every page carries a four-row table saying
present/MISSING for old-skel, old-mesh, new-skel, new-mesh, with the loader's own status and
note beside it — so `deleted_spurious` (new deliberately absent) reads differently from a
mesh that upstream never published. `index.html` shows the same matrix for the whole batch.

Meshes are decimated **for display only** so a 20-neuron page set stays openable in a
browser; the label says so. The served OBJs are whatever the loader wrote.
"""
import argparse
import glob
import json
import logging
import os
import sys
import warnings

warnings.filterwarnings('ignore')
logging.getLogger('navis').setLevel(logging.ERROR)

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))   # -> src/, so the package imports

#: (label, subdir, filename, colour) — the four things we overlay on the template.
LAYERS = (
    ('old skeleton', 'old', 'volume.swc', (0.15, 0.35, 0.95)),
    ('old mesh', 'old', 'volume_man.obj', (0.55, 0.75, 1.00)),
    ('new skeleton', 'new', 'volume.swc', (0.90, 0.10, 0.10)),
    ('new mesh', 'new', 'volume_man.obj', (1.00, 0.60, 0.10)),
)
TEMPLATE = {'brain': 'JRC2018U', 'vnc': 'JRCVNC2018U'}
#: 0 = show the meshes exactly as served, which is the point of this page. The loader
#: already bounds the NEW mesh (37 f/um2 above a 4 MB wire budget), so it needs no help.
#: The OLD v626 meshes are unbounded though — IMG-1 measured mean 9.74 MB, max 44.63 MB —
#: so a decimating escape hatch stays available for a page a browser will not open.
DISPLAY_FACES = 0


def hush_navis():
    """Silence navis' INFO chatter — must run AFTER `import navis`.

    Setting the level at module import does nothing: navis installs its own handler at
    INFO when it is imported, which happens later (lazily, inside functions). Without this
    every plot3d emits "Use the `.show()` method to plot the figure.", one line per neuron.
    """
    import logging
    for name in ('navis', 'navis.plotting', 'pygeos', 'trimesh'):
        logging.getLogger(name).setLevel(logging.ERROR)


def load_layer(path, kind, name, navis, budget):
    """A navis object for one archived file, or None if absent/unreadable."""
    if not os.path.exists(path):
        return None
    try:
        if kind == 'volume.swc':
            n = navis.read_swc(path)
            n.units = 'microns'
        else:
            import trimesh
            tm = trimesh.load(path, process=False, force='mesh')
            if not len(getattr(tm, 'faces', [])):
                return None
            raw = len(tm.faces)
            tm = decimate_for_display(tm, budget)
            if len(tm.faces) == raw and raw > HEAVY_FACES:
                # collected, not printed — printing here puts the note above the summary
                # line of the neuron it describes, which reads as belonging to the previous
                # one. main() prints it after.
                HEAVY.append(f'{name} has {raw:,} faces')
            n = navis.MeshNeuron(tm, units='microns')
        n.id = n.name = name
        return n
    except Exception:
        return None


#: A single plotly mesh3d beyond roughly this many faces makes a page slow to open.
#: We warn rather than shrink, so the page keeps showing the served geometry.
HEAVY_FACES = 500_000

#: heavy-mesh notes for the neuron currently being rendered; drained by main()
HEAVY = []


def decimate_for_display(tm, budget):
    """Shrink a mesh so the HTML opens. Display only — never written back."""
    n = len(tm.faces)
    if not budget or n <= budget:
        return tm
    try:
        import fast_simplification
        import trimesh
        v, f = fast_simplification.simplify(np.asarray(tm.vertices, np.float32),
                                           np.asarray(tm.faces, np.int32),
                                           target_reduction=1 - budget / n)
        return trimesh.Trimesh(vertices=np.asarray(v, float),
                              faces=np.asarray(f, int), process=False)
    except Exception:
        return tm


def _display_note(budget):
    if not budget:
        return 'meshes shown exactly as served'
    return (f'meshes decimated to {budget:,} faces FOR DISPLAY ONLY on this page — '
            f'unrelated to the served OBJ reported above')


def _obj_line(meta):
    """What happened to the OBJ we actually served — distinct from the display decimation.

    Without this the page reports the pre-decimation face count next to a note about a
    60k display budget, which reads as though the served mesh were decimated to 60k. It
    usually is not decimated at all: most BANC neurons are under the 4 MB wire budget.
    """
    n, note = meta.get('obj_faces'), meta.get('obj_note')
    if n is None:
        return '<span class="k">not written this run</span>'
    faces = meta.get('faces') or 0
    if note and 'budget' in note:
        return f'{n:,} faces — <b>not decimated</b> ({note})'
    if faces and n < faces:
        return f'{faces:,} &rarr; <b>{n:,} faces</b> — decimated ({note})'
    return f'{n:,} faces ({note})'


def status_table(meta, present, budget):
    rows = ''.join(
        f'<tr><td>{label}</td><td class="{"ok" if present[label] else "miss"}">'
        f'{"present" if present[label] else "MISSING"}</td></tr>'
        for label, *_ in LAYERS)
    return f"""
<style>
 body {{ font: 13px/1.5 -apple-system, system-ui, sans-serif; margin: 0; }}
 .hdr {{ padding: 10px 16px; border-bottom: 1px solid #ddd; }}
 table {{ border-collapse: collapse; margin: 6px 0; }}
 td {{ padding: 2px 10px 2px 0; }}
 .ok {{ color: #197; }} .miss {{ color: #c33; font-weight: 600; }}
 .k {{ color: #666; }}
</style>
<div class="hdr">
 <b>{meta.get('root')}</b> · {meta.get('region')} · {TEMPLATE.get(meta.get('region'), '')}
 &nbsp;<span class="k">status</span> <b>{meta.get('status')}</b>
 &nbsp;<span class="k">skeleton source</span> {meta.get('swc_source')}
 &nbsp;<span class="k">nodes/faces</span> {meta.get('nodes')}/{meta.get('faces')}
 <br><span class="k">served OBJ</span> {_obj_line(meta)}
 <table>{rows}</table>
 <span class="k">{meta.get('note') or ''}</span><br>
 <span class="k">{_display_note(budget)}</span>
</div>
"""


def render_one(d, out_dir, navis, flybrains, budget):
    meta_path = os.path.join(d, 'meta.json')
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    root = meta.get('root') or os.path.basename(d)
    region = meta.get('region') or os.path.basename(os.path.dirname(d))
    meta.setdefault('root', root)
    meta.setdefault('region', region)

    objs, present = [], {}
    tm = getattr(flybrains, TEMPLATE[region]).mesh
    vol = navis.Volume(np.asarray(tm.vertices), np.asarray(tm.faces), name=region)
    vol.color = (0.85, 0.85, 0.85, 0.10)
    objs.append(vol)

    for label, sub, fname, colour in LAYERS:
        n = load_layer(os.path.join(d, sub, fname), fname, f'{label}', navis,
                       budget)
        present[label] = n is not None
        if n is not None:
            n.color = colour
            objs.append(n)

    path = os.path.join(out_dir, f'{root}_{region}.html')
    if len(objs) == 1:
        # Nothing to compare; still emit a page so the batch has no silent holes.
        with open(path, 'w') as fh:
            fh.write(status_table(meta, present, budget) +
                     '<p style="padding:16px">No geometry archived for this neuron.</p>')
        return path, meta, present
    import plotly.offline as po
    fig = navis.plot3d(objs, backend='plotly', inline=False)
    # 'directory' emits a <script src="plotly.min.js"> reference instead of inlining
    # ~3.5 MB per page — but with output_type='div' plotly does NOT write that file, so
    # write_plotlyjs() below must put it in out_dir or every page renders blank.
    body = po.plot(fig, output_type='div', include_plotlyjs='directory', auto_open=False)
    with open(path, 'w') as fh:
        fh.write(status_table(meta, present, budget) + body)
    return path, meta, present


def write_plotlyjs(out_dir):
    """Write the one shared copy of plotly.min.js the pages reference.

    Bundled rather than pulled from a CDN: a Jenkins workspace artefact should render with
    no network. Keep this file beside the HTML when moving the directory around.
    """
    import plotly.offline as po
    p = os.path.join(out_dir, 'plotly.min.js')
    with open(p, 'w') as fh:
        fh.write(po.get_plotlyjs())
    return p


def write_index(rows, out_dir):
    head = ''.join(f'<th>{label}</th>' for label, *_ in LAYERS)
    body = ''
    for path, meta, present in rows:
        cells = ''.join(
            f'<td class="{"ok" if present[label] else "miss"}">'
            f'{"&#10003;" if present[label] else "MISSING"}</td>'
            for label, *_ in LAYERS)
        body += (f'<tr><td><a href="{os.path.basename(path)}">{meta.get("root")}</a></td>'
                 f'<td>{meta.get("region")}</td><td>{meta.get("status")}</td>'
                 f'<td>{meta.get("swc_source")}</td>'
                 f'<td>{meta.get("nodes")}/{meta.get("faces")}</td>{cells}</tr>')
    counts = {}
    for _, meta, _ in rows:
        counts[meta.get('status')] = counts.get(meta.get('status'), 0) + 1
    summary = '  '.join(f'{k}={v}' for k, v in sorted(counts.items()))
    p = os.path.join(out_dir, 'index.html')
    with open(p, 'w') as fh:
        fh.write(f"""<style>
 body {{ font: 13px/1.5 -apple-system, system-ui, sans-serif; margin: 24px; }}
 table {{ border-collapse: collapse; }}
 th, td {{ padding: 4px 10px; border-bottom: 1px solid #eee; text-align: left; }}
 .ok {{ color: #197; }} .miss {{ color: #c33; font-weight: 600; }}
</style>
<h2>BANC image comparison — {len(rows)} neuron(s)</h2>
<p>{summary}</p>
<table><tr><th>root</th><th>region</th><th>status</th><th>skel source</th>
<th>nodes/faces</th>{head}</tr>{body}</table>""")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--archive', required=True,
                    help='directory written by vfb-banc-images --archive')
    ap.add_argument('--out', default=None,
                    help='output directory (default: <archive>/html)')
    ap.add_argument('--display-faces', type=int, default=DISPLAY_FACES,
                    help='decimate each mesh to this many faces FOR DISPLAY ONLY. '
                         'Default 0 = show them exactly as served, which is the point of '
                         'the page. Set e.g. 200000 if an old v626 mesh is too large for '
                         'the browser to open (IMG-1: up to 44 MB observed).')
    args = ap.parse_args(argv)

    # 0 means off, and must stay 0: decimate_for_display and _display_note both
    # test it directly. An earlier sentinel of 10**12 made the page claim it had
    # decimated when it had not.
    budget = max(0, args.display_faces)

    import navis
    import flybrains
    navis.set_pbars(hide=True)
    hush_navis()

    out_dir = args.out or os.path.join(args.archive, 'html')
    os.makedirs(out_dir, exist_ok=True)
    dirs = sorted(d for d in glob.glob(os.path.join(args.archive, '*', '*'))
                  if os.path.isdir(d) and os.path.basename(d) != 'html')
    if not dirs:
        raise SystemExit(f'no neuron directories under {args.archive}')

    rows = []
    for i, d in enumerate(dirs, 1):
        HEAVY.clear()
        path, meta, present = render_one(d, out_dir, navis, flybrains, budget)
        miss = [k for k, v in present.items() if not v]
        print(f'  [{i}/{len(dirs)}] {meta.get("root")} {meta.get("region")} '
              f'{meta.get("status")}' + (f'  MISSING: {", ".join(miss)}' if miss else ''),
              flush=True)
        for note in HEAVY:
            print(f'        note: {note} — slow to open; --display-faces N reduces it '
                  f'for display only.', flush=True)
        rows.append((path, meta, present))

    js = write_plotlyjs(out_dir)
    idx = write_index(rows, out_dir)
    print(f'\n{len(rows)} page(s) -> {out_dir}\nindex: {idx}\n'
          f'shared js: {js} ({os.path.getsize(js) / 1e6:.1f} MB) — keep it beside the HTML')
    return 0


if __name__ == '__main__':
    sys.exit(main())
