# Known issues — connectome import

Cross-cutting defects found in the loaded data or the import code. This is the work queue
for the connectome import agent; the [dashboard](../dashboard/) tracks *stage progress*, which
is a different question ("has n2n been built?" vs "is what we built correct?").

Each issue has a stable ID. Keep the evidence and its date — re-measure rather than trust a
figure if the release has moved on. See [`VERSIONING.md`](VERSIONING.md) for the identity
and curation rules that several of these depend on.

Status: `open` · `in-progress` · `fixed` · `wontfix`

---

## IMG-1 — Served OBJ meshes are far too large to display · **critical** · in-progress

**Affects: every EM connectome.** Not BANC-specific; fixing one dataset leaves the rest
broken.

Measured 2026-08-24, `volume_man.obj` for APL (`FBbt_00100222`), a deliberately large
neuron:

| dataset | APL OBJ |
|---|---|
| Nern2024 (OpticLobe) | **625.79 MB** |
| Berg2025 (maleCNS) R / L | **514.77 / 489.90 MB** |
| Dorkenwald2023 (FlyWire) | **281.42 / 282.04 MB** |
| Xu2020 (hemibrain) | 93.51 MB |
| Zheng2018 / Baltruschat2021 (CATMAID) | 1.89 MB |

BANC, 30 randomly sampled neurons: mean **9.74 MB**, max **44.63 MB** (MBON03 45 MB, a
`tibia_flexor` motor neuron 52 MB). A BANC APL would plausibly sit in the 200–500 MB range.

Confirmed in practice: loading the maleCNS APL takes **minutes on a good connection**.

Context:

- FlyWire's 281 MB is already produced **with `lod=2`** (`flywire_import.py:230`), so
  source-side LOD is not sufficient.
- BANC publishes **only LOD 0** (`meshes/<root>:1` and above are 404). Confirmed 2026-08-25
  from the layer itself: `neuron_meshes/meshes/info` is a **404**, so this is the legacy
  single-resolution precomputed format, not `neuroglancer_multilod_draco`, and a manifest
  lists exactly one fragment (`<root>:0:1`). There is no coarser mesh to fetch, so IMG-1
  has **no bucket-side fix**.

### Upstream intended 10% decimation and it silently does not happen

In `banc/transforms/banc-ngl-upload.R` the BANC block reads the OBJ, decimates it, and then
uploads the **undecimated file**:

```r
mesh3d <- readobj::read.obj(obj.file, convert.rgl = TRUE)[[1]]
mesh3d <- Rvcg::vcgQEdecim(mesh3d, percent = 0.1)   # result never used
banc_upload_mesh(mesh = obj.file, ...)              # <- the full-res path
```

`mesh3d` is computed and discarded. That this is unintended is clear from the hemibrain
block in the same file, which passes `mesh = mesh3d` with `# obj.file,` commented out
beside it — so `banc_upload_mesh` does accept a mesh object. FANC, FAFB and maleCNS have
the same discarded-decimation shape as BANC.

**Still do not report this upstream as a simple fix**, though the reason has changed now
that decimation is measured properly (below). `percent = 0.1` is a **10× cut to ~20 f/µm²**,
which is past the 37 f/µm² this repo settled on and into the range where thin processes
shred. And it would be applied *before* the transform into template space, on every
consumer, with no way to opt out. The bug is load-bearing in our favour for a different
reason than previously recorded: it is why we receive intact full-resolution geometry that
we can decimate to our own target. Worth watching in case it changes.
- The other two file types are fine: NRRD is 0.15–0.39 MB even for APL (bounded by the
  template, not the neuron); SWC is 2–13 MB.

### SOLVED: the size difference is tessellation density, not neuron size

Measured 2026-08-26. APL_R, **the same cell**, in the two datasets at opposite ends of the
table above:

| | area | faces | density | mean edge | served |
|---|---|---|---|---|---|
| hemibrain APL_R | 62,244 µm² | 2.31 M | **37 f/µm²** | 263 nm | 93.5 MB |
| maleCNS APL_R | 60,334 µm² | 11.97 M | **198 f/µm²** | 114 nm | 514.8 MB |

**Identical surface area (within 3%); maleCNS just triangulates 5.4× finer.** Component
quality is the same too (largest component 97.8% vs 98.1% of area). The entire 5.5× file
size difference is redundant tessellation — and hemibrain, the coarse one, is the one that
displays acceptably.

Source density across every dataset, `volume_man.obj` on JRC2018Unisex:

| dataset | f/µm² | mean edge | reduction to reach 37 |
|---|---|---|---|
| hemibrain (Xu2020) | 37 | 263 nm | 1.0× (no-op) |
| FlyWire (Dorkenwald2023, `lod=2`) | 104 | 148 nm | 2.8× |
| maleCNS (Berg2025) | 198 | 114 nm | 5.4× |
| BANC (Bates2025/2026), n=3 | 199–220 | 108–112 nm | 5.4–5.9× |
| OpticLobe (Nern2024) | 459 | 78 nm | 12.4× |
| CATMAID/FAFB (Zheng2018) | — | — | **no faces at all, see MESH-3** |

So the target is not a guess: **decimate to hemibrain's 37 f/µm² (≈250 nm edges)**. The
factor falls out of the source mesh, and hemibrain is left untouched by construction.

### Why the earlier "decimation is impossible" verdict was wrong

Recorded here because the mistake is easy to repeat. The 2026-08-24 investigation concluded
quadric decimation destroys these meshes. It does not. Three errors:

1. **It tested reductions 5–50× more aggressive than needed.** The budgets tried were 4 and
   8 faces/µm² — a 25–50× cut — plus cable-length budgets. The only row in a sane range,
   `cable 64/µm` = 93 f/µm², reported 93.2% of area kept and 4 components, which is a
   *good* result read as a failure.
2. **It read component count as fragmentation** on meshes whose *source* component count is
   already 17,008 (sub-µm² dust — MESH-2, which the same document establishes). "274
   components" is not fragmentation when the hemibrain reference mesh has 4,099.
3. **It inferred "no tessellation redundancy" from the 8 nm source voxel size** rather than
   measuring against a mesh known to display fine. The voxel grid bounds what the
   reconstruction *can* resolve; it says nothing about how finely the marching-cubes
   surface was then triangulated.

### Measured cost at 37 f/µm² (maleCNS APL_R, 11.97 M → 2.23 M faces)

| metric | before | after |
|---|---|---|
| surface area | 60,334 µm² | 54,933 µm² (91.0%) |
| effective radius 2V/A | 147.0 nm | **149.3 nm** |
| components | 17,008 | 2,284 |
| largest component | 98.11% of area | **98.38%** |
| boundary edges | 673 | 3 |
| degenerate faces | 0 | 0 |
| area >250 nm from result | — | 0.134% |
| area >1 µm from result | — | 0.000% |

Nothing is lost: no branch moves more than ~1.6 µm anywhere, and 99.87% of the surface
stays within 250 nm. The component count *falls* because decimation merges the dust MESH-2
describes — it does not split the arbor.

**The lost 9% of area is voxel-scale surface corrugation, not tube thinning.** The
proof is `2V/A`, an effective radius, which is unchanged: BANC 149.6 → 149.5 nm,
maleCNS 147.0 → 149.3 nm. Decimation is straightening 8 nm-scale knobbles off the tube
wall, which is exactly what should go.

**Do NOT add a normal-offset "re-inflation" to recover the area.** Tried and rejected
2026-08-26: offsetting vertices outward until the area matches the source overshoots
*volume* by 10–24% (BANC needs a 55–59 nm offset where volume-matching wants 28–33 nm), so
it would serve neurites visibly fatter than the reconstruction. There is nothing to
recover.

Visual check at 12–16 µm fields — far more zoomed than any whole-neuron display — is
indistinguishable from the source and matches hemibrain's faceted look. Only below ~5 µm
fields do the thinnest twigs go chunky and occasionally bead, which is the trade hemibrain
already ships. 15 f/µm² was also tested and is too far: 4.2% of area >250 nm away, thin
processes shred.

### What does work: lossless mitigation, ~5× total

All of the following are lossless at display scale and need no geometry change:

| lever | gain | notes |
|---|---|---|
| **gzip** via `Content-Encoding` | 3.0–3.6× | bit-exact; browsers decompress transparently, no format change |
| **precision trim to 3 dp** | ~1.5× on top of gzip | **every dataset writes 8 dp** (`v 201.79138893 …`), resolving ~0.01 pm against an 8 nm voxel grid |
| **strip sub-µm² dust** | 1.01–1.04× | see MESH-2; threshold-based only |

Combined, measured 2026-08-24 (gzipped, i.e. what goes over the wire):

| mesh | source | gzip | **gzip + 3 dp** | total |
|---|---|---|---|---|
| hemibrain_APL | 93.5 MB | 27.8 | **18.6 MB** | 5.0× |
| flywire_APL | 281.4 MB | 79.4 | **52.3 MB** | 5.4× |
| maleCNS_APL_R | 514.8 MB | 143.0 | **93.9 MB** | 5.5× |
| banc_MBON03 | 45.1 MB | 15.1 | 12.0 MB | 3.8× |

**Choose 3 dp.** Quantisation vs geometric cost, measured across three APLs:

| dp | step | max vertex shift | area change | verts welded |
|---|---|---|---|---|
| 4 | 0.1 nm | 0.086 nm | 0.000% | 0 |
| **3** | **1 nm** | **0.86 nm** | **≤0.002%** | **0–60** |
| 2 | 10 nm | 8.6 nm | 0.044–0.221% | 0–3,568 |
| 1 | 100 nm | 86 nm | **4.1–19.3%** | 24k–1.37M |

At 3 dp the worst vertex moves a *tenth of a source voxel*. 2 dp buys only ~14% more
(maleCNS 93.9 → 81.0 MB) for 10× coarser quantisation and measurable area loss — not worth
it. 1 dp is disqualified: 19.3% of maleCNS's surface disappears.

### Combined result: decimate to 37 f/µm², write 3 dp, serve gzipped

Measured end to end 2026-08-26, wire size = gzipped:

| mesh | served now | after | factor |
|---|---|---|---|
| OpticLobe APL_R | 625.8 MB | **12.4 MB** | 50.3× |
| maleCNS APL_R | 514.8 MB | **18.5 MB** | 27.8× |
| FlyWire MB_ML.1 | 281.4 MB | **19.5 MB** | 14.4× |
| hemibrain APL_R | 93.5 MB | **18.5 MB** | 5.0× (decimation is a no-op) |
| BANC n1 (26 MB) | 26.3 MB | **1.26 MB** | 20.8× |
| BANC n3 (1.6 MB) | 1.6 MB | **0.41 MB** | 4.0× (under budget, not decimated) |

Note every dataset converges on ~12–20 MB for an APL-scale neuron, because they converge
on the same face count. `gzip` remains a server `Content-Encoding` setting, not something
this repo writes.

Full working spec, rejected alternatives, reproduction recipe and implementation order:
**[`DECIMATION.md`](DECIMATION.md)**.

**Implemented** for BANC in `images/loader.py`: `MESH_DENSITY = 37.0`,
`MESH_BUDGET_MB = 4.0`, `OBJ_DP = 3`, `decimate_mesh()` / `write_obj()`, exposed as
`--mesh-density` / `--mesh-budget-mb` (`--mesh-density 0` disables). A mesh already under
the budget is left alone — most BANC neurons are a few MB and there is no reason to spend
fidelity on them. The NRRD deliberately keeps the full-res mesh: it voxelises onto a
~0.5 µm grid, so it neither gains from the fine mesh nor suffers from the coarse one.

**Still to do:** the same two lines in the maleCNS, FlyWire and OpticLobe loaders — those
are where the 515/281/626 MB files come from, and they are untouched. The
**Neuroglancer migration** (streaming LODs) is still the right end state, but this is no
longer mitigated-not-solved: 12–20 MB gzipped is a displayable file.

---

## IMG-2 — maleCNS images are not cut; whole neuron written to both templates · **high** · open

**Affects: Berg2025 / Berg2025a (maleCNS).**

Verified 2026-08-18 on 15 sampled neurons: identical node counts in both channels, and in
13/15 the VNC channel is **100% outside** the JRCVNC2018U bounding box. Ascending and
descending neurons are wrong in **both** channels, so both image jobs are affected, not just
the VNC one.

Cause is silent identity-extrapolation in the transform chain — see
[[navis-banc-transform-gotchas]] in the agent's memory, or the summary in `VERSIONING.md`.
`navis.voxelize(bounds=...)` already clips, which is why the NRRDs look fine and this went
unnoticed in SWC/OBJ.

**Fix direction:** the four-step logic in IMG-3 below, which is dataset-agnostic.

---

## IMG-3 — BANC: ~4,660 spurious brain images that should be deleted · **high** · open

**Affects: Bates2025 / Bates2026 (BANC).**

Of 7,624 v888 neurons with a real image on both templates, only **2,964** are crossers by
BANC's own annotations. The other **4,660** are VNC neurons (sensory 3,345,
vnc_intrinsic 781, motor 424, visceral_circulatory 107) whose brain image is **100% outside**
the brain bounding box — e.g. a `tibia_flexor` motor neuron with a 1,632-node "brain" image
sitting entirely outside the template. These should be **removed**, not regenerated.

**Removal is implemented** in
[`images/loader.py`](-m vfb_connectomics_import.images.loader): when a rebuild
finds no material in the region *and* a usable source was available, the existing image is
deleted (`deleted_spurious`). The source-available condition matters — upstream mesh
coverage is only 94.4%/68.8%, so a `no_source` neuron must never have its image deleted on
the strength of absent input. `--no-delete-spurious` disables it for a first pass.

The working algorithm, established 2026-08-19/20 and applicable to any whole-CNS dataset:

```
1. templates to attempt  =  region  ∪  crosser-flag
      BANC: `region` (3 values) for the 89% that do not span;
      crossers from the neck-connective table ∪ super_class
      {ascending, descending, sensory_ascending, sensory_descending}.
      region ALONE truncates every one of ~3,500 crossers.
      (In practice geometry alone reproduces this — see "cut at the neuropil" below —
       so these annotations are better used as a cross-check than as an input.)

2. cut in source space at the NEUROPIL boundaries      <-- MANDATORY
      BANC brain half : y <  305,801 nm   (BANC_brain.ply y max)
      BANC vnc   half : y >  549,946 nm   (BANC_vnc.ply  y min)
      The 244 um of neck connective between them is DROPPED from both halves.

3. trim each half to its target template bbox
      catches peripheral-nerve arbors (14,747 BANC neurons) leaving the CNS.

4. if a half trims to zero nodes, do not write the image
      this is what removes the spurious images.
```

**Cut at the neuropil, not at the connective.** An earlier version cut at BANC's own
neck-connective annotation (y = 370,000 nm, `neck_connective_y92500`). That is wrong,
because **registration support extends ~200 um past each neuropil with no anatomy to
constrain it**:

| | registration support | neuropil |
|---|---|---|
| brain | y **36 – 540** µm | 45 – **305.8** µm |
| vnc | y **340** – 1132 µm | **549.9** – 1017.8 µm |

Material in the overlap gets genuinely warped — not identity-fallback — into
plausible-looking coordinates that *pass* a bbox check. Measured on crosser
`720575941514201932`: a 29-node fragment from source y 432–437 µm landed pinned to the
JRCVNC2018U bbox corner (z 151.5 of a 152.4 ceiling) and survived the trim. Cutting at the
neuropil removed it — the halves went from 2 spatial clusters to 1 — at a cost of 953 nodes
/ 356 µm of connective cable, 3.6% of that neuron. **Support ≠ validity.**

Step 2 cannot be replaced by step 3: brain material at low source x arrives as
near-identity and the VNC bounding box genuinely contains those coordinates —
measured leakage **42/420 (10%)** brain→VNC, versus **0/378** VNC→brain. The asymmetry is
counter-intuitive and was verified with elastix, not assumed.

### Verified transform paths (BANC)

Confirmed 2026-08-24 with **navis 1.9.1 / flybrains 0.6.3 / elastix 5.3.1**. Both are the
3-hop minimum and `shortest_bridging_seq` selects them unaided:

```
BANC -> JRC2018U        BANC -> BANCum -> JRC2018F -> JRC2018U
  1. AffineTransform    diag [0.001, 0.001, 0.001]        nm -> um
  2. ElastixTransform   <flybrains>/data/BANC_JRC2018F/BANC_to_template.txt
  3. H5transform        ~/flybrain-data/JRC2018U_JRC2018F.h5

BANC -> JRCVNC2018U     BANC -> BANCum -> JRCVNC2018F -> JRCVNC2018U
  1. AffineTransform    diag [0.001, 0.001, 0.001]        nm -> um
  2. ElastixTransform   <flybrains>/data/BANC_JRCVNC2018F/BANC_to_template.txt
  3. H5transform        ~/flybrain-data/JRCVNC2018U_JRCVNC2018F.h5
```

Use **no `via` and no `avoid`** for a BANC source. The `avoid=['BANC','BANCum']` in CODE-1
applies to *other* datasets that must not detour through BANC; applying it here removes the
only available path. elastix lives at `~/opt/elastix` — needs `PATH` and
`DYLD_LIBRARY_PATH` (see CODE-2).

### Validated against the existing images

One neck crosser, root `720575941514201932` = `VFB_00105soo` (AN17A018, ascending), which
already has both images. Ours (BANC published `_skeleton.swc`, cut at y=370,000, aligned,
bbox-trimmed) vs the existing VFB image:

| half | centroid offset | median NN | ours / VFB nodes |
|---|---|---|---|
| brain | 4.46 µm | 1.7–2.1 µm | 2,632 / 3,048 |
| vnc | 23.67 µm | 7.0–7.9 µm | 23,597 / 30,297 |

The brain half agrees. The VNC half is displaced ~24 µm and differs in extent — **and on
visual inspection the existing VFB VNC image leaves the neuropil in places while ours stays
inside, so ours is the better of the two.** Node counts are not comparable: VFB's are
mesh-derived (denser sampling), ours come from BANC's published skeleton.

Two things ruled out while investigating: VFB's VNC image is **not** contaminated with
brain-side material (our brain half pushed through the VNC transform gives 0/2,725 points
inside the VNC bbox), and the node-count gap is sampling density, not extra content.

**Acceptance check should be neuropil containment, not bbox.** The bounding box is a crude
proxy — the existing VFB VNC image passes a bbox test while sitting outside the neuropil.
Test against the `JRCVNC2018U` / `JRC2018U` neuropil meshes instead;
[`VALIDATION.md`](VALIDATION.md) records where those meshes live, which comparisons are
circular, and what to run instead.

**The materiality rule is now implemented** in
[`images/loader.py`](-m vfb_connectomics_import.images.loader) as
`--min-nodes` / `--min-faces` (defaults 10 / 100), reported as its own `too_small` status
so the cut-off stays auditable rather than silently dropping data. It earned its keep
immediately: on a 4-neuron VNC test one half survived the bbox trim with **5 nodes / 36
faces** — a truncated tip at the cut plane, not a depictable arbor.

Still open from this issue: the **acceptance test** should be neuropil-mesh containment
rather than bbox, which is blocked on the three faults recorded in
[`VALIDATION.md`](VALIDATION.md) (`trimesh.contains` needs `rtree`/`embreex`; `JRC2018U`'s
mesh is not watertight; **`JRCVNC2018U`'s mesh has inverted winding**, so `contains` would
return the exact complement).

---

## IMG-4 — BANC v888: 81,965 neurons have no image at all · **high** · open

**Affects: Bates2026 (BANC v888).** Measured 2026-08-19 from the KB.

| status | v888 | v626 |
|---|---|---|
| no image at all | **81,965** | 828 |
| brain only | 43,442 | 56,044 |
| VNC only | 13,480 | 14,918 |
| both | 7,624 | 9,042 |

Do **not** plan to reuse v626 images for these: a changed root ID means the segment was
edited, so the old image depicts a shape that no longer exists (`VERSIONING.md` Rule 3).

Source for regeneration: `compiled_data/banc_888/banc_banc_space_swc/<root>_skeleton.swc`
(full resolution, nanometres, BANC space). Do **not** use
`neuron_skeletons/swcs-from-pcg-skel/` — keyed to v626 roots, 404s for v888.

### What the bucket actually provides — full census, 2026-08-25

**There are no mesh LODs.** `neuron_meshes/meshes/info` is a 404, so the layer is the
legacy single-resolution precomputed format, not `neuroglancer_multilod_draco`; a
manifest lists exactly one fragment (`<root>:0:1`). So there is no coarser mesh to fetch
and IMG-1 has no bucket-side fix. What exists is three separate products, not a pyramid:
full mesh, `_skeleton`, `_l2`.

Complete listing of `banc_banc_space_swc/` (186 pages, 185,280 roots). The `_skeleton` and
`_l2` suffixes are **exactly mutually exclusive** — zero roots have both:

| | roots | share | total | mean |
|---|---|---|---|---|
| `_skeleton` only | 108,483 | 58.6% | 36.52 GB | 337 kB |
| `_l2` only | 76,797 | 41.4% | 0.21 GB | 2.7 kB (125× coarser) |

**The 41.4% headline is misleading — it is concentrated in what we care least about.**
`_l2`-only share by `super_class`:

| class | n | `_l2`-only |
|---|---|---|
| glia | 12,225 | 79.7% |
| not_a_neuron / trachea | 258 | ~74% |
| optic_lobe_intrinsic | 72,293 | 51.6% |
| sensory | 16,401 | 30.9% |
| visual_projection | 7,238 | 14.5% |
| central_brain_intrinsic | 31,875 | 10.3% |
| **descending** | 1,316 | **3.6%** |
| ventral_nerve_cord_intrinsic | 12,866 | 2.1% |
| **ascending** | 1,849 | **1.2%** |
| **sensory_ascending** | 517 | **0.6%** |

Restricting to real neurons: 32.3% excluding glia/trachea/not_a_neuron, **13.3%** also
excluding optic lobe. **Among neck crossers — the ones needing both templates — only
2.0%** (73 of 3,695). `_l2`-only neurons are also the small ones (mean cable 291 µm vs
904 µm), so skeletonising their meshes is cheaper than average. So the `_l2` share is
**not** a runtime blocker for the two-template path.

### Mesh coverage is incomplete — new, and the real gap

Mesh manifest presence, 250 roots sampled per group (95% CI):

| | mesh present |
|---|---|
| `_skeleton` roots | **94.4% ± 2.9** |
| `_l2`-only roots | **68.8% ± 5.7** |

So ~31% of `_l2`-only roots have **neither** a full-res skeleton **nor** a mesh — roughly
24,000 roots whose only representation is a 2.7 kB `_l2` skeleton. Not explained by the
root changing between materialisations: changed roots have *better* mesh coverage
(98.0% / 76.0%) than unchanged ones (94.4% / 64.8%), so this is mesh-generation coverage,
not a versioning artefact. Needs its own audit before the loader promises an image for
every neuron.

### The SWC dir is version-clean; the mesh dir is NOT

This asymmetry decides how the loader enumerates its work list.

- **SWCs are cleanly v888.** `compiled_data/` holds only `banc_888` (alongside other
  datasets: `fafb_783`, `fanc_1116`, `hemibrain_121`, `malecns_09`, `manc_121`). Of the
  185,280 roots with an SWC, **all 185,280 are current v888 — zero stale**. Of the 188,508
  v888 roots in `banc_888_meta.feather`: 57.5% `_skeleton`, 40.7% `_l2`, **1.7% (3,228)
  have no SWC at all**.
- **`neuron_meshes/meshes/` is cumulative across materialisations** — it sits under no
  versioned prefix, and **40.8% ± 6.1** of the 69,428 v626 roots that no longer exist in
  v888 still have a mesh manifest, i.e. roughly 28,000 stale meshes.
- `neuron_meshes/segment_properties/` and `segment_properties_v888/` are **identical**
  (both 188,508 ids, 100% matching meta's `root_888`), so despite the directory names the
  properties *are* v888. Only the mesh blobs accumulate.

**Consequence: never enumerate the work list by listing the mesh directory** — it would
pick up ~28,000 dead roots. Drive from `banc_888_meta.feather` / `segment_properties_v888`
and treat mesh presence as a per-root lookup. Correctness is not at risk either way: a root
ID identifies a fixed supervoxel set, so a mesh keyed to root X depicts segment X whenever
it was built (`VERSIONING.md` Rule 3 in reverse). The staleness is dead weight, not wrong
data.

### Confirmed against the producer: `github.com/htem/bancpipeline`

Read 2026-08-25. The upstream pipeline is R-based; two scripts explain every number above.

- **`banc/share/banc-export-skeletons.R`** prefers the detailed skeleton, falls back to L2,
  and **explicitly deletes stale files** (`setdiff(final.ids, valid.ids)` → `file.remove`).
  That is why the SWC directory is 100% v888-clean. It then `gsutil -m rsync`s to the bucket.
- **`banc/transforms/banc-ngl-upload.R`** uploads meshes **append-only** — a `gsutil ls -r`
  snapshot plus a per-id `gsutil stat` skip, and **no stale-removal step at all**. That is
  why the mesh directory accumulates. It is an omission relative to the skeleton path, not
  a glitch.
- The per-neuron body is wrapped in `try({...})`, so a failure inside
  `banc_read_neuron_meshes()` is **silently swallowed** and that neuron simply never gets a
  mesh, with no error surface and no retry. That is the mechanism behind the 94.4% / 68.8%
  coverage gap.
- `segment_properties/` and `segment_properties_v888/` receive **the same v888 JSON** from
  the same `push_segment_properties` calls, which is why they measure identical. The code
  comment above them still claims one holds v626 for user choice — the comment is stale.
- `_skeleton` is made with **skeletor** from the segmentation mesh; `_l2` with **pcg_skel**.
  So IMG-4's advice to skeletonise the mesh for the `_l2`-only share is exactly what
  upstream did.

### The immutable mirror has no neuron meshes

The bucket is explicitly **mutable** — bancpipeline's README: *"mirrored at both the Harvard
Dataverse (frozen, paper version) and the GCS bucket (mutable, evolves with the live
project)"*. The frozen mirror is **`doi:10.7910/DVN/7WTH1N`** (v3.0, released 2026-07-01,
379 files, 536 GB; v888 = "snapshot 2026-04-17" = paper version).

| | frozen Dataverse | mutable bucket |
|---|---|---|
| skeletons | `banc_swc_skeletons.zip`, 16.58 GB | `compiled_data/banc_888/banc_banc_space_swc/` |
| **per-neuron meshes** | **absent** | `neuron_meshes/meshes/` |
| neuropil meshes | `banc_neuropil_meshes.zip`, 44.7 MB | `region_outlines/` |
| elastix registrations | `registration_{brain_jrc2018f,vnc_jrc2018vncf}.zip`, `banc_template_spaces.zip` | `registrations/` |

The only `meshes` entry in the deposit is the **neuropil** zip. There is **no immutable
copy of the per-neuron meshes anywhere** — so mesh-derived images cannot be pinned or
reproduced from an archived source, and a mesh that changes or vanishes from the bucket is
unrecoverable. Skeleton-derived images can be pinned; mesh-derived ones cannot.

**Gotcha if pinning to the DOI:** the skeleton zip deliberately contains **both v888 and
v626 root_ids** ("so users can cross-reference the two"), so it is a *superset* and must be
filtered to v888 ourselves. The bucket already does that filtering but is mutable. Pick one
and record which.

---

## KB-1 — `term_replaced_by` never applied; deprecated IDs dead-end · **medium** · open

**Affects: BANC; check others.** 15,778 of BANC's 15,779 v626-only neurons carry a bare
`deprecated` property, but **zero** carry `term_replaced_by` and there is no relationship of
any kind to their successors. A cited or bookmarked VFB ID therefore dead-ends instead of
redirecting.

Not a curation-transfer problem — typing is correctly re-derived each release
(`VERSIONING.md` Rule 2). This is identifier continuity only, and it is **only well defined
for 1:1 succession**: a split or merge has no single successor, so this needs per-case
judgement, never a bulk join over a mapping table.

---

## KB-2 — No version-stable identity anchor for any connectome · **medium** · open

There is **no supervoxel `Site` in the KB at all**. `BANC_import.py:23` writes a
`flywire_banc:` dbxref to a Site that does not exist (the real ones are `BANC626` /
`BANC888`), and `flywire_import.py:61` writes `flywire_supervoxel:` but the KB holds only
`flywire783` and `neuronbridge`.

Consequence: identity is keyed on per-release root IDs, so an edited neuron looks like a
deletion plus an unrelated creation. Adding a supervoxel (or nucleus/representative-point)
Site is the single change that would make cross-release identity tractable. See
`VERSIONING.md` Rule 5.

---

## KB-3 — BANC has 65,053 duplicate `in_register_with` edges · **low** · open

**Affects: Bates2025 and Bates2026.** The brain template carries 211,564 edges over 146,511
distinct channels in v888 (145,885 over 80,832 in v626). The excess is exactly the
carried-over set: the same channel has two *identical* brain edges, same `filename`, same
`folder` — evidently a second edge added by the v888 load for neurons it recognised as
already present.

Harmless today (PDB publishes per populated edge, not per edge) but it makes every edge
count misleading, which cost real time during this investigation.

---

## CODE-1 — `avoid=['BANC']` is worse than no avoid at all · **medium** · open

The six elastix-backed transform edges are on **`BANCum`**, not `BANC`, so excluding `BANC`
reroutes the path search *onto* them. Measured:

| call | result |
|---|---|
| maleCNS brain, no avoid | OK |
| maleCNS brain, `avoid=['BANC']` | **FAIL** — elastix |
| maleCNS brain, `avoid=['BANC','BANCum']` | OK |

The maleCNS VNC loader survives only incidentally, because it also excludes
`JRCVNC2018F`. Always exclude both names.

---

## CODE-2 — `except Exception` cannot catch navis's missing-elastix error · **medium** · open

`navis/transforms/elastix.py:162` raises **`BaseException`**, which `except Exception as e`
does not catch. Every loader wraps per-neuron work that way, so a missing or misconfigured
elastix kills the whole job instead of skipping one neuron — with a traceback about elastix
rather than anything domain-specific.

elastix itself is easy: SuperElastix release 5.3.1 `elastix-5.3.1-macos.zip` ships a native
**arm64** `transformix`, no quarantine issue. Needs the bin dir on `PATH` and the lib dir on
`DYLD_LIBRARY_PATH` (`LD_LIBRARY_PATH` on Linux). Not in homebrew; `itk-elastix` on PyPI
does **not** satisfy it (navis shells out to the CLI).

---

## CODE-3 — `flywire_import.py` routes a female brain through the male template · **low** · open

`flywire_import.py:215` forces `via='JRCFIB2022M'` with the comment *"needs via to work
currently"*. **Correction 2026-08-24:** with flybrains 0.6.3 that call no longer resolves to
the short route described below at all — it resolves to a 16-hop path through BANC, FANC and
MANC. See **CODE-4**, which is the reason to remove the `via` and supersedes the routing
described here; the z-offset analysis below still stands for the intended route. That
intended route goes through **JRC2018M**, the leg
[navis-flybrains#24](https://github.com/navis-org/navis-flybrains/issues/24) reports as
carrying a +25 voxel z-offset. The direct route
`FLYWIRE → FLYWIREum → JRC2018F → JRC2018U` now resolves cleanly and is one hop shorter, so
the workaround appears obsolete.

Measured impact on VFB: **none.** The offset cancels before reaching JRC2018U — two routes
agree to 0.12 µm in z, and an absolute check against the JRC2018U neuropil surface gives
best dz = **+0.0 µm** (versus **+10.0 µm / +26.3 voxels** into JRC2018M, independently
reproducing the issue). Worth removing anyway to stop depending on a disputed leg.

---

## CODE-4 — `via=` bypasses the weighted path search; both uses resolve to garbage · **high** · open

`TemplateRegistry.find_bridging_path` calls `nx.shortest_path(..., weight='weight')` **only
when neither `via` nor `avoid` is set**. Otherwise it walks `nx.all_simple_paths` and breaks
on the first path satisfying the constraint — DFS order, unweighted, no length minimisation
(`navis/transforms/templates.py:451-467`). `via=` therefore means "any path that happens to
touch this node", not "go this way".

Measured 2026-08-24, navis 1.12.0 + flybrains 0.6.3:

| call | resolves to |
|---|---|
| `flywire_import.py:84,215,233` — `FLYWIRE→JRC2018U via='JRCFIB2022M'` | **16 hops**, via `FAFB14 → JRC2018F → BANCum → JRCVNC2018F → FANC → MANC → JRCFIB2022Mum → JRC2018M` — 3× elastix, 2× CMTK, through the **ventral nerve cord** |
| `MANC_import.py:73` — `MANCraw→JRCVNC2018U via='JRCVNC2018M'` | **19 hops**, out to the brain templates and back |
| same, no `via` | 3 and 4 hops respectively |

This is also the mechanism behind CODE-1 — passing either kwarg drops you out of the
weighted search, so a constraint that looks tightening can hand you a far worse path.

Fix: drop `via` on `MANC_import.py:73` (unconstrained is already correct); on FlyWire remove
it per CODE-3, or if kept use `avoid=['BANCum','FAFB14']` and **assert the resolved path**.
A one-line CI assertion on `find_bridging_path` catches the next flybrains upgrade, which
will move these routes again. Details and the assertion:
[`TRANSFORMS.md`](TRANSFORMS.md) §1.

---

## CODE-5 — a broken `cloudvolume` import is reported as "no mesh" for every neuron · **high** · open

**Affects: `images/loader.py`.** Found 2026-08-26 while fetching the BANC APL for the
IMG-1 comparison.

`fetch_mesh()` wraps the whole fetch in `except Exception: return None`, documented as
"a missing mesh is expected, not exceptional" (true — IMG-4). But `from cloudvolume import
CloudVolume` happens *inside* that guard, via `_cv()`. On this machine that import fails:

```
ImportError: dlopen(.../zfpy.cpython-310-darwin.so): symbol not found in flat namespace '_stream_close'
```

`cloudvolume.chunks` imports `zfpc`, which imports the broken `zfpy`. So **every** call
returns `None`, and every neuron is logged as mesh-absent. Verified the meshes are really
there: `neuron_meshes/meshes/720575941482622627:0` is a 200 with one fragment, and the
fragment `…:0:1` is a 200 of 125,417,824 bytes that parses to 3,409,638 verts / 7,041,847
faces.

Consequences:

- A run on an agent with this breakage silently writes **skeleton-only** output for all
  188,508 neurons — SWC and a skeleton-derived NRRD, no OBJ — and the ledger records it as
  legitimate `no_source`/`empty_here`, so a restart never retries.
- **IMG-4's coverage census may be understated.** That census should be re-derived with a
  client that cannot fail this way before its numbers are trusted.

Same family as CODE-2: a broad `except` around a block that contains both the expected
failure (absent object) and an unrelated fatal one (import/config error).

**Fix:** import `cloudvolume` at module import time, or at worker start, so an environment
failure is loud and immediate; keep the narrow `except` around the `mesh.get` call only.
Distinguish "absent" from "could not ask" in the ledger status. Independently, either pin a
working `zfpy` or fetch the fragments over plain HTTPS — the format is trivial
(`uint32 n`, `float32[n][3]` vertices, `uint32[][3]` indices) and needs no credentials.

---

## MESH-1 — VFB serves fragmented skeletons for BANC · **high** · open

**Affects: BANC; check every mesh-derived skeleton.** Measured 2026-08-24 on MBON03:

| | nodes | roots |
|---|---|---|
| BANC published `<root>_skeleton.swc` | 29,127 | **1** — one connected tree |
| VFB served `volume.swc` | 30,225 | **1,112** — fragmented |

1,112 roots is exactly the mesh's component count, so the skeleton was produced by
skeletonising the mesh (one tree per mesh component) with **no healing step** — i.e.
`navis.skeletonize(mesh)` without `navis.heal_skeleton()`. That is what the BANC repair
script does.

This matters more than the mesh issues, because cross-neuron comparison runs on skeletons.
Anything requiring connectivity — geodesic distance, cable length, pruning, splitting —
is broken on these. NBLAST happens to survive, since it uses point/tangent clouds rather
than topology.

**Fix:** use BANC's published `compiled_data/banc_888/banc_banc_space_swc/<root>_skeleton.swc`
directly. Single tree, 29,127 nodes, 1.86 MB, nanometres, BANC space. No skeletonising and
no healing needed. See IMG-4 for the `_skeleton` vs `_l2` availability caveat.

---

## MESH-2 — "component count" is mostly debris, except FlyWire · **low** · open

Measured 2026-08-24. Largest connected component as a share of each mesh:

| mesh | largest component | dust | saving if dust dropped |
|---|---|---|---|
| banc_MBON03 | 99.14% of faces | 0.86% | 0.41 MB of 45.1 |
| hemibrain_APL | 97.17% | 2.83% | 2.52 MB of 93.5 |
| maleCNS_APL_R | 97.43% | 2.57% | 11.89 MB of 514.8 |
| opticlobe_APL | 96.14% | 3.86% | 21.68 MB of 625.8 |
| **flywire_APL** | **47.39%** | **52.61%** | 133.80 MB of 281.4 |

For four of five the thousands of components are sub-µm² debris (16,884 of maleCNS's 17,008
are under 1 µm², holding 0.44% of the area). Stripping it gives a cleaner display and a
genuinely single-component mesh, but is a 1–4% size win — not a fix.

**FlyWire is the real exception and probably a separate bug:** its largest component holds
only 47%, and the runner-up is a 16,103 µm² / 1.67M-face piece — a second major chunk of
neuron, not debris, followed by 3,591 / 2,424 / 2,320 / 1,438 µm² pieces. Worth
investigating on its own; possibly a reconstruction or transform artefact.

**Consequence for any cleanup rule:** it must be **threshold-based** (drop components below
~1 µm², or below some fraction of the largest). A "keep only the largest component" rule
would delete over half of the FlyWire APL.

**Largely moot as of 2026-08-26:** the IMG-1 decimation removes most of this dust for free —
maleCNS APL goes 17,008 → 2,284 components at 37 f/µm², with the largest component's share
*rising* from 98.11% to 98.38%. No separate dust-stripping pass is needed. FlyWire's second
major chunk survives decimation, as it should, so the threshold caveat above still stands
for anything that does try to prune components.

---

## MESH-3 — CATMAID/FAFB served OBJ is a point cloud with zero faces · **medium** · open

**Affects: Zheng2018 / Baltruschat2021 (CATMAID FAFB).** Found 2026-08-26 while measuring
mesh density for IMG-1.

`.../i/0010/1220/VFB_00101567/volume_man.obj` (APL 203841) is 1.89 MB of **33,600 `v` lines
and nothing else** — no `f`, no `l`, no `g`. Header is `# OBJ File Generated by
VirtualFlyBrain.org`, so this is our own writer, not upstream.

This is why CATMAID looked anomalously well-behaved in the IMG-1 size table: it is not a
small mesh, it is not a mesh. Any viewer expecting a surface gets an empty render; anything
that does draw it is drawing vertices.

Likely cause: the writer was handed a skeleton or a point cloud and wrote vertices without
ever building faces. Check every CATMAID-derived `volume_man.obj`, not just APL, and check
whether the same writer path is used by any other dataset.

---

## Fixed / closed

*(nothing yet)*
