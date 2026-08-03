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
| `pdb_dataset` | does this version's `Site` (+ `DataSet`) record exist, and is it flagged `is_data_source`? | *fill* probe for the **Dataset record** column |
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

## How VFB dataset updates work (reference)

Canonical docs: **<https://virtualflybrain.org/docs/data/em/versioning/>** — read this
before extending the version/live logic. The mechanics that matter for the dashboard:

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
