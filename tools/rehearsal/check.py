"""Audit a rehearsal run. Every check is something that would be bad in production.

Checks 7 and 8 exist because the first version of this script asserted only that each
product FILE existed. An all-zero NRRD, an NRRD on the wrong grid, or a truncated OBJ would
all have passed — and a real `write_nrrd` bug (region.spacing vs region.template.spacing)
did pass, because the end-to-end runs before it had used --products swc,obj.
"""
import collections, csv, glob, json, os, sys

import numpy as np

OUT = os.environ.get('REHEARSAL_DIR', os.path.expanduser('~/Documents/vfb_malecns_rehearsal'))
LIVE, ARC = os.path.join(OUT, 'live'), os.path.join(OUT, 'archive')
PRODUCTS = ('volume.swc', 'volume_man.obj', 'volume.nrrd')
SWEPT = ('volume.obj', 'volume.dps.pkl')          # must be GONE after a successful swap
GRID = {'VFB_00101567': (1210, 566, 174), 'VFB_00200000': (660, 1290, 382)}

rows = list(csv.DictReader(open(os.path.join(OUT, 'report.csv'))))
batch = {b['acc']: b for b in json.load(open(os.path.join(OUT, 'testset.json')))}
fail, warn = [], []
by = collections.defaultdict(list)
for r in rows:
    by[r['status']].append(r)

print(f'{len(rows)} tasks')
for k in sorted(by):
    print(f'  {k:18s} {len(by[k]):4d}')
wrote = by['replaced'] + by['created']

print('\n1. every deleted file is in the archive, and the live folder is stripped')
for r in by['deleted_spurious']:
    d = os.path.join(ARC, r['region'], r['root'], 'old')
    if not (os.path.isdir(d) and os.listdir(d)):
        fail.append(f"{r['root']}/{r['region']}: DELETED with an empty archive")
    left = glob.glob(os.path.join(r['folder'], 'volume*')) + \
        glob.glob(os.path.join(r['folder'], 'thumbnail*'))
    if left:
        fail.append(f"{r['root']}/{r['region']}: delete left {[os.path.basename(p) for p in left]}")
print(f'   {len(by["deleted_spurious"])} checked')

print('\n2. every written folder is complete, stale files swept, old set archived')
for r in wrote:
    for f in PRODUCTS:
        if not os.path.exists(os.path.join(r['folder'], f)):
            fail.append(f"{r['root']}/{r['region']}: missing {f}")
    for f in SWEPT:
        if os.path.exists(os.path.join(r['folder'], f)):
            fail.append(f"{r['root']}/{r['region']}: stale {f} survived the swap")
    if r['status'] == 'replaced':
        d = os.path.join(ARC, r['region'], r['root'], 'old')
        if not (os.path.isdir(d) and os.listdir(d)):
            fail.append(f"{r['root']}/{r['region']}: replaced with an empty archive")
print(f'   {len(wrote)} checked')

print('\n3. no .partial files anywhere')
p = glob.glob(os.path.join(LIVE, '**', '*.partial*'), recursive=True)
if p:
    fail.append(f'{len(p)} .partial file(s) left behind')
print(f'   {len(p)} found')

print('\n4. named DN/AN crossers have material in both regions')
per = collections.defaultdict(dict)
for r in rows:
    per[r['root']][r['region']] = r['status']
both = 0
for acc, b in batch.items():
    if b['picked'] != 'crosser':
        continue
    got = {g for g, s in per.get(acc, {}).items() if s in ('replaced', 'created')}
    if got == {'brain', 'vnc'}:
        both += 1
    else:
        warn.append(f"{acc} {b['label']}: wrote only {sorted(got) or 'nothing'}")
n_cross = sum(1 for b in batch.values() if b['picked'] == 'crosser')
print(f'   {both} of {n_cross}')

print('\n5. no neuron lost its image in every region')
for acc, st in per.items():
    if all(s in ('deleted_spurious', 'no_source', 'error') for s in st.values()):
        fail.append(f'{acc}: no image left in ANY region ({st})')
print(f'   {len(per)} neurons')

print('\n6. errors')
for r in by['error']:
    fail.append(f"{r['root']}/{r['region']}: {r['note'][:110]}")
print(f'   {len(by["error"])}')

print('\n7. every NRRD is on the template grid and is not empty')
import nrrd
nz = []
for r in wrote:
    p = os.path.join(r['folder'], 'volume.nrrd')
    if not os.path.exists(p):
        continue
    ch = os.path.basename(r['folder'])
    try:
        d, _h = nrrd.read(p)
    except Exception as e:
        fail.append(f"{r['root']}/{r['region']}: NRRD unreadable ({e})"); continue
    if tuple(d.shape) != GRID[ch]:
        fail.append(f"{r['root']}/{r['region']}: NRRD grid {d.shape} != {GRID[ch]}")
    if d.dtype != np.uint8:
        fail.append(f"{r['root']}/{r['region']}: NRRD dtype {d.dtype}")
    n = int((d > 0).sum())
    nz.append(n)
    if n == 0:
        fail.append(f"{r['root']}/{r['region']}: NRRD is ALL ZERO")
if nz:
    nz.sort()
    print(f'   {len(nz)} read; non-zero voxels min {nz[0]:,} median {nz[len(nz)//2]:,} max {nz[-1]:,}')

print('\n8. every OBJ parses, is non-empty, and matches the reported face count')
for r in wrote:
    p = os.path.join(r['folder'], 'volume_man.obj')
    if not os.path.exists(p):
        continue
    n = sum(1 for line in open(p, 'rb') if line.startswith(b'f '))
    if n == 0:
        fail.append(f"{r['root']}/{r['region']}: OBJ has no faces")
    elif r.get('obj_faces') and int(float(r['obj_faces'])) != n:
        fail.append(f"{r['root']}/{r['region']}: OBJ has {n} faces, report says {r['obj_faces']}")
print(f'   {len(wrote)} checked')

print('\n9. nothing served above the density ceiling')
over = [r for r in rows if r.get('obj_f_per_um2') and float(r['obj_f_per_um2']) > 200]
for r in over:
    fail.append(f"{r['root']}/{r['region']}: served at {r['obj_f_per_um2']} f/um2")
print(f'   {len(over)} over 200 f/um2')

print('\n' + '=' * 70)
print(f'FAIL — {len(fail)} problem(s):' if fail else 'PASS — every check clean')
for f in fail[:25]:
    print('   ', f)
if warn:
    print(f'\n{len(warn)} warning(s) (a DN/AN that genuinely does not cross is fine):')
    for w in warn[:10]:
        print('   ', w)
sys.exit(1 if fail else 0)
