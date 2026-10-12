#!/usr/bin/env python
"""Build the old-vs-new comparison page for the maleCNS panel."""
import html, json, os, sys
import numpy as np

SP = os.path.dirname(os.path.abspath(__file__))
import warnings; warnings.filterwarnings('ignore')
import logging; logging.getLogger('navis').setLevel(logging.ERROR)
import flybrains, fast_simplification
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

OLD_C, NEW_C, TPL_C = '#e8743b', '#2b7bba', '#9aa0a6'
TEMPLATE = {'brain': 'JRC2018U', 'vnc': 'JRCVNC2018U'}
CAM = {'brain': dict(eye=dict(x=0, y=0, z=-2.1), up=dict(x=0, y=-1, z=0)),
       'vnc':   dict(eye=dict(x=0, y=0, z=-2.1), up=dict(x=0, y=-1, z=0))}


def tpl_mesh(name, budget=4000):
    m = getattr(flybrains, name).mesh
    v, f = np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int32)
    if len(f) > budget:
        v, f = fast_simplification.simplify(v, f, target_reduction=1 - budget / len(f))
    return np.round(np.asarray(v, float), 1), np.asarray(f, int)


TPL = {k: tpl_mesh(v) for k, v in TEMPLATE.items()}


DISPLAY_DIR = os.environ.get('DISPLAY_DIR', 'display')
OUT_NAME = os.environ.get('OUT_NAME', 'malecns_lod_compare.html')


def load(tag):
    p = os.path.join(SP, DISPLAY_DIR, tag + '.npz')
    if not os.path.exists(p):
        return None
    d = np.load(p)
    return np.asarray(d['v'], float), np.asarray(d['f'], int)


def trace(vf, color, name, opacity=1.0, show=True):
    v, f = vf
    return go.Mesh3d(x=v[:, 0], y=v[:, 1], z=v[:, 2],
                     i=f[:, 0], j=f[:, 1], k=f[:, 2],
                     color=color, opacity=opacity, name=name, showlegend=show,
                     hoverinfo='name', flatshading=True, lighting=dict(ambient=0.55))


#: the template bounding box the pipeline trims to, (grid - 1) * spacing. Much larger than
#: the neuropil surface mesh -- and the served spurious copies sit outside BOTH, so a view
#: framed on either one alone silently crops them out of the picture.
TPL_BBOX = {'brain': np.array([[0., 627.37], [0., 293.46], [0., 173.0]]),
            'vnc':   np.array([[0., 263.57], [0., 515.60], [0., 152.40]])}


def scene_axes(region, meshes=()):
    """View range = template surface U template bbox U everything actually plotted.

    Framing on the template alone clipped 16 of 32 meshes in the first attempt, including
    every spurious copy -- the exact thing these pictures exist to show.
    """
    v, _ = TPL[region]
    lo, hi = v.min(0), v.max(0)
    lo = np.minimum(lo, TPL_BBOX[region][:, 0])
    hi = np.maximum(hi, TPL_BBOX[region][:, 1])
    for mv, _f in meshes:
        lo, hi = np.minimum(lo, mv.min(0)), np.maximum(hi, mv.max(0))
    pad = 0.03 * (hi - lo).max()
    ax = lambda i: dict(range=[lo[i] - pad, hi[i] + pad], visible=False,
                        showbackground=False)
    return dict(xaxis=ax(0), yaxis=ax(1), zaxis=ax(2),
                aspectmode='data', camera=CAM[region])


def figure(row):
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.01,
                        specs=[[{'type': 'scene'}, {'type': 'scene'}]],
                        subplot_titles=('brain — JRC2018U', 'VNC — JRCVNC2018U'))
    first, present = True, {}
    for col, region in enumerate(('brain', 'vnc'), start=1):
        fig.add_trace(trace(TPL[region], TPL_C, 'template', opacity=0.07, show=False),
                      row=1, col=col)
        old = load(f"old_{row['accession']}_{region}")
        new = load(f"new_{row['accession']}_{region}")
        present[region] = [m for m in (old, new) if m is not None]
        if old is not None:
            fig.add_trace(trace(old, OLD_C, 'served now', 0.55, show=first), row=1, col=col)
        if new is not None:
            fig.add_trace(trace(new, NEW_C, 'new pipeline', 1.0, show=first), row=1, col=col)
        first = False
    fig.update_layout(scene=scene_axes('brain', present['brain']),
                      scene2=scene_axes('vnc', present['vnc']),
                      height=420, margin=dict(l=0, r=0, t=26, b=0),
                      paper_bgcolor='rgba(0,0,0,0)',
                      legend=dict(orientation='h', y=1.08, x=0.0,
                                  bgcolor='rgba(0,0,0,0)'),
                      font=dict(family='ui-sans-serif,system-ui,sans-serif', size=12))
    for a in fig.layout.annotations:
        a.font.size = 12
    return fig


def mb(x):
    return f'{x:,.2f}' if x is not None else '—'


def main():
    rows = json.load(open(os.path.join(SP, 'display_index.json')))
    parts, totals = [], {'old': 0.0, 'new_raw': 0.0, 'new_gz': 0.0}

    tbl = ['<table><thead><tr>'
           '<th>neuron</th><th>region</th><th class="n">served now<br><span class="u">faces</span></th>'
           '<th class="n">served now<br><span class="u">MB on the wire</span></th>'
           '<th class="n">new<br><span class="u">LOD</span></th>'
           '<th class="n">new<br><span class="u">faces</span></th>'
           '<th class="n">new<br><span class="u">f/µm²</span></th>'
           '<th class="n">new<br><span class="u">MB raw</span></th>'
           '<th class="n">new<br><span class="u">MB gzip</span></th>'
           '<th class="n">inside template<br><span class="u">served → new</span></th>'
           '<th>verdict</th></tr></thead><tbody>']

    for row in rows:
        for ri, region in enumerate(('brain', 'vnc')):
            e = row['regions'].get(region, {})
            old, new = e.get('old'), e.get('new')
            expected = row['kind'] == 'crosser' or row['kind'] == region
            if old:
                totals['old'] += old['wire_mb']
            if new:
                totals['new_raw'] += new['obj_raw_mb']; totals['new_gz'] += new['obj_gz_mb']
            if new is None:
                verdict = ('<span class="good">dropped — nothing here</span>' if not expected
                           else '<span class="bad">MISSING — expected material</span>')
                newcells = '<td class="n">—</td>' * 5
            else:
                flags = []
                if new['f_per_um2'] > 200:
                    flags.append(f"<span class='warn'>{new['f_per_um2']:.0f} f/µm² &gt; ceiling</span>")
                if new['obj_raw_mb'] > 20:
                    flags.append(f"<span class='warn'>raw &gt; 20 MB</span>")
                if new.get('decimated'):
                    flags.append('decimated')
                if not expected:
                    flags.append('<span class="bad">unexpected material</span>')
                verdict = ' · '.join(flags) or '<span class="good">within policy</span>'
                newcells = (f"<td class='n'>lod{new['lod']}</td>"
                            f"<td class='n'>{new['faces']:,}</td>"
                            f"<td class='n'>{new['f_per_um2']:.1f}</td>"
                            f"<td class='n'>{mb(new['obj_raw_mb'])}</td>"
                            f"<td class='n'>{mb(new['obj_gz_mb'])}</td>")
            oi = old.get('inside_pct') if old else None
            ni = new.get('inside_pct') if new else None
            if ni is None:
                inside = (f"<span class='n'>{oi:.1f}%</span> → <span class='good'>—</span>"
                          if oi is not None else '—')
            elif oi is None:
                inside = f"— → {ni:.1f}%"
            else:
                d = ni - oi
                cls = 'good' if d > 2 else ('bad' if d < -2 else '')
                inside = (f"{oi:.1f}% → <span class='{cls}'>{ni:.1f}%</span>"
                          + (f" <span class='{cls}'>({d:+.0f})</span>" if abs(d) > 2 else ''))
            name = (f"<td rowspan='2'><b>{html.escape(row['label'])}</b>"
                    f"<span class='u'>MaleCNS:{row['accession']} · {row['kind']}</span></td>"
                    if ri == 0 else '')
            tbl.append(
                f"<tr>{name}<td>{region}</td>"
                f"<td class='n'>{old['full_faces']:,}</td><td class='n'>{mb(old['wire_mb'])}</td>"
                f"{newcells}<td class='n'>{inside}</td><td>{verdict}</td></tr>")
    tbl.append(f"<tr class='tot'><td colspan='3'>total, {len(rows)} neurons × 2 channels</td>"
               f"<td class='n'>{totals['old']:,.0f}</td><td colspan='3'></td>"
               f"<td class='n'>{totals['new_raw']:,.0f}</td>"
               f"<td class='n'>{totals['new_gz']:,.0f}</td><td></td>"
               f"<td>{totals['old'] / totals['new_raw']:.0f}× smaller raw, "
               f"{totals['old'] / totals['new_gz']:.0f}× gzipped</td></tr>")
    tbl.append('</tbody></table>')

    for i, row in enumerate(rows):
        fig = figure(row)
        inner = pio.to_html(fig, full_html=False, include_plotlyjs=('cdn' if i == 0 else False),
                            config={'displayModeBar': False})
        sub = []
        for region in ('brain', 'vnc'):
            e = row['regions'].get(region, {})
            old, new = e.get('old'), e.get('new')
            o = f"served {old['full_faces']:,} f / {old['wire_mb']:,.1f} MB" if old else 'none'
            n = (f"new lod{new['lod']} {new['faces']:,} f / {new['obj_raw_mb']:,.1f} MB"
                 if new else '<b>new: empty</b>')
            sub.append(f"<span><b>{region}</b> — {o} · {n}</span>")
        parts.append(
            f"<section><h3>{html.escape(row['label'])}"
            f"<span class='tag'>{row['kind']}</span></h3>"
            f"<div class='sub'>{' '.join(sub)}</div>{inner}</section>")

    page = TEMPLATE_HTML.format(table=''.join(tbl), figures=''.join(parts))
    out = os.path.join(SP, OUT_NAME)
    open(out, 'w').write(page)
    print(f'wrote {out}  ({os.path.getsize(out)/1e6:.1f} MB)')
    print(f"old total {totals['old']:,.0f} MB | new raw {totals['new_raw']:,.0f} MB "
          f"| new gz {totals['new_gz']:,.0f} MB")


TEMPLATE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>maleCNS: served now vs new pipeline</title><style>
:root{{color-scheme:light}}
body{{margin:0;padding:28px 22px 60px;font:14px/1.55 ui-sans-serif,system-ui,-apple-system,sans-serif;
color:#1a1d21;background:#fbfbfa;max-width:1180px;margin-inline:auto}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:34px 0 10px;
border-bottom:1px solid #e3e3e0;padding-bottom:5px}}
h3{{font-size:15px;margin:0 0 2px}} .lede{{color:#5a6066;margin:0 0 18px;max-width:72ch}}
.key{{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0 8px;font-size:13px}}
.key span{{display:flex;align-items:center;gap:6px}}
.sw{{width:12px;height:12px;border-radius:3px;display:inline-block}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;margin:10px 0 6px}}
th,td{{padding:5px 8px;border-bottom:1px solid #eceae6;text-align:left;vertical-align:top}}
th{{font-weight:600;color:#44494e;font-size:11.5px;border-bottom:1px solid #d8d6d2}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
.u{{display:block;color:#878d93;font-weight:400;font-size:11px}}
tr.tot td{{border-top:2px solid #d8d6d2;font-weight:600;background:#f5f4f1}}
.good{{color:#1a7f45}} .bad{{color:#b3261e;font-weight:600}} .warn{{color:#9a6200}}
section{{margin:22px 0 10px;padding:14px 0 0;border-top:1px solid #ededea}}
.tag{{font-size:11px;background:#eceae6;color:#5a6066;border-radius:3px;
padding:2px 7px;margin-left:9px;vertical-align:middle;font-weight:500}}
.sub{{color:#6b7177;font-size:12px;margin:2px 0 4px;display:flex;gap:20px;flex-wrap:wrap}}
.note{{background:#fff;border:1px solid #e6e4e0;border-left:3px solid #9a6200;
padding:11px 14px;margin:16px 0;border-radius:3px;font-size:13px}}
.note b{{color:#9a6200}}
.cap{{color:#6b7177;font-size:12px;max-width:86ch;margin:4px 0 0}}
code{{background:#f0eeea;padding:1px 4px;border-radius:3px;font-size:12px}}
</style></head><body>
<h1>maleCNS v1.0 — what is served now vs what the new pipeline would serve</h1>
<p class="lede">Eight neurons: four that cross the neck connective (three descending, one
ascending), two brain-only and two VNC-only. Orange is the file
<code>virtualflybrain.org</code> serves today; blue is what the new pipeline produces, with
the cut planes, declared transform chain and baked fields of
<code>connectomes.py</code> and the LOD rule of <code>docs/MESH_SIZING.md</code>. The
grey shell is the template.</p>
<div class="key">
<span><i class="sw" style="background:#e8743b"></i> served now</span>
<span><i class="sw" style="background:#2b7bba"></i> new pipeline</span>
<span><i class="sw" style="background:#9aa0a6"></i> template</span>
</div>
<div class="note"><b>Read the two panels as a pair.</b> A brain-only neuron should be
<i>absent</i> from the VNC panel and vice versa. Today every neuron appears, whole, in both
— that is IMG-2. The new pipeline's job is to put each half where it belongs and leave the
other panel empty.</div>
<h2>Per neuron</h2>
{table}
<p class="cap"><b>inside template</b> is the share of each mesh's <i>surface area</i> that
falls within the template's filled neuropil shell, sampled at 60,000 points on the
full-resolution mesh. The bounding-box trim both pipelines apply only proves a point is in
the <i>box</i>; IMG-3 is exactly the case where misplaced material passes that test, so the
box cannot be the check. A spurious whole-neuron copy in the wrong template scores 0.0%.</p>
<div class="note"><b>Meshes below are decimated for display only.</b>
They show placement and the split, not surface quality — the quality question is the
<code>f/µm²</code> and LOD columns above. Face counts and sizes in the table are the real
pipeline output.</div>
<h2>Old and new, together</h2>
{figures}
</body></html>"""

if __name__ == '__main__':
    main()
