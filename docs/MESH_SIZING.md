# Mesh sizing: which LOD, or decimate?

How a neuron's served OBJ is brought to a displayable size. Companion to
[`DECIMATION.md`](DECIMATION.md), which settled *how* to decimate; this settles *whether*
to, and what to do instead when the publisher ships their own resolution ladder.

Measured 2026-09-15/16 on maleCNS v1.0. Everything below is in **JRC2018U / JRCVNC2018U
micrometres** — the space the OBJ is served in, and the space hemibrain's 37 f/µm² is
quoted in. Source-space area is **1.78×** template-space area for maleCNS, so a
source-space f/µm² compares to nothing in `ISSUES.md`; getting this wrong makes every
density in IMG-1 look 1.8× too small.

---

## The policy

> **Serve the finest rung the publisher ships that fits the wire budget. Reprocess only
> when nothing they ship fits.**

This is deliberately **not** quality-optimal — see "the method test" below, where our own
decimation beats the published rung at equal file size. It is *responsibility*-optimal: we
serve their geometry, unaltered, and own only the choice of which one. Anyone re-deriving
the quality argument will conclude the rule is a mistake; it isn't, it is a different
objective.

---

## The rule

**Per dataset, measured once:**

1. Does the source publish a ladder? `info` gives `@type: neuroglancer_multilod_draco`;
   the *per-segment* manifest gives `num_lods`. No ladder → decimate (this is BANC, LOD 0
   only).
2. Sample ~100 neurons and measure f/µm² per rung. If a rung's density spread (p95/p5)
   exceeds ~2×, that rung is not a coherent quality level — different neurons would be
   served at visibly different quality — so decimate instead, which targets density
   directly.
3. Record the ladder in `connectomes.py` **with its provenance**, next to `Cut` and `Hop`.

**Per neuron:**

1. Fetch the coarsest rung (cheap) → surface area per region.
2. Discard rungs above the **ceiling, 200 f/µm²**. Nothing displays better above it:
   the densest thing VFB serves anywhere is OpticLobe at 459, and hemibrain displays
   acceptably at 37.
3. Predict each remaining rung: `area × density × 9 bytes/face`. Pick the finest
   predicted to fit the **20 MB budget**.
4. Fetch it, then **check the actual face count and step down a rung if it busts the
   budget.** The prediction chooses; the measurement decides. See "why verification is
   not optional".
5. Nothing fits → decimate the finest admissible rung to the budget. This is the only
   path that reprocesses.

**Constants:** ceiling 200 f/µm², budget 20 MB, 9 bytes/face (measured 7.6–8.7 across
every mesh in this document; conservative, i.e. it errs toward the coarser rung).

---

## maleCNS v1.0: the measured ladder

`gs://flyem-male-cns/v1.0/segmentation`, `neuroglancer_multilod_draco`, 4 rungs at scales
1/2/4/8. Face reduction per step is **6.7× / 5.8× / 4.85×**, not the 7× guessed in
`sources.py`.

| rung | APL_R f/µm² | DL1_adPN_L f/µm² | APL_R faces | gzip 3 dp |
|---|---|---|---|---|
| lod0 | 1302.4 | 1281.6 | 80,049,619 | 588.32 MB |
| **lod1** | **198.6** | **194.2** | 11,971,252 | 88.43 MB |
| lod2 | 34.1 | 32.1 | 2,065,220 | 15.73 MB |
| lod3 | 6.7 | 6.1 | 425,704 | 3.37 MB |

**lod1 is what VFB serves today.** APL_R's served file is 11,971,252 faces over
60,267 µm² — IMG-1's maleCNS row reproduced exactly. So the existing job already asks for
a rung, IMG-1's "maleCNS source density 198 f/µm²" *is* lod1, and there is a rung above it
6.7× finer again that nobody should ever serve.

lod0 fails the ceiling. lod2 sits essentially on hemibrain's 37.

### The population is small; the problem is a tail

100 neurons strided across the full 166,701-neuron KB worklist, 101 served files, **zero
missing meshes**:

| | lod1 wire | area |
|---|---|---|
| median | **0.93 MB** | 549 µm² |
| p90 | 3.70 MB | 2,217 µm² |
| p99 | 11.81 MB | 6,629 µm² |
| max | 18.57 MB | 10,653 µm² |

Under a 20 MB budget **101 of 101 stay on lod1**. IMG-1 reads as though every maleCNS OBJ
is broken; the median is under 1 MB and lod1 is already right nearly everywhere. The valve
engages above ~11,300 µm², which is well under 1% of files — and a random sample cannot
resolve that tail (APL is 60,267 µm², 6× beyond anything sampled).

### Consistency — checked, because the rule depends on it

| | median | p5–p95 | min–max | spread |
|---|---|---|---|---|
| lod2 f/µm² | 32.2 | 27.2–39.3 | 24.7–48.7 | 1.44× |
| lod3 f/µm² | 6.78 | 5.26–8.41 | 4.80–9.38 | 1.60× |

- **Depth is uniform**: 4 rungs for 100/100 neurons. Read it from the manifest anyway —
  `num_lods` is per-segment, and a dataset where small cells get fewer rungs is entirely
  plausible since the chunking is spatial.
- **No drift with size**: r(log area, lod2 density) = −0.33, area-quartile medians
  34.1 | 32.9 | 30.9 | 32.0. One constant per rung is legitimate here.
- Step ratio lod2/lod3 varies 4.08–7.74×, so ratios are not a substitute for measurement.

### Why verification is not optional

The ±50% density spread is not theoretical. In a 10-neuron prototype run it bit
immediately: **DNp01(GF)_R brain**, area 10,653 µm², predicted at 196 f/µm² to be
18.79 MB — a fit. Its actual lod1 half is **2,610,604 faces = 23.50 MB**, because the
giant fibre runs at **245 f/µm²**. The rule stepped down to lod2 and wrote 3.20 MB. A
predict-only rule ships a 23.5 MB file and never knows.

We fetch the mesh anyway, so the exact face count is free before the OBJ is written.
Enforce the budget on the measurement, never the prediction. A wrong or absent calibration
then costs one extra fetch, never a bad file — which is also what lets a brand-new dataset
run with no calibration at all.

---

## The method test: their ladder vs our decimation

Both mechanisms brought to the **same face count** on DL1_adPN_L, scored against lod0 as
ground truth — 150,000 points sampled on the reference surface, exact point-to-triangle
distance (no rtree; KD-tree over triangle centroids, k=24):

| candidate | faces | f/µm² | mean | p95 | p99 | **>250 nm** | area kept | gzip |
|---|---|---|---|---|---|---|---|---|
| lod1 (served today) | 902,171 | 194.2 | 10.6 nm | 24.0 | 62.2 | 0.03% | 95.0% | 7.58 MB |
| lod1 → 100 f/µm² (ours) | 464,592 | 102.4 | 12.8 nm | 29.2 | 124.4 | 0.10% | 92.8% | 4.04 MB |
| **lod2 (their rung)** | 144,804 | 32.1 | 33.3 nm | 87.1 | 259.7 | **1.09%** | 92.3% | 1.27 MB |
| **lod1 → same count (ours)** | 144,803 | 34.1 | 20.7 nm | 55.4 | 183.5 | **0.38%** | 86.8% | 1.34 MB |

**Quadric decimation is ~1.6× more accurate than the published rung at equal size.** They
fail differently, and both failures are visible: the rung *blobs* — it keeps 92.3% of the
area but puts it in the wrong place, so dense arbors turn to lumps — while decimation
*smooths*, stripping corrugation (86.8% of area) while staying closer to the true surface,
which pinches or gaps the finest twigs.

We serve the rung anyway, per the policy. Decimation costs 0.35–0.42 s/neuron, so this is
not a cost argument; it is a scope argument.

**Corollary: `lod1` is the right decimation input, not lod0.** Decimating from lod0 could
recover at most ~2 nm (our dec100 is 12.8 nm against lod1's own 10.6 nm floor) for a 6.9×
larger fetch.

Two caveats on the table. `2V/A` was dropped from it deliberately: these meshes are not
watertight, so trimesh's volume is unreliable, and the "tube fattening" story it appears to
tell (214 → 335 nm) should not be read. And the ladder is **proportional, not absolute** —
mean edge on the small cell is *shorter* than on APL at every rung (lod1 121 vs 158 nm) —
so a small thin neuron is not penalised relative to a big one. That was the one argument
that could have favoured lod1 everywhere, and it does not hold.

---

## BANC: `decimate_mesh()` never enforced its budget

`budget_mb` is used **only as a skip threshold**; the target is then a density with no cap:

```python
if n * 9 / 1e6 <= budget_mb:        # loader.py:604 — skip if already small
    return mesh, '... <= budget'
area = _surface_area(mesh)
target = int(density * area)        # loader.py:607 — unbounded
if target >= 0.95 * n:              # loader.py:608 — also unbounded; returns as-is
    return mesh, '...'
```

At `MESH_DENSITY = 100` a 60,000 µm² neuron decimates to ~6 M faces ≈ **50 MB** and the
function reports success. The second escape is worse: a mesh already *below* the density
target is returned untouched however large it is.

**Fix — make the target two-sided**, on both paths:

```python
target = min(int(density * area), int(budget_bytes / BYTES_PER_FACE))
```

Then density binds for typical neurons and the budget binds for the tail. Split the one
constant into the two jobs it is doing: `MESH_SKIP_MB = 4.0` (below this, don't bother)
and `MESH_BUDGET_MB = 20.0` (above this, never serve).

A check on the numbers: 20 MB at 9 bytes/face caps at 2.22 M faces, so a 60,000 µm² neuron
lands at **37 f/µm²** — exactly hemibrain's measured "displays fine" density. The cap and
the quality floor meet where IMG-1 said they should. This also retires the tension that
`MESH_DENSITY = 100` implies ~50 MB for an APL: with the cap, 100 is safe as a *target*.

**Not yet a live problem.** 80 BANC brain channels sampled 2026-09-16: 68 served, **all
written by the current loader** (Aug 2026), median 90,645 faces (0.82 MB est), max 439,102
(3.95 MB est), **0/68 over 20 MB**. The remaining 12 have no image at all — IMG-4's gap.
The exposure is BANC's large-neuron tail, which random sampling does not reach.

**Worth checking separately:** `MESH_DENSITY` went 37 → 100 in `05cc221` on 2026-08-27,
mid-run. Unless the full run started after that commit, the served BANC set is a *mixture
of two densities*. The ledger records what each neuron got; `--redo` fixes it.

---

## Prototype run, 2026-09-16

10 maleCNS neurons (5 crossers), 15 served files, 296 s end to end. Not `loader.py` — a
scratch script exercising
`sources.MaleCnsBucket → Cut → LOD rule → chain.resolve (baked) → bbox trim → 3 dp OBJ`,
against the file VFB serves today. Both chains resolve to a **single baked hop**, so no
elastix and no CMTK.

**689.2 MB → 135.5 MB gzipped, 5.1×** (both sides gzipped; the served files are stored raw,
so raw-vs-gzip would have flattered us 4×). APL_R brain 149.90 → 17.87 MB at lod2;
DNp01(GF)_R brain 72.51 → 3.20 MB.

Three findings:

- **IMG-2 confirmed on served meshes, not sampled skeletons.** Every crosser has
  near-identical face counts in *both* channels — DNa02_L 3,487,189 / 3,487,189,
  AN00A006_M 1,588,120 / 1,588,120, DNp01(GF)_R 5,372,398 / 5,372,434.
- **The baked chain agrees with the existing pipeline where the existing pipeline is
  right.** For brain-only and VNC-only cells we reproduce the served geometry
  face-for-face (DL1_adPN_L 902,171 = 902,171; MBON03_R 1,516,018 = 1,516,018;
  IN13A073_L within 2 faces). Their only change is 8 dp → 3 dp, which is the 1.5× those
  rows show.
- The step-down fired, as described above.

The KB side is ready: **166,701 Berg2025a channels on both templates, all with folders,
zero accession/filename mismatches** — so `kb_worklist()` works unchanged and IMG-2 really
is a pipeline re-run with no re-curation.

---

## What is not done

- **`loader.py` is not generalised.** The branch generalised the layer underneath it
  (`connectomes.py`, `chain.py`, `sources.py`, `bake_fields.py`, `verify_baked.py`) and
  did not touch the job: `REGIONS` still cuts on y (maleCNS cuts on z), `DATASET`/`SITE`
  are constants, `_seq()` calls `find_bridging_path('BANC', …)`, `worker_init()` calls
  `transforms.register()` (the thing that reroutes maleCNS brain through BANC), `_cv()`
  hardcodes the BANC bucket, and the env vars and console script are BANC-named.
- **The rule in this document is implemented nowhere.**
- **The baked maleCNS fields have never been verified.** They exist (2026-08-28) but
  `verify_baked.py` has no recorded maleCNS result — its reference numbers are still
  BANC's. It needs elastix + CMTK on PATH, which production deliberately lacks, so it
  cannot be caught later. Do this before any test set.
- **MANC is a new connectome entry, not new arguments.** Its chain needs no baked field
  (`MANC → MANCum` affine, then two H5 hops, no binary), but: `Region` currently requires
  a `Cut` and MANC is VNC-only; `MANC → MANCnm` carries two parallel `AliasTransform`s and
  `MANC → FANC` exists, so the explicit-hop machinery is load-bearing; and **the geometry
  source is unresolved** — no public bucket answers at the obvious names, and `sources.py`
  is built on anonymous HTTPS precisely because neuprint-python needs 3.10 while the agent
  is 3.9.
- **The large-cell tail is unmeasured in both datasets.** A targeted probe of known-large
  cells (APL, CT1, giant fibre, large tangentials) would size the valve population for
  maleCNS and close the budget question for BANC's existing images, in one pass.
