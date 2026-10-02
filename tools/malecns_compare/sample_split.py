"""How many maleCNS neurons actually have material in each region?

Coarsest rung only (lod3) — this asks *where* a neuron is, not what it should be served
at, so the cheapest mesh answers it. Determines how many of the 333,402 image folders the
rebuild would find spurious.
"""
import json, os, sys, time
import numpy as np
SP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP); sys.path.insert(0, os.path.join(SP, 'gil', 'src'))
os.environ.setdefault('BANC_FIELD_DIR', os.path.expanduser('~/Documents/banc_transform_fields'))
import warnings; warnings.filterwarnings('ignore')
import logging; logging.getLogger('navis').setLevel(logging.ERROR)
import navis, flybrains; flybrains.register_transforms()
from vfb_connectomics_import.images import connectomes, chain, sources
import newpipe as N
from kb import q

CX = connectomes.MALECNS
MIN_FACES = 100          # loader's materiality rule, faces side

rows = q("MATCH (d:DataSet {short_form:'Berg2025a'})<-[:has_source]-(i:Individual)"
         "-[x:database_cross_reference]->(:Site {short_form:'male-cns_v1_0'}) "
         "RETURN x.accession[0] AS acc, i.label ORDER BY acc")
accs = [(r[0], r[1]) for r in rows if r[0]]
print(f'{len(accs):,} maleCNS neurons in KB')
n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
step = max(1, len(accs) // n)
sample = accs[::step][:n]
print(f'sampling {len(sample)} evenly across the sorted list (stride {step})\n')

src = sources.MaleCnsBucket()
seqs = {r: chain.resolve(CX.region(r), use_baked=True)[0] for r in ('brain', 'vnc')}
out = []
t0 = time.time()
for i, (acc, label) in enumerate(sample, 1):
    m = src.mesh(acc, lod=3)
    if m is None:
        out.append({'acc': acc, 'label': label, 'brain': None, 'vnc': None}); continue
    row = {'acc': acc, 'label': label}
    for r in ('brain', 'vnc'):
        h = N.build(m, CX.region(r), seqs[r])
        row[r] = int(len(h.faces)) if h is not None else 0
    out.append(row)
    if i % 10 == 0:
        print(f'  {i}/{len(sample)}  [{time.time()-t0:.0f}s]')
    json.dump(out, open(os.path.join(SP, 'split_sample.json'), 'w'), indent=1)

ok = [r for r in out if r['brain'] is not None]
both = [r for r in ok if r['brain'] >= MIN_FACES and r['vnc'] >= MIN_FACES]
bonly = [r for r in ok if r['brain'] >= MIN_FACES and r['vnc'] < MIN_FACES]
vonly = [r for r in ok if r['vnc'] >= MIN_FACES and r['brain'] < MIN_FACES]
neither = [r for r in ok if r['brain'] < MIN_FACES and r['vnc'] < MIN_FACES]
print(f'\nof {len(ok)} with a mesh ({len(out)-len(ok)} absent):')
for name, g in (('both regions (crosser)', both), ('brain only', bonly),
                ('VNC only', vonly), ('neither', neither)):
    print(f'  {name:24s} {len(g):3d}  {100*len(g)/len(ok):5.1f}%')
spur = len(bonly) + len(vonly) + 2 * len(neither)
print(f'\nspurious channels per neuron, mean: {spur/len(ok):.2f}')
print(f'-> of 333,402 maleCNS image folders, ~{spur/len(ok)/2*100:.0f}% are spurious')
for r in neither[:5]:
    print('  neither:', r)
