# Connectome import dashboard

A self-updating status board for every connectome VFB imports. It answers, at a
glance: **what stage is each import at, which version, is it live in the current
release, and does it need updating** — without anyone maintaining a board by hand.

**[Open the live dashboard →](https://virtualflybrain.github.io/VFB_connectomics_import/)**
(colour-coded HTML; an emoji `STATUS.md` is published alongside it).

Generated output is **never committed** — it is built into `site/` and published to
GitHub Pages by the [`Connectome dashboard`](../.github/workflows/dashboard.yml)
workflow (nightly + on push + manual). Nothing regenerating lives in git, so it can
never cause a merge conflict.

## How it reads

Rows are connectomes, columns are stages. Each cell has two parts:

| Part | Meaning |
|---|---|
| **Fill colour** | the work state |
| **Live dot** | whether it is actually live in the current release (checked in PDB) |

Fill: 🟩 done (built & uploaded) · 🟧 needs update · 🟥 in progress / not live ·
⬜ not started · 🔳 unknown (a probe couldn't tell).
Dot: 🔵 / ● live now · ⚪ / ○ done but **not live yet**.

So 🟩● = live; 🟩○ = uploaded to the data server but not yet loaded into the
running release; 🟧 = a newer upstream version exists.

## The one file you edit: `connectomes.yaml`

Everything volatile (done? live? needs update?) is **derived by probes at build
time — never typed by a human**, because manual status always goes stale. The
manifest holds only stable identity facts plus, per stage-cell, *how to check it*.

Each cell can define up to three probes:

```yaml
n2n:
  fill:   {type: owl_index, match: 'connectome_BANC_n2n\.owl'}  # colour
  update: {type: neuprint_upstream}                             # -> orange if newer
  live:   {type: pdb_cypher}                                    # -> the dot
```

### Probe types

| Type | Checks | Notes |
|---|---|---|
| `owl_index` | matching OWL live on `virtualflybrain.org/data/VFB/OWL/` | auto-discovers filenames from the directory listing |
| `repo_glob` | matching artifact present in this repo | e.g. a built TSV not yet uploaded |
| `jenkins` | a Jenkins job's status | running → in progress, success → done. Needs `meta.jenkins_base` + a `job` name |
| `neuprint_upstream` | is a newer version available upstream | *update* probe; needs `NEUPRINT_TOKEN` env |
| `gcs_versions` | newer version folder in a public GCS bucket | *update* probe; tokenless (BANC) |
| `pdb_cypher` | is it live in PDB right now | *live* probe (and a *fill* probe for neurons). Uses a stage-aware default query, or a `query:` you supply |
| `pdb_dataset` | does this version's `Site` (+ `DataSet`) record exist in **PDB**, and is it flagged `is_data_source`? | *fill* probe for the **Dataset record** column, as *published* |
| `kb_dataset` | same three-state check against the **KB** | *fill* probe for **Dataset record**. Prefer this — see below. Needs `KB_USER`/`KB_PASSWORD` |
| `kb_cypher` | is it curated in the KB right now | *fill* probe for cells where "done" ≠ "live", e.g. neurons loaded but not yet released |
| `manual` | a fixed `state:` | last resort — **will drift**, avoid |

Any probe that can't reach its endpoint degrades to 🔳 unknown; it never breaks
generation. A cell with **no probe wired** is also 🔳 unknown — never ⬜, because
"we never checked" is a different claim from "this work has not begun".

### The `dataset` column

`pdb_dataset` distinguishes three states, which matters because VFB versioning
moves the `Connectome` label and `is_data_source` flag onto each new release's Site:

| Result | State |
|---|---|
| no `Site` with that `short_form` | ⬜ not started |
| `Site` exists but `is_data_source` unset | 🟥 in progress — record built, not yet the current source |
| `Site` exists and is flagged | 🟩 done |

It reads `vfb_site`, plus `vfb_dataset` when present (absent → reported in the
tooltip, never counted as a failure). Note PDB returns `is_data_source` as a
single-element **list** (`[True]`), which the probe normalises.

**Use `kb_dataset`, not `pdb_dataset`, while a version is in preparation.**
Creating the `Site`/`DataSet` nodes is a *curation* step that happens in the KB;
PDB only catches up at the next release. Probing PDB for a target version that has
been built but not released returns ⬜ not started — i.e. claims nobody began work
that is in fact finished and waiting. The `live:` dot is what reports whether it
reached PDB. The same argument applies to **Neurons loaded** (`kb_cypher`).

The two stores **do not spell `short_form`s identically** — the KB keeps the
neuPrint hyphen (`male-cns_v1_0`), PDB underscores it (`male_cns_v1_0`). Give
`kb_site` / `kb_dataset` alongside `vfb_site` / `vfb_dataset` where they differ;
the KB probes fall back to the `vfb_*` keys when they don't (BANC, e.g., is
`BANC888` in both).

## ⚠️ Artifact filenames carry no version — and must (TODO)

Generated OWL is named `connectome_BANC_n2n.owl`, `connectome_manc.owl` and so on:
**no version token**. So `owl_index` matches whatever is on the data server and
reports 🟩 done regardless of which release it was built from. That makes every
`n2n`/`n2r` cell assert a freshness it cannot actually verify.

Nothing else recovers it either:

- **The file doesn't say.** `generate_n_n_template()` emits only `VFB:`/`FBbt:` IDs
  and `n2o:weight`. The `robot annotate` step sets an ontology IRI, not a version.
- **`last-modified` lies.** The BANC n2n OWL was dated 17-Aug-2026, two months
  *after* the newest TSV in this repo, yet was built from v626 data.
- Establishing provenance took an HTTP range request for 3 MB of the 451 MB file,
  extracting VFB IDs, and testing them against KB dataset membership — 0/400 were
  v888-only and 78/400 were neurons *dropped* in v888, matching the v626
  population split (80.5% / 19.5%) exactly. No probe can do that.

**Convention to adopt when each connectome is next rebuilt** — put the `Site`
`short_form` in the filename, since that is already the canonical version token in
the KB, in PDB, and in this manifest as `vfb_site`:

```
connectome_BANC626_n2n.owl   ->  connectome_BANC888_n2n.owl
connectome_male_cns_v1_0_n2n.owl
```

Then the `owl_index` match derives from the manifest instead of a hand-written
regex per connectome, and a stale artifact simply fails to match — so the cell
honestly reports that nothing exists for the target version. Also stamp it *inside*
the file, so it survives a rename:

```bash
robot annotate --ontology-iri http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl \
               --version-iri  http://virtualflybrain.org/data/VFB/OWL/BANC888_import.owl \
               --annotation dc:source "BANC v888 (Site BANC888, GCS neuron_connectivity/v888)"
```

### `built_version` — the interim workaround

Until then, `version` in the manifest is the version being **targeted**, which
diverges from reality mid-migration: BANC targets v888 while its OWL is v626-derived.
Setting `version: "888"` alone made the `n2n` cell go green *and* "up to date",
because `gcs_versions` compared the target against the bucket and found parity —
two probes agreeing a stale artifact was current.

So the update probes (`gcs_versions`, `neuprint_upstream`) compare against
`built_version` when present, falling back to `version`:

```yaml
version: "888"          # what we are migrating TO
built_version: "626"    # what the OWL on the server was actually built FROM
```

Bump `built_version` when the artifact is rebuilt; **delete the field entirely once
filenames carry the version**, as `owl_index` will then discriminate unaided.

## Common edits

- **Add a connectome** → append an entry under `connectomes:` with its
  `vfb_site` (must match a live PDB Site short_form) and a probe per stage.
- **Add a stage/column** → add one line under `stages:` and a `fill` probe for it
  on each connectome.
- **Wire skeleton status** → set `meta.jenkins_base` and each `skel.fill.job`.
- **Wire a live check for a new column** → add `live: {type: pdb_cypher, query: "..."}`
  (or rely on the built-in defaults for neurons / n2n / n2r).

## Run locally

```bash
pip install pyyaml certifi
python dashboard/generate.py
# writes dashboard/site/index.html and dashboard/site/STATUS.md (gitignored)
open dashboard/site/index.html
```

## How the live check works

`pdb_cypher` POSTs Cypher to `pdb.virtualflybrain.org/db/data/transaction/commit`
(public, no auth) and treats a non-zero count as "live". Default queries:

- **neurons** — neurons cross-referenced to the connectome's `Site`
- **n→n** — `synapsed_to` edges among that Site's neurons
- **n→r** — `has_pre/postsynaptic_terminal_in` edges among that Site's neurons

PDB is the source of truth for `vfb_site` short_forms — if a live dot is missing
where you expect one, check the Site name against the live list:

```
curl -s -X POST https://pdb.virtualflybrain.org/db/data/transaction/commit \
  -H 'Content-Type: application/json' \
  -d '{"statements":[{"statement":"MATCH (s:Site) RETURN s.short_form ORDER BY s.short_form"}]}'
```

## Scope: progress, not correctness

This dashboard answers "how far has each connectome got?". It does **not** check whether
what was built is *right* — a cell is green when the artifact exists, regardless of its
contents. Known correctness defects are tracked in [`../ISSUES.md`](../ISSUES.md).

Some of those are automatable and could become probes later (e.g. sampling served
`volume_man.obj` sizes and flagging a connectome whose meshes are too large to display —
IMG-1). Add them as new stage columns if so; a cell should never turn green on a check the
probe cannot actually make.

## How VFB dataset updates work (reference)

Canonical docs: **<https://virtualflybrain.org/docs/data/em/versioning/>** — read this
before extending the version/live logic.

For the *identity and curation* rules these mechanics sit on top of — root IDs as versions
rather than identities, why curation is re-derived rather than carried, when an image can be
reused, what `term_replaced_by` is for — see **[`../VERSIONING.md`](../VERSIONING.md)**.
That file also records the traps that produced wrong answers here (mtime as a version
signal; KB vs PDB short_form spelling; matching Templates by `label`).

The mechanics that matter for the dashboard:

- **Each release is a new `Site` + `DataSet`.** A version bump creates new nodes; it
  does not overwrite the old ones in place. So a version's identity lives in its
  `Site` short_form (e.g. `male_cns_v0_9` → `male_cns_v1_0`).
- **The *current* version is flagged**, not just present. The `Connectome` label and
  the `is_data_source` flag move from the old Site to the new one, marking it the
  authoritative source. → The most reliable "what version is live now" signal is the
  Site carrying `is_data_source` / the `Connectome` label, **not** merely any Site
  whose short_form exists. (v2 should query for that flag rather than guess short_forms.)
- **Old → new is linked** by a `term_replaced_by` edge — that's the upgrade chain.
- **Connectivity and images are replaced** with edges from the new data for neurons
  that are not deprecated. Deprecated neurons keep resolvable IDs but are excluded
  from connectivity results.

Implication: the earlier "in-place update under the same short_form" worry is largely
moot for VFB-loaded data (new Site per release) — but the *source-side* version
(neuPrint dataset key, CAVE materialization, BANC bucket) is still what tells us a new
release exists upstream before VFB has loaded it.

## Security note

`NEUPRINT_TOKEN` must be a GitHub **repo secret**, never committed. (The import
scripts under `src/` currently contain hardcoded neuPrint tokens — those should be
rotated and moved to env vars / secrets.)

**TLS.** `probes.py` verifies certificates against certifi's CA bundle, falling
back to an *unverified* connection only when the local trust store can't validate
the cert — a python.org macOS build ships with **zero** roots, and without the
fallback every probe would fail there. That trade is acceptable for the public
read-only endpoints (worst case: a wrong cell colour) but **not** for a request
carrying a credential, so `_urlopen` refuses to retry unverified when it sees an
auth header and raises `UnverifiedCredentialError` instead. The upstream check
then degrades to 🔳 unknown rather than transmitting the token to an
unauthenticated peer. Install `certifi` (it's in `dashboard/requirements.txt`) and
the fallback is never reached.

**KB credentials.** The KB (curation database, where records are authored before
release) wants HTTP Basic — `Basic realm="Neo4j"` — unlike public read-only PDB.
To enable KB probes, add two **repo secrets** under
*Settings → Secrets and variables → Actions*:

| Secret | Notes |
|---|---|
| `KB_USER` | use a **read-only** account |
| `KB_PASSWORD` | rotate independently of the user |

Locally, put the same keys in a gitignored `.env` at the repo root; `load_dotenv()`
in `generate.py` reads it with stdlib only, and **real environment variables always
win** so a stale local file can never shadow a CI secret. Both probes degrade to
🔳 unknown when the secrets are absent, so forks — which never receive secrets —
still build a dashboard.

**Cypher is write-guarded.** `connectomes.yaml` accepts arbitrary `query:`
strings. That is harmless against public PDB, but the same code path carries KB
credentials, so `_assert_read_only()` rejects any statement containing `CREATE`,
`MERGE`, `DELETE`, `DETACH`, `SET`, `REMOVE`, `DROP`, `FOREACH`, `LOAD`,
`TERMINATE`, `GRANT`, `REVOKE` — **or `CALL`**, which is how such a denylist would
otherwise be bypassed (`apoc.cypher.runWrite`, `apoc.do.when`). It is enforced
inside `_post_json()`, so a new probe cannot forget to call it. Word-boundary
matching keeps `DataSet`, `is_data_source` and `database_cross_reference` from
tripping it. Use a read-only account anyway — this guard should not be the only
thing standing between a YAML edit and a write.

**Server-side query budget.** Every Cypher POST carries
`max-execution-time: 60000`. A client timeout only ends our half of the
conversation — the transaction keeps running on PDB. Set above the 25s client
timeout on purpose, so it can only ever kill work we've already abandoned.
