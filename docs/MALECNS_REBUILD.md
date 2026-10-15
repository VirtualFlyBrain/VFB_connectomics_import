# Rebuilding the maleCNS images — handover

State as of 2026-10-15. **The full run is under way**: one build, `region=both`,
`workers=40`, `archive=false`, started 15 Oct, about 24 h at 0.26 s/task. Everything
described here is verified; what is *not* verified is called out explicitly at the end.
Read "Before you press go" even if you skip the rest, and "After the run" before telling
anyone it's done.

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

**On the live job, 2026-10-14/15.** A 100-neuron test batch (`limit=100, archive=true`,
190 tasks; ten had one region already done from an earlier batch): 95 replaced, 95 deleted
spurious, 0 errors, every skeleton `published_skeleton`, 0 meshes needing decimation. A
neck-crossing neuron (`jrmc/02fc`) had both halves replaced. The compare pages matched the
old images apart from the cut, and the kept thumbnails still match the new meshes.

What the batch showed that isn't in the rehearsal:
- **About 30% of replaced meshes are served at `lod2`** (32–58 f/µm²) rather than `lod1`
  (149–200), because their `lod1` would bust the 200 f/µm² ceiling. That's the policy
  working, but it's a 4–5× drop in surface detail, mostly on neurons with a lot of
  skeleton for a small mesh (e.g. 73143: 4,044 nodes → 19,908 faces). If anyone reports a
  coarse-looking neuron, this is the first thing to check (`lod2` in the log line).
- **The largest served meshes are 0.9–1.45 M faces** (10556 brain: 1,445,910), all `lod1`
  and within policy. See the gzip limit below for why that's a big download.
- **VNC replacements take about twice as long** as brain ones (28–38 s vs 12–20 s per task).
- **Most replaced folders had no `volume.dps.pkl`** to sweep (`-1` in the log rather than
  `-2`). See "After the run".

**Unit tests** — 62 across `test_images.py` and `test_sizing.py`, up from 25.
`test_banc_query.py` needs `vfb_connect` and is skipped where that isn't installed. `tests/test_sizing.py` encodes the measured cases rather
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

**4. Then run the rest, with `archive=false`.** One build with more workers is simpler than
sharding: one ledger, one log. The `s/neuron` figure in the log is wall-clock time per
**task** with all workers running (elapsed / tasks), so the total time is just tasks × that
figure; don't divide by the worker count again. (An earlier version of this note did, and
got ~17 h.) Measured on 2026-10-15, `archive=false`, 24 workers on the dedicated server:

| workers | s/task | 333k tasks |
|---|---|---|
| 8 | 0.92 | ~85 h |
| 24 | 0.34 | ~32 h |
| 40 | 0.26 | **~24 h** |

8 → 24 was close to linear; 24 → 40 gave 1.3× for 1.67× the workers, so 40 is about where
it stops paying. Memory peaked at 17 GB at 40 workers. If going higher anyway, watch
whether s/task keeps falling and whether the `error=` count starts climbing. Archiving
costs roughly 1.6× (1.49 s/task at 8 workers in the test batches).

Resumable from the ledger at any point, including after changing `workers`, and no neuron
is ever left without an image.

**`empty_here` after a restart is expected.** Tasks still running when a build is aborted
can finish deleting a spurious image before the ledger records them. The rerun finds an
empty folder and records `empty_here`, which is the correct end state. Expect about as many
as were in flight at each abort (10 after two restarts on 15 Oct). A count that keeps
climbing through the run would be new.

**The memory graphs disagree, and that's fine.** At 40 workers the host showed ~17 GB used
while Rancher showed the Jenkins container at 80–120 GB and climbing. The container figure
includes the kernel's file cache: every mesh downloaded and every file written to the NAS.
The host's "used" leaves that out. The kernel frees it on demand, so it isn't a leak. The
network graphs split the same way: NAS writes show on the host (spikes to ~570 Mbps), and
only the downloads show on the container.

---

## The Jenkins build step

The "Execute shell" step is kept short on purpose; this section is its documentation.

**Parameters:** `connectome` (`banc` | `malecns`), `region`, `mode`, `workers`, and
optionally `shard`/`of`, `limit`, `include`, `roots`, `redo`, `no_delete_spurious`, `dry_run`,
`archive`. `limit` counts **neurons**, each with all of its regions. `include` and `roots`
are string parameters holding comma-separated root IDs (or `@file`), passed as
`${include:+--include "$include"}`. `KB_USER` / `KB_PASSWORD` come from the job's credentials binding. They are used
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

**For whoever owns the thumbnail job (Robbie): check it against the empty folders.**
Replaced images keep their thumbnails on purpose (`io.py`: `thumbnail*` goes briefly out of
sync). The new meshes look the same at thumbnail size, and thumbnails are clipped to the
template, so the updater just redoes them and nobody notices. Spurious images lose their
thumbnails along with everything else (`remove_all` sweeps `volume*` and `thumbnail*`). So
the only visible breakage is those ~161,000 emptied channels: the KB still points at them,
and the site shows a missing thumbnail. What happens next depends on how the thumbnail job
finds its work. If it looks for folders with a volume but no thumbnail, it skips them. If
it goes through the KB's channels, it will hit ~161,000 empty folders, and may error on
each or keep retrying. Not this job's problem to fix, but check before the full run lands.

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

**The log says `s/neuron` but counts tasks.** With `region=both` a neuron is two tasks, so
"332,025 left" is about 166,000 neurons. The numbers are right; only the label is off.

**Each region downloads the neuron separately.** A task is one neuron in one region, and
each fetches the skeleton and meshes itself. So with `region=both` every neuron is
downloaded twice. Fixing it means one task per neuron building both halves, which changes
how the ledger records progress. Not done: at 0.26 s/task the run fits in a day anyway.

---

## After the run

**1. The web cache will hide the result.** `www.virtualflybrain.org` serves `/data/` through
a cache (`X-Cache: HIT`, not Cloudflare) with `Cache-Control: max-age=31536000`. On 15 Oct,
`jrmc/02fc`'s new 23.4 MB and 68.8 MB meshes were on disk, but a plain download still
returned the old 117 MB and 118 MB files (`Last-Modified` Nov 2025 and Aug 2026). The same
URL with `?cb=<anything>` returned the new ones. So until the cache for `/data/VFB/i/` is
cleared, users keep the old meshes, and deleted spurious files may still be served if they
were cached. Browsers also keep their copies for a year, which only a shorter `max-age` or
versioned URLs fixes. This is for whoever runs the VFB web servers (Robbie), not this job.
Check the files on disk, or with a cache-busting query, before deciding something didn't
work.

**2. The thumbnail job** needs checking against the emptied folders. See "Things that
will bite".

**3. Rerun the NBLAST dotprops cache** (`VFB_similarity_import`, `CACHE.md` "First run").
It notices every replaced SWC and rebuilds its dotprops. Single-region neurons should come
out unchanged and not be rescored; neck-crossers' halves are now cut, so they will be. Any
spurious image it had cached now has no SWC and gets dropped. If that's over 10% of a
template's cache, its drop guard stops it on purpose; check its run log, then rerun with
`MAX_DROP_FRACTION=1`. That most folders here had no `volume.dps.pkl` suggests many maleCNS
channels were never in that cache, so the drop may well be smaller. Run it after this job
finishes, not during: neurons it rebuilt early would just be rebuilt again.

---

## Known limits of the verification

- The rehearsal is **80 neurons** and the live test batches a few hundred. Both bugs fixed on
  2026-10-09 were invisible to a 240-neuron run a week earlier. They cover the paths well;
  they cannot prove behaviour at 333,402. Read the full run's summary before calling it
  done: errors, `empty_here`, and the replaced/deleted split.
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
