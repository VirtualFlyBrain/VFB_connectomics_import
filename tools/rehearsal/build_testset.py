"""Pick a rehearsal batch: strided for representativeness, plus guaranteed crossers."""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kb import q

OUT = os.environ.get('REHEARSAL_DIR', os.path.expanduser('~/Documents/vfb_malecns_rehearsal'))
N_STRIDED = int(os.environ.get('N_STRIDED', 60))
N_CROSSER = int(os.environ.get('N_CROSSER', 20))
SITE, DATASET = 'male-cns_v1_0', 'Berg2025a'

rows = q(f"MATCH (d:DataSet {{short_form:'{DATASET}'}})<-[:has_source]-(i:Individual)"
         f"-[x:database_cross_reference]->(:Site {{short_form:'{SITE}'}}) "
         f"RETURN x.accession[0] AS acc, i.label ORDER BY acc")
rows = [(r[0], r[1]) for r in rows if r[0]]
print(f'{len(rows):,} neurons')

strided = rows[::max(1, len(rows) // N_STRIDED)][:N_STRIDED]
# Crossers must be named, not hoped for: only ~3.3% of the dataset occupies both regions,
# so a strided sample carries one or two — too few to prove the cut does the right thing.
cross = [(a, l) for a, l in rows if l and l.startswith(('DNa', 'DNp', 'DNg', 'DNd', 'DNb', 'AN'))]
random.Random(20261009).shuffle(cross)

seen, batch = set(), []
for acc, label in list(strided) + cross[:N_CROSSER]:
    if acc in seen:
        continue
    seen.add(acc)
    batch.append({'acc': acc, 'label': label,
                  'picked': 'crosser' if (acc, label) in cross[:N_CROSSER] else 'strided'})
os.makedirs(OUT, exist_ok=True)
json.dump(batch, open(os.path.join(OUT, 'testset.json'), 'w'), indent=1)
open(os.path.join(OUT, 'testset.roots'), 'w').write(','.join(b['acc'] for b in batch))
print(f'{len(batch)} neurons: {sum(b["picked"] == "strided" for b in batch)} strided + '
      f'{sum(b["picked"] == "crosser" for b in batch)} named crossers -> {OUT}')
