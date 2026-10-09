"""Mirror the CURRENTLY SERVED files into a local write-root.

Without this the rehearsal is hollow: against an empty tree `had_image` is False, so
`decide()` can never return DELETE, `--archive` copies nothing and the atomic swap degrades
to a plain write. Every destructive path would go untested.
"""
import concurrent.futures as cf, json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kb import q

OUT = os.environ.get('REHEARSAL_DIR', os.path.expanduser('~/Documents/vfb_malecns_rehearsal'))
LIVE = os.path.join(OUT, 'live')
PREFIX = 'http://www.virtualflybrain.org/data/'
FILES = ('volume.swc', 'volume.nrrd', 'volume_man.obj', 'volume.obj',
         'volume.wlz', 'volume.dps.pkl', 'thumbnail.png', 'thumbnailT.png')
CH = {'brain': 'VFBc_00101567', 'vnc': 'VFBc_00200000'}

accs = {b['acc'] for b in json.load(open(os.path.join(OUT, 'testset.json')))}
folders = {}
for region, ch in CH.items():
    for acc, folder in q(
            f"MATCH (d:DataSet {{short_form:'Berg2025a'}})<-[:has_source]-(i:Individual)"
            f"<-[:depicts]-(ic:Individual)-[r:in_register_with]"
            f"->(tc:Template {{short_form:'{ch}'}}) "
            f"MATCH (i)-[x:database_cross_reference]->(:Site {{short_form:'male-cns_v1_0'}}) "
            f"RETURN x.accession[0], r.folder[0]"):
        if acc in accs:
            folders.setdefault(acc, {})[region] = folder
json.dump(folders, open(os.path.join(OUT, 'folders.json'), 'w'), indent=1)
print(f'{len(folders)} of {len(accs)} accessions have folders on both templates')

jobs = [(folder + f, os.path.join(LIVE, folder.replace(PREFIX, '').rstrip('/'), f))
        for regs in folders.values() for folder in regs.values() for f in FILES]

def fetch(job):
    url, dest = job
    if os.path.exists(dest) and os.path.getsize(dest):
        return 0
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        data = urllib.request.urlopen(url, timeout=300).read()
    except Exception:
        return 0                      # absent upstream is normal: wlz/obj are patchy
    open(dest, 'wb').write(data)
    return len(data)

total = 0
with cf.ThreadPoolExecutor(24) as ex:
    for i, n in enumerate(ex.map(fetch, jobs), 1):
        total += n
        if i % 200 == 0:
            print(f'  {i}/{len(jobs)}  {total/1e9:.2f} GB', flush=True)
print(f'mirrored {total/1e9:.2f} GB into {LIVE}')
