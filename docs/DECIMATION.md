# Mesh decimation: making the served OBJs displayable

**Status: measured and settled; implemented for BANC only; never yet run against
`/IMAGE_WRITE/`.** Measured 2026-08-24 and 2026-08-26 against **trimesh 3.16.1 /
fast-simplification / navis 1.3.1**. The three loaders that produce the actual 515/281/626 MB
files — maleCNS, FlyWire, OpticLobe — are **untouched**.

This is the working spec for [`ISSUES.md`](ISSUES.md) **IMG-1**. It exists because the
conclusion recorded there on 2026-08-24 was *wrong in the opposite direction* — it said
decimation is impossible — and the reasoning that overturns it is a chain of measurements
that is expensive to re-derive and easy to get wrong in exactly the same way twice.

Companion docs: [`ISSUES.md`](ISSUES.md) IMG-1 (issue of record), IMG-4 (why BANC meshes are
missing), MESH-2 (dust), MESH-3 (CATMAID point cloud), CODE-5 (the `cloudvolume` swallow) ·
[`TRANSFORMS.md`](TRANSFORMS.md) (where in the pipeline this sits) ·
[`VALIDATION.md`](VALIDATION.md) (the geometric-correctness question, which is separate).

Visual A/B for the BANC APL, 250 µm down to 4 µm:
<https://claude.ai/code/artifact/a8a1418d-aeab-4040-adf8-e9466dc5f471>

---

## 1. The finding, in one table

APL_R, **the same cell**, in the two datasets at opposite ends of the IMG-1 size table.
Measured 2026-08-26 from the served `volume_man.obj` on JRC2018Unisex:

| | surface area | faces | density | mean edge | served |
|---|---|---|---|---|---|
| hemibrain APL_R | 62,244 µm² | 2,305,051 | **37.0 f/µm²** | 263 nm | 93.5 MB |
| maleCNS APL_R | 60,334 µm² | 11,971,252 | **198.4 f/µm²** | 114 nm | 514.8 MB |

**Identical surface area within 3%. maleCNS simply triangulates 5.4× finer.** Component
quality is the same too — largest connected component 97.77% of area vs 98.11%. The entire
5.5× filesize difference is redundant tessellation, and hemibrain, the coarse one, is the one
that displays acceptably.

That is the whole basis of this document. Everything below is consequence.

---

## 2. Source density census

Same measurement across every dataset, one representative neuron each,
`volume_man.obj` on JRC2018Unisex (`VFB_00101567`):

| dataset | neuron | f/µm² | mean edge | reduction to reach 37 |
|---|---|---|---|---|
| Xu2020 (hemibrain) | APL_R | 37.0 | 263 nm | **1.0× — no-op** |
| Dorkenwald2023 (FlyWire, `lod=2`) | MB_ML.1 | 103.6 | 148 nm | 2.8× |
| Bates2026 (BANC) | APL_R | 129.4 | 139 nm | 3.5× |
| Berg2025 (maleCNS) | APL_R | 198.4 | 114 nm | 5.4× |
| Bates2025 (BANC) | 3 sampled | 198.8–219.8 | 108–112 nm | 5.4–5.9× |
| Nern2024 (OpticLobe) | APL_R | 458.6 | 78 nm | 12.4× |
| Zheng2018 (CATMAID) | APL | — | — | **not a mesh — MESH-3** |

hemibrain is the outlier and it is the acceptable one. **Mean edge length is the invariant**
worth remembering: everything except hemibrain lands at 78–148 nm, hemibrain at 263 nm.

BANC is not uniform: the APL sits at 129 f/µm² while three ordinary neurons sit at 199–220.
Do not assume a per-dataset constant — compute the target from each mesh.

---

## 3. Why the 2026-08-24 verdict was wrong

`ISSUES.md` previously carried a section headed *"Decimation does not work here — do not
retry it"*. Recording the failure mode because it is a natural one to repeat:

1. **It tested reductions 5–50× more aggressive than needed.** The budgets tried were 4 and
   8 faces/µm² — a 25–50× cut — plus cable-length budgets. Only one row, `cable 64/µm` =
   93 f/µm², was in a sane range, and it reported 93.2% of area kept with 4 components.
   That is a *good* result, read as a failure.
2. **It read component count as fragmentation** on meshes whose *source* component count is
   already 17,008 sub-µm² dust fragments — a fact the same document establishes in MESH-2.
   "274 components" is not fragmentation when the reference mesh has 4,099.
3. **It inferred "there is no tessellation redundancy" from the 8 nm source voxel size**
   rather than measuring against a mesh known to display fine. The voxel grid bounds what
   the reconstruction *can resolve*; it says nothing about how finely the marching-cubes
   surface was then triangulated. This was the load-bearing error — it made the question
   look closed on first principles, so no A/B was ever run.

The general lesson: **the acceptability threshold was available as a measurement all along**
(another dataset's mesh of the same cell), and was never taken.

---

## 4. The rule

```
target_faces = MESH_DENSITY × surface_area_of_this_mesh
MESH_DENSITY = 37.0            faces per µm²  (≈ 250 nm mean edge)
```

Properties that make this the right form:

- **Self-calibrating.** The reduction factor comes from the source mesh, so one constant
  covers datasets that differ by 12× in density.
- **A no-op where it should be.** hemibrain is already at the target and is left alone.
- **Not a percentage.** A fixed 10% or 50% budget damages the coarse datasets and
  under-treats the fine ones. This is also why upstream's `percent = 0.1` must not be
  "fixed" — see §8.

Two guards on top:

```
MESH_BUDGET_MB = 4.0     skip if the mesh is already small on the wire (≈9 bytes/face gzipped)
                         → most BANC neurons are never touched at all
skip if target ≥ 0.95 × n   → don't rewrite a mesh for a <5% gain
skip if n < 1000            → nothing to decimate
OBJ_DP = 3                  1 nm quantisation; worst vertex moves 0.86 nm
```

`MESH_BUDGET_MB` matters more than it looks. Most BANC neurons gzip to a few hundred KB
untouched; there is no reason to spend fidelity on them for a saving nobody notices.

---

## 5. Measured cost

### maleCNS APL_R — 11,971,252 → 2,232,341 faces (5.4×)

| metric | before | after |
|---|---|---|
| surface area | 60,334 µm² | 54,933 µm² (91.0%) |
| effective radius `2V/A` | 147.0 nm | **149.3 nm** |
| connected components | 17,008 | 2,284 |
| largest component | 98.11% of area | **98.38%** |
| boundary edges | 673 | 3 |
| degenerate faces | 0 | 0 |
| non-manifold edges | 60,859 | 43,713 |
| area >250 nm from result | — | 0.134% |
| area >1 µm from result | — | 0.000% |

### BANC APL_R — 7,041,847 → 2,013,109 faces (3.5×)

`root_888` 720575941482622627, `cell_type` APL, 26,286 µm cable.

| metric | before | after |
|---|---|---|
| surface area | 54,408 µm² | 46,431 µm² (85.3%) |
| effective radius `2V/A` | 145.8 nm | 127.6 nm (**−12.5% — see §6**) |
| connected components | 8,847 | 4,000 |
| boundary / non-manifold / degenerate | 14,073 / 1,687 / 1,473 | — |
| area >250 nm from result | — | 0.062% |
| area >1 µm from result | — | 0.0001% |
| worst single deviation | — | 1,179 nm |

**Deviation is one-sided and area-weighted**: every source triangle centroid measured to the
nearest decimated vertex, weighted by the area it carries. This is the metric that answers
*"did a branch disappear"*, and nothing did.

**Component count falling is not a loss.** Decimation merges the MESH-2 dust; the largest
component's share *rises*. No separate dust-stripping pass is needed.

### Wire sizes

Gzipped, i.e. what actually crosses the network:

| mesh | served now | after | factor |
|---|---|---|---|
| OpticLobe APL_R | 625.8 MB | **12.4 MB** | 50.3× |
| maleCNS APL_R | 514.8 MB | **18.5 MB** | 27.8× |
| FlyWire MB_ML.1 | 281.4 MB | **19.5 MB** | 14.4× |
| BANC APL_R | 55.8 MB gz (300 MB raw) | **17.8 MB** | 3.1× on the wire, 4.5× raw |
| hemibrain APL_R | 93.5 MB | **18.5 MB** | 5.0× (from 3 dp + gzip alone) |
| BANC, 26 MB neuron | 26.3 MB | **1.26 MB** | 20.8× |
| BANC, 1.6 MB neuron | 1.6 MB | **0.41 MB** | 4.0× — under budget, not decimated |

Every dataset converges on 12–20 MB for an APL-scale neuron, because they converge on the
same face count. **`gzip` is a server `Content-Encoding` setting, not something this repo
writes** — the raw-OBJ column is what the loaders control.

---

## 6. Open question: `2V/A` on the BANC APL

The one metric that disagrees, recorded rather than smoothed over.

The claim that decimation removes *surface corrugation* rather than *tube thickness* rests on
the effective radius `2V/A` being unchanged. On three meshes it is:

| mesh | `2V/A` before | after |
|---|---|---|
| maleCNS APL_R | 147.0 nm | 149.3 nm |
| BANC n1 (706 k faces) | 149.6 nm | 149.5 nm |
| BANC n2 (63 k faces) | 114.8 nm | 110.6 nm |
| **BANC APL_R** | **145.8 nm** | **127.6 nm** |

The BANC APL loses 12.5% where the others lose nothing. Two candidate explanations, neither
confirmed:

- **`V` is unreliable here.** Measured on this mesh: **14,073 boundary edges** (i.e. 14,073
  open edges where the surface simply stops), 1,687 non-manifold edges and 1,473 degenerate
  faces, across 8,847 components. The divergence theorem assumes a closed surface, so `V` is
  a rough indicator at best. For comparison the maleCNS APL has only 673 boundary edges —
  20× fewer — and it is the mesh whose `2V/A` held steady. **This is very likely the whole
  explanation.**
- **Real thinning specific to this mesh.** Its source density is 129 f/µm², *lower* than the
  others, so per-triangle it starts closer to the target — which makes a larger thickness
  loss the harder story to tell, not the easier one.

The spatial measurement disagrees with the pessimistic reading: 0.062% of area more than
250 nm from the result is the *best* of any mesh tested.

**To settle it, don't refine the volume estimate — measure thickness directly.** Sample N
points on the surface, cast a ray along −normal, take the first hit; that is the local tube
diameter, and its distribution before and after is the answer. `trimesh.ray` will do it on
the decimated mesh; the source mesh needs a crop or an embree build to be tractable.
**Not yet done.**

Nothing else in this document depends on the outcome — the size and spatial-fidelity results
stand either way. What is at stake is only whether a small uniform re-inflation would be an
improvement, and §7 rejects that on independent grounds.

---

## 7. Rejected alternatives

Each was measured and each is a dead end. Do not re-litigate without new evidence.

| approach | verdict | evidence |
|---|---|---|
| **Normal-offset re-inflation to restore area** | **rejected** | Matching area overshoots *volume* by 10–24% (BANC wants a 55–59 nm offset where volume-matching wants 28–33 nm), so it would serve neurites visibly fatter than the reconstruction. Restoring area ≠ restoring thickness, because some of the lost area is genuine roughness. |
| **pymeshlab quadric with `preservetopology=True`** | **no better, 32× slower** | Same area kept (54,780 vs 54,933 µm²), component count preserved exactly at 17,008 — but 193 s vs 6.1 s for maleCNS APL. `fast_simplification` already does not fragment at this target, so topology preservation buys nothing. |
| **15 f/µm²** | **too far** | 4.2% of area >250 nm away (vs 0.13% at 37), 78.8% area kept, thin processes shred. 25 f/µm² is borderline at 0.60%. |
| **A fixed percentage budget** | **wrong shape** | Damages coarse datasets, under-treats fine ones. See §4. |
| **Separate sub-µm² dust stripping** | **unnecessary** | Decimation already merges it and *improves* the largest-component share. MESH-2's threshold caveat still applies to anything that does prune components — FlyWire's second 16,103 µm² component is real neuron, not debris. |
| **Welding / merging vertices** | **does nothing** | 0 vertices merge at any tolerance up to one voxel, via raw parsing, `trimesh.load(process=True)`, `merge_vertices()` or `process(validate=True)`. (2026-08-24) |
| **Boolean union of fragments** | **not applicable** | Fragments do not intersect. manifold3d rejected 731/1,110 parts and returned 379 still-separate components holding 0.6% of area. (2026-08-24) |
| **2 dp instead of 3 dp** | **not worth it** | Buys ~14% (maleCNS 93.9 → 81.0 MB gz) for 10× coarser quantisation and measurable area loss. 1 dp is disqualified: 19.3% of maleCNS's surface disappears. |

### Metrics that misled, and must not be trusted alone

- **Component count** — counts sub-µm² debris; the baseline is already in the thousands.
- **Unsigned mean surface distance** — 0.27 µm at 4 f/µm² looked excellent while tubes were
  pinching shut, because sealing a tube barely moves the surface. Use the **area-weighted
  one-sided tail** (`% of area >250 nm / >1 µm away`) instead.
- **Renderer coverage** — see the trap in §11. A naive rasteriser under-samples the *coarse*
  mesh and manufactures damage that is not there.

---

## 8. Do not "fix" the upstream decimation

`banc/transforms/banc-ngl-upload.R` computes a decimated mesh and uploads the undecimated
file:

```r
mesh3d <- readobj::read.obj(obj.file, convert.rgl = TRUE)[[1]]
mesh3d <- Rvcg::vcgQEdecim(mesh3d, percent = 0.1)   # result never used
banc_upload_mesh(mesh = obj.file, ...)              # <- the full-res path
```

That it is unintended is clear from the hemibrain block in the same file, which passes
`mesh = mesh3d`. FANC, FAFB and maleCNS have the same discarded-decimation shape.

**Leave it.** `percent = 0.1` is a 10× cut to ~20 f/µm² — past this repo's 37 and into the
range where thin processes shred (§7). It would be applied *before* the transform into
template space, on every consumer, with no opt-out. The bug is load-bearing in our favour:
it is why we receive intact full-resolution geometry we can decimate to our own target.
Worth watching in case it changes.

---

## 9. What is implemented

In [`-m vfb_connectomics_import.images.loader`](-m vfb_connectomics_import.images.loader),
between `write_nrrd` and `clip_into`:

```python
MESH_DENSITY   = 37.0    # faces per µm² of surface area; hemibrain-matched
MESH_BUDGET_MB = 4.0     # leave a mesh alone if already this small on the wire
OBJ_DP         = 3       # 1 nm quantisation

_surface_area(mesh)                                  -> float, µm²
decimate_mesh(mesh, density, budget_mb)              -> (trimesh, note)
write_obj(mesh, path, dp)                            -> None
```

Wired in at the OBJ write only:

```python
dec, note = decimate_mesh(t_mesh, mesh_density, mesh_budget_mb)
r['obj_faces'] = len(dec.faces)
r['obj_note']  = note
write_obj(dec, tmp)
```

CLI: `--mesh-density` (default 37.0, **`0` disables**) and `--mesh-budget-mb` (default 4.0).
Both are threaded through the worker task tuple, so they are honoured under `--workers`.
Per-neuron `obj_faces` / `obj_note` land in the ledger and the `--report` CSV, which is how a
run is audited after the fact.

`requirements.txt` gains `fast-simplification`.

**The NRRD deliberately keeps the full-resolution mesh.** It voxelises onto a ~0.5 µm grid,
so it neither gains from the fine mesh nor suffers from the coarse one — and leaving it
untouched keeps a known-good output out of this change. Do not "simplify" this by feeding it
the decimated mesh without re-checking the NRRDs.

### Not implemented

- **maleCNS, FlyWire and OpticLobe loaders.** These produce the 515/281/626 MB files. The
  FlyWire path is `flywire_import.py:184` (`volume_man.obj`); maleCNS lives in a Jenkins job
  outside this repo. Each needs the same two calls, and `flywire_import.py:230` already
  passes `lod=2`, which is *not* sufficient (104 f/µm² after it).
- **Any actual run.** Nothing has been written to `/IMAGE_WRITE/` with this code.
- **Server-side `Content-Encoding: gzip`.** Outside this repo; worth 3.0–3.6× on its own and
  bit-exact.
- **The `2V/A` question in §6.**

---

## 10. Implementation order, if we go ahead

1. **Dry-run BANC on a sample.** `--limit 200 --report` with the fields above, then check the
   `obj_note` distribution: how many `budget`-skipped, how many decimated, what the face
   ratios are. No writes to the real tree.
2. **Eyeball the largest few.** The zoom-ladder method in §11 on the 5 biggest neurons in the
   sample. This is cheap and it is the only check that catches a class of damage the numbers
   miss.
3. **Decide the budget.** 4 MB is a judgement call, not a measurement. If most of the sample
   is skipped and the tail is still large, lower it.
4. **BANC full run**, then re-measure served sizes from the file server rather than trusting
   the loader's own numbers.
5. **Port to FlyWire**, which is the smallest port and the second-worst offender.
6. **maleCNS and OpticLobe** — OpticLobe is the largest win (50×) and the largest reduction
   (12.4×), so re-run step 2 on it specifically rather than assuming it transfers.
7. **Only then** consider whether the Neuroglancer migration (streaming LODs) is still
   urgent. It remains the right end state; it is no longer an emergency.

Ordering note: steps 1–4 are independent of 5–6, and IMG-2 (maleCNS not being cut) should
land before maleCNS meshes are regenerated, or the work is done twice.

---

## 11. How to reproduce the measurements

### Density and fidelity

```python
import numpy as np, trimesh, fast_simplification
from scipy.spatial import cKDTree

def tri_area(V, F):
    return 0.5*np.linalg.norm(np.cross(V[F[:,1]]-V[F[:,0]], V[F[:,2]]-V[F[:,0]]), axis=1)

A0   = tri_area(V, F); tot = A0.sum()
dens = len(F)/tot                                  # the number that matters
Vd, Fd = fast_simplification.simplify(V.astype(np.float32), F.astype(np.int32),
                                     target_reduction=1 - int(37.0*tot)/len(F))
d, _ = cKDTree(Vd).query(V[F].mean(1), workers=-1)  # one-sided, source -> result
print(f'area >250nm away: {100*A0[d>0.25].sum()/tot:.3f}%')
print(f'area >1um   away: {100*A0[d>1.0].sum()/tot:.4f}%')
```

Component counts via `scipy.sparse.csgraph.connected_components` on the edge graph, which
runs in seconds at 12 M faces. (`trimesh.split()` was not benchmarked against it.)

### Getting a mesh to test with

Served meshes, no auth:

```
https://www.virtualflybrain.org/data/VFB/i/<first4>/<last4>/<template>/volume_man.obj
```

For a BANC neuron with no VFB image, fetch the precomputed fragment directly — **do not go
through `cloudvolume`, see CODE-5**:

```bash
B=https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/neuron_meshes/meshes
curl -s "$B/<root>:0"            # {"fragments":["<root>:0:1"]}
curl -sO "$B/<root>:0:1"
```

```python
raw = open(frag,'rb').read()
n   = np.frombuffer(raw, np.uint32, 1)[0]
V   = np.frombuffer(raw, np.float32, 3*n, 4).reshape(n,3) / 1000.0   # nm -> µm
F   = np.frombuffer(raw, np.uint32, offset=4+12*n).reshape(-1,3)
```

Cell types come from `compiled_data/banc_888/banc_888_meta.feather` (188,508 × 81; the
`cell_type` column — the BANC APL is the single row with `cell_type == 'APL'`).

### The visual A/B, and its trap

Both meshes must be rendered with **one camera and one rasteriser**, and the rasteriser must
sample **proportionally to projected triangle area**. A fixed sample budget per triangle
silently under-fills the coarse mesh at high zoom and invents damage:

| field | source coverage | decimated coverage | |
|---|---|---|---|
| 4 µm | 0.293 | 0.080 | capped at 512 samples/triangle — **artefact** |
| 4 µm | 0.522 | 0.490 | cap raised to 2¹⁸ — real |

This cost a wrong conclusion once ("the thinnest twigs bead"). Coverage parity between the
two meshes at every zoom level is both the check that the renderer is fair *and* good
evidence that the geometry survived.

Useful zoom ladder: 250 µm (whole neuron) → 60 → 24 → 10 → 4 µm. Differences are invisible
above ~10 µm; below that both meshes are visibly faceted, and the question is whether the
*same branches* are in the *same places*. A wipe or blink comparison at matched camera shows
this far better than side-by-side.

---

## 12. Traps

- **Density must be computed per mesh, not per dataset.** BANC spans 129–220 f/µm².
- **Compute the target from the *source* area.** Area drops during decimation, so the
  achieved density reads higher than `MESH_DENSITY` (43 rather than 37 on the BANC APL).
  That is expected, not a bug.
- **`fast_simplification` wants float32 / int32.** Passing float64 silently copies.
- **These meshes are non-manifold and not watertight** — 60,859 non-manifold edges on the
  maleCNS APL. Any metric derived from volume is approximate; anything that assumes a closed
  surface will mislead.
- **`--mesh-density 0` disables**, for reproducing an old output byte-for-byte. It does not
  disable the 3 dp write; that is `OBJ_DP`.
- **`write_obj` replaced `navis.write_mesh` for the OBJ.** It writes a two-line comment
  header, `v`/`f` only, and no normals or texture coordinates. `navis.read_mesh` round-trips
  it; anything else consuming these files should be checked once.
- **Decimation happens after the transform and the bbox trim**, in microns in template space.
  Moving it earlier would change the density target's meaning.
