"""Resolve the comparison panel: VFB ids -> accession + per-region served folder."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kb import q

CHANNEL = {'brain': 'VFBc_00101567', 'vnc': 'VFBc_00200000'}

# label prefix, exact accession, and what we expect it to be — the expectation is
# recorded so the render can show "crosser" cases failing or working, not just pictures.
PANEL = [
    ('VFB_jrmc30my', 'DNp01(GF)_R',       '10001',  'crosser'),   # giant fibre; size stress
    ('VFB_jrmc37m0', 'DNa02_L',           '523769', 'crosser'),
    ('VFB_jrmc30s1', 'DNpe008(PS225)_R',  '42125',  'crosser'),
    ('VFB_jrmc3g14', 'AN00A006_M',        '513235', 'crosser'),   # ascending
    ('VFB_jrmc37im', 'DL1_adPN_L',        '10359',  'brain'),     # face-for-face reference
    ('VFB_jrmc3hpl', 'APL_R',             '10540',  'brain'),     # largest area; LOD stress
    ('VFB_jrmc20f5', 'MNad06_R',          '803562', 'vnc'),
    ('VFB_jrmc20eq', 'MNad03_L',          '810086', 'vnc'),
]

def resolve():
    ids = ','.join(f"'{v}'" for v, *_ in PANEL)
    out = {}
    for region, ch in CHANNEL.items():
        rows = q(f"MATCH (i:Individual)<-[:depicts]-(ic:Individual)-[r:in_register_with]"
                 f"->(tc:Template {{short_form:'{ch}'}}) WHERE i.short_form IN [{ids}] "
                 f"RETURN i.short_form, r.folder[0], r.filename[0]")
        for sf, folder, fn in rows:
            out.setdefault(sf, {})[region] = {'folder': folder, 'filename': fn}
    recs = []
    for sf, label, acc, kind in PANEL:
        got = out.get(sf, {})
        for region in CHANNEL:
            d = got.get(region)
            if d and str(d['filename']) != acc:
                raise SystemExit(f'{label}: KB filename {d["filename"]!r} != accession {acc}')
        recs.append({'vfb': sf, 'label': label, 'accession': acc, 'kind': kind,
                     'folders': {r: got[r]['folder'] for r in CHANNEL if r in got}})
    return recs

if __name__ == '__main__':
    recs = resolve()
    json.dump(recs, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'panel.json'), 'w'), indent=1)
    for r in recs:
        print(f"{r['label']:22s} {r['accession']:>7s} {r['kind']:8s} "
              f"{sorted(r['folders'])}")
        for reg, f in sorted(r['folders'].items()):
            print(f"      {reg:5s} {f}")
