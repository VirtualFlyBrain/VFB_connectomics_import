# Rebuilding the maleCNS images — handover

State as of 2026-10-12. Everything described here is verified; what is *not* verified is
called out explicitly at the end. Read "Before you press go" even if you skip the rest.

---

## What is wrong, in one paragraph

maleCNS (`Berg2025a`) writes the **whole neuron into both templates, uncut**. Every neuron
gets two near-identical multi-megabyte files, and whichever one it does not belong in lands
outside that template entirely. `DL1_adPN_L` is served as 948,736 faces in JRC2018U *and*
948,694 faces in JRCVNC2018U — the same cell, 42 faces apart — with the VNC copy at
z 454.6–554.4 µm against a template that ends at z 152.4 µm, and y running negative. 80.4 MB
served for a cell that needs 33.4 MB once. This is `IMG-2` in [`ISSUES.md`](ISSUES.md).

**The registration was never wrong.** Measured on channels at the same LOD rung, the
rebuilt output matches what is served today to a median of **16 nm** in the brain and
**53 nm** in the VNC — the same order as each baked field's own interpolation error (below),
and far under one display voxel. The entire defect is the missing cut. This is the opposite
of BANC, where the new alignment genuinely moves.

---

## Scale

| | |
|---|---|
| maleCNS individuals in the KB | 166,701 |
| image folders (both templates) | 333,402 |
| brain-only / VNC-only / genuine crossers | **86.7% / 10.0% / 3.3%** |
| folders holding a file that should not exist | **~161,000** |

The split figures come from 60 neurons strided across the whole worklist, coarse probe mesh
only. They are consistent with the KB's own counts (52 DNa + 320 DNp + 860 DNg + ~1,018 AN0
≈ 1.4–3%), but the sample is small — treat 3.3% as "a few percent", not as a precise number.

On an 8-neuron comparison panel the rebuild took **2,151 MB → 362 MB** raw (87 MB gzipped),
with the four already-correct channels moving by ≤1 point of neuropil containment.

---

## What was verified, and how

**The baked fields, against the exact native chain** —
`python -m vfb_connectomics_import.images.verify_baked --connectome malecns --region brain|vnc`.
This had never been run before 2026-10-02. It pushes real neuron material through both the
baked field and the full multi-hop chain and compares per point:

| | points | mean | p95 | p99 | max | domain disagreement |
|---|---|---|---|---|---|---|
| brain → JRC2018U | 1,455,732 | **16.5 nm** | 31.2 | 40.9 | 120.1 | **0 / 0** |
| vnc → JRCVNC2018U | 277,898 | **74.8 nm** | 138.3 | 175.5 | 369.9 | **0 / 0** |

Judge against the **display** voxel, not the 8 nm source voxel: 519 nm for JRC2018U, 400 nm
for JRCVNC2018U. The worst brain point moves 23% of a voxel; the VNC mean is 19% of one.
Larger than BANC's reference (6.3 / 13.7 nm) because these fields collapse three and five
hops respectively *all the way to the U templates*, where BANC stops at the F templates and
leaves its tail hop live. Zero domain disagreement is the important column: the field never
invents a coordinate the real chain refuses, and the grid extents were sized correctly.

Needs CMTK (`streamxform`) and ~3.2 GB of H5 for the native side, which is exactly the
baggage the bake exists to remove — so it is a manual tool, not a CI test.

**The job end to end, against a mirror of the live images** — `tools/rehearsal/run.sh`.
A loader run against an empty tree is hollow: `had_image` is False, so `decide()` can never
return DELETE, `--archive` copies nothing, and the atomic swap degrades to a plain write.
The rehearsal downloads the real served files first, so deletion, archiving and replacement
all execute for real with nothing at risk.

Last result — 2026-10-09, 80 neurons (60 strided + 20 named crossers), 160 tasks, 3.9 min
at 1.48 s/neuron on 4 workers: **PASS, all nine checks, 0 errors.** 58 deleted spurious,
102 replaced, 20/20 crossers wrote both halves, live tree 4.1 GB → 949 MB. `--archive` was
separately verified as a genuine undo — restoring from it returned the mirror to its exact
baseline file count.

**Unit tests** — 54, up from 25. `tests/test_sizing.py` encodes the measured cases rather
than assertions: the giant fibre that busts a budget its prediction met, the 370 f/µm² that
the ceiling has to catch, and both of `decimate_mesh`'s old escape hatches.

---

## Before you press go

**1. Stage the baked fields.** They are not on the agent. One directory per connectome:

```
vfb-local-transforms/
├── banc_transform_fields/        543 MB   (plans.json / support.json are BANC leftovers;
│                                           nothing reads them, do not copy them across)
└── malecns_transform_fields/     244 MB
    ├── malecns_brain_2um.npy   159,667,328 B   md5 2649245e60c5fb1e8a4c66ba240fbcfa
    ├── malecns_brain_2um.json        1,012 B   md5 dbb505802d0f1c16531cc5c612a1f33b
    ├── malecns_vnc_2um.npy      96,449,624 B   md5 eeee35fa467a495122f309d618317857
    └── malecns_vnc_2um.json          1,115 B   md5 ccd13cf85123068b295b23b4888666f3
```

The `.json` sidecars are **not** optional. `BakedField` reads `source` and `target` from
them and refuses a field that does not match the hop it is being used for — which is what
stops a mis-staged file producing plausible garbage, and why a wrong copy fails at preflight
rather than 40,000 neurons in.

**2. Run a dry build first.** `connectome=malecns, region=both, dry_run=true`. Preflight
opens both fields, checks both sidecars against the declared hops, prints the chains and
stops. Seconds. Expect:

```
h5: none needed — malecns chains are baked end to end
chain [brain -> JRC2018U]:
    JRCFIB2022M -> JRC2018U  baked malecns_brain_2um.npy
    cut: z < 340,544 nm  (max z of brain neuropil ROIs, ME(R) ...)
chain [vnc -> JRCVNC2018U]:
    JRCFIB2022M -> JRCVNC2018U  baked malecns_vnc_2um.npy
    cut: z > 527,616 nm  (min z of VNC neuropil ROIs, LegNp(T1)(L) ...)
```

If a field is missing, in the wrong folder, truncated, or is BANC's under a maleCNS name,
that is where it fails — loudly, naming the resolved path and the file it looked for.

**3. Then an archived test batch.** `limit=200, include=10001,523769,42125,513235,
archive=true`. `limit` counts neurons, each with both regions, so that's 204 neurons and
~408 tasks. `include` guarantees neurons that cross the neck: three descending (DNp01 giant
fibre, DNa02_L, DNpe008) and one ascending (AN00A006), the same crossers as the
`tools/malecns_compare` panel. Descending neurons are around 1% of the dataset, so a strided
sample of 200 holds one or two by chance at best. These four are the known hard cases. Read
`report-*.csv` and open a few folders. `tools/rehearsal/check.py` is the list of things worth checking.

**4. Then shard the rest, with `archive=false`.** At 1.48 s/neuron, 333,402 tasks on 8
workers is ~17 hours, or about 2 hours across 8 shards. Resumable from the ledger at any
point, and no neuron is ever left without an image.

---

## The Jenkins build step

The "Execute shell" step is kept short on purpose; this section is its documentation.

**Parameters:** `connectome` (`banc` | `malecns`), `region`, `mode`, `workers`, and
optionally `shard`/`of`, `limit`, `include`, `roots`, `redo`, `no_delete_spurious`, `dry_run`,
`archive`. `KB_USER` / `KB_PASSWORD` come from the job's credentials binding. They are used
for one read-only Cypher query per region per build, which builds the work list. All
geometry is anonymous HTTPS from a public bucket.

**Python:** a python3.9 venv with `pip install -e ".[images]"`. Install the `images` extra,
not `.`. The extra pulls navis/flybrains/cloud-volume/skeletor and skips the connectivity
stack (neuprint-python, python-catmaid, fafbseg, vfb_connect), which this job does not use
and which needs python 3.10+.

**Environment the step sets or may set:**

| variable | what |
|---|---|
| `IMAGE_FIELD_DIR` | `$JENKINS_HOME/vfb-local-transforms/<connectome>_transform_fields`, chosen from `connectome`. Takes precedence over the legacy `$BANC_FIELD_DIR`, which the step `unset`s anyway |
| `FLYBRAINS_DATA` | Only BANC reads an H5 at run time (its JRC2018F→JRC2018U tail hop). Defaults to `~/flybrain-data`; otherwise the first BANC build fetches `JRC2018U_JRC2018F.h5` (717 MB) once. maleCNS is baked end to end and downloads nothing |
| `IMAGE_SWC_DIR` | Optional staged skeleton mirror, **per connectome**: BANC wants `<root>_skeleton.swc` from its bucket, maleCNS wants `<id>.swc` from `gs://flyem-male-cns`. A staged dir is authoritative, so a miss does **not** fall back to the bucket. Preflight warns if the mirror is incomplete. Leave unset unless staged |
| `IMAGE_WRITE` | Output root. Defaults to `/IMAGE_WRITE/` |

**Ledger and report:** `ledger-<connectome>-<region>[-<shard>of<of>].jsonl` and
`report-<same>-<BUILD_NUMBER>.csv` in the workspace. The same path on every build is what
makes it resume (see the ledger note below).

**compare.py** only runs when `archive=true` and `dry_run` is not set. It builds old-vs-new
HTML pages for test batches.

---

## Things that will bite

**`--mesh-budget-mb` changed meaning.** It used to be the "already small enough, leave it
alone" threshold (default 4). It is now the **hard cap** on a served OBJ (default 20), and
the old sense is `--mesh-skip-mb`. The loader exits with an explanation if given the old
value, so this fails loudly rather than quietly decimating every BANC mesh over ~444k faces.
Do not pass it.

**The ledger must not be shared between connectomes or shards.** It is the only record of
progress — file existence cannot indicate it, because almost every neuron already has an
image. Name it after the connectome, region and shard.

**`--archive` is off by default, and the full run deletes ~161,000 files.** Archiving
everything is ~3.4 TB (measured: 10.32 MB per channel across all eight served files).
Archiving one shard is ~430 GB. It is a genuine undo — verified — but it has to be asked for.

**Errors are now the signal.** A transient mesh-fetch failure used to be indistinguishable
from "no material here", which could delete a correct image; it now raises, and `error` is
deliberately not a terminal status so those neurons retry next build. Expect a non-zero
error count on a run this size. A *rising* one is a reason to stop, not a reason to relax
the check.

**The KB is untouched.** All 166,701 individuals keep channels on both templates, so
~161,000 will point at empty folders and VFB will still offer a VNC entry for a brain-only
cell with nothing behind it. Better than a wrong image, but somebody has to decide whether
those channels should go. That is curation, not this job.

**The new SWCs have no cell body.** `to_tree_neuron` in
[`loader.py`](../src/vfb_connectomics_import/images/loader.py) builds the `TreeNeuron` from
every SWC column except column 1, the node type (`1` = soma), so `navis.write_swc` writes no
soma tag. The soma *node* is still there; it just isn't tagged. Seen on the compare page for
14470 (brain, `published_skeleton`): 8,918 points either side, max 0.058 µm apart, a soma
sphere on the old skeleton and none on the new. This applies to every SWC the loader writes,
not just that neuron. **Deliberately left alone** (2026-10-14): users view the mesh, and
NBLAST ignores node types and radii, so no scores move. To fix it later, keep column 1 and
pass `soma=` (the node IDs where it is 1) to the `TreeNeuron`. First check the published
source skeletons actually tag a soma, which hasn't been verified. If they don't, the soma
has to come from the connectome's soma table instead.

---

## Known limits of the verification

- The rehearsal is **80 neurons**. Both bugs fixed on 2026-10-09 were invisible to a
  240-neuron run a week earlier. It covers the paths well; it cannot prove behaviour at
  333,402. Read the first shard's report before launching the rest.
- `verify_baked` compares the bake against **the chain it was built from**. If flybrains'
  `JRCFIB2022M → JRC2018M` were itself wrong, both routes would be wrong together and agree
  perfectly. That is a different question, answered by ROI-based validation against VFB's
  own reference domains.
- The density ceiling is tested against the density computed from the **probe's** area, not
  the served rung's own area. Measured on DL1_adPN_L and APL_R the two differ by +1.0% and
  −4.9% — not a systematic bias, and small against the ±50% neuron-to-neuron spread the
  policy already allows for. Deliberately left alone.
- The 20 MB budget is denominated in **gzipped** bytes, but `www.virtualflybrain.org` serves
  `volume_man.obj` as `application/octet-stream` with no `Content-Encoding` even when gzip
  and br are offered (checked 2026-10-02, nginx/1.20.2). So the real wire cost is the raw
  size. Rebasing is a decision, not a bug fix — see the `Budget` docstring in
  [`sizing.py`](../src/vfb_connectomics_import/images/sizing.py) for why the number stops
  making sense on a raw basis. The better fix is compression on the server.

---

## Where things live

| | |
|---|---|
| the job | `images/loader.py`, `--connectome malecns` |
| what differs per dataset | [`images/connectomes.py`](../src/vfb_connectomics_import/images/connectomes.py) — cuts, chains, ladder, DataSet/Site |
| which LOD, or decimate | [`images/sizing.py`](../src/vfb_connectomics_import/images/sizing.py) + [`MESH_SIZING.md`](MESH_SIZING.md) |
| the destructive part | `images/io.py` — no network, no transform, read it closely |
| field verification | `images/verify_baked.py` |
| rehearsal | [`tools/rehearsal/`](../tools/rehearsal/) |
| old-vs-new comparison | [`tools/malecns_compare/`](../tools/malecns_compare/) |
