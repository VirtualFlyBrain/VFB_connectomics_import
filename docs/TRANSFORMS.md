# Transforms: how BANC and maleCNS reach the VFB templates

Settled 2026-08-25. Verified against **navis 1.9.1 / flybrains 0.6.3 / elastix 5.3.1**.

Companion docs: [`ISSUES.md`](ISSUES.md) for the cut/trim algorithm and open defects,
[`VERSIONING.md`](VERSIONING.md) for identity across releases.

---

## The paths

Both are the 3-hop minimum and `find_bridging_path` selects them unaided.

```
BANC -> JRC2018U        BANC -> BANCum -> JRC2018F -> JRC2018U
  1. AffineTransform    diag [0.001, 0.001, 0.001]        nm -> um
  2. ElastixTransform   <flybrains>/data/BANC_JRC2018F/BANC_to_template.txt
  3. H5transform        ~/flybrain-data/JRC2018U_JRC2018F.h5

BANC -> JRCVNC2018U     BANC -> BANCum -> JRCVNC2018F -> JRCVNC2018U
  1. AffineTransform    diag [0.001, 0.001, 0.001]        nm -> um
  2. ElastixTransform   <flybrains>/data/BANC_JRCVNC2018F/BANC_to_template.txt
  3. H5transform        ~/flybrain-data/JRCVNC2018U_JRCVNC2018F.h5

maleCNS brain           JRCFIB2022Mraw -> JRCFIB2022M -> JRCFIB2022Mum -> JRC2018M -> JRC2018U
maleCNS vnc             ... -> MANCum -> JRCVNC2018M -> JRCVNC2018U     (needs via='MANCum')
```

**Use no `via` and no `avoid` for a BANC source.** Both bypass Dijkstra entirely — navis
switches to `all_simple_paths` and takes the first match, giving 16–19 hop garbage paths —
and they also cause a baked transform's `weight` to be ignored. The `avoid=['BANC','BANCum']`
needed by *other* datasets removes the only available path here.

**maleCNS VNC does need `via='MANCum'`**, and for a good reason: unrouted it detours through
BANC, sending a *male* volume through a *female* CNS into the *female* VNC template. The
`via` forces male EM -> male VNC template. That existing choice in the loader is correct.

---

## Why the BANC legs are baked and the JRC legs are not

The JRC hops **already are** dense fields — that is what the `.h5` files are: int16
deformation grids with the affine in an attribute, a quantisation multiplier, multi-resolution
levels, and forward plus inverse. Nothing needs doing there.

Only the BANC hops are parametric, because:

- elastix emits `TransformParameters` text files and BANC published its registration
  working directory as-is (`registrations/brain_240721/` includes `register_brain.sh`)
- parametric is **27x smaller** — 8.3 MB of B-spline coefficients vs 223 MB dense
- baking forces choices (bounds, spacing, out-of-domain behaviour) that only the consumer
  can make, and is lossy in a way the parametric form is not
- nobody had needed per-neuron BANC->template transforms at 80k scale before

`flybrains` is a distribution layer: it registers whatever each project shipped, and does
not transcode. So this is not an oversight — we are simply the first consumer who needs the
other form.

**Cost of not baking:** the elastix hop is ~0.35 s of process spawn per call plus ~9.8 us
per point. On a 598k-vertex mesh that is 5.9 s, **92% of the whole chain**.

---

## The baked fields

Built by [`src/vfb_connectomics_import/images/bake_fields.py`](src/vfb_connectomics_import/images/bake_fields.py),
consumed by [`banc_baked.py`](src/vfb_connectomics_import/images/transforms.py).

| | grid | spacing | size |
|---|---|---|---|
| `banc_brain_2um.npy` -> JRC2018F | (445, 263, 159, 3) | 2 µm | 213 MB |
| `banc_vnc_2um.npy` -> JRCVNC2018F | (445, 407, 159, 3) | 2 µm | 330 MB |

Form: a dense **coordinate** lookup table (absolute output coordinates, not displacements),
float32, on a regular grid over BANC nanometres. Lookup is trilinear via
`scipy.ndimage.map_coordinates(order=1)`. A sidecar `.json` carries `lo`/`step`/`target` so
the grid can never be orphaned from its array.

**Accuracy: 5.5–13.7 nm mean, 75 nm max** across four neurons and both halves, against an
8 nm source voxel and a ~520 nm template voxel.

**Not committed to git** (543 MB). Default location `~/Documents/banc_transform_fields`,
overridable with `$BANC_FIELD_DIR`.

**Kept internal — not published.** Decided 2026-08-25. The functionality already exists
for anyone who wants it: the elastix registrations are public and `flybrains` registers
them, so a user transforming a handful of neurons is already served. Baking only matters
at whole-dataset scale, which is our problem, not a general one. So these fields are a
build input for our jobs, not a data product.

This also corrects an earlier note here that said to "publish them the way VFB already
publishes transforms — `flybrains.download_vfb_transforms()` exists". That function
**git-clones the `VfbBridgingRegistrations` repo** into `$FLYBRAINS_DATA` and is sized for
~6 MB of CMTK files. It is not a mechanism for 543 MB of `.npy`, so it was never the
ready-made route implied.

### Registration

`register()` adds them as `FunctionTransform` edges with `weight=0.1`. navis' registry is a
`MultiDiGraph`, so they sit *alongside* the elastix edges rather than replacing them, and
`nx.shortest_path(weight='weight')` prefers them. The path collapses 3 hops to 2 and elastix
disappears:

```
before:  BANC -> BANCum -> JRC2018F -> JRC2018U   (Affine, Elastix, H5)
after:   BANC -> JRC2018F -> JRC2018U             (FunctionTransform, H5)
```

The elastix transforms remain available as a fallback and for verification.

### NaN outside the grid — do not remove this

`map_coordinates(mode='nearest')` **clamps** outside the grid rather than failing. With an
earlier field whose y ceiling (320,000) did not match the cut plane (370,000), 185 nodes were
clamped up to **51.6 µm** off — and because clamping pulls them back inside the template, the
bbox trim then *kept* them: 93 nodes disagreed on keep/drop against the exact chain.
`BakedField.__call__` returns NaN outside the grid for exactly this reason. Run
`banc_baked.self_check()` at job startup; it asserts that out-of-domain is rejected.

---

## Why displacements / int16 / a coarser grid were not used

Measured on the brain field:

| form | mean magnitude | int16 step | quant error | zlib |
|---|---|---|---|---|
| absolute coordinates (what we ship) | 493.55 µm | 28.3 nm | 13.6 nm | 1.17x |
| displacement `out - in` | 225.43 µm | 9.4 nm | 4.5 nm | 1.15x |
| residual `out - Affine(in)` | 49.96 µm | 7.4 nm | 3.5 nm | 1.13x |

- **Plain displacements buy nothing.** Identical to absolute under trilinear interpolation
  (measured 0.013 nm difference), and the registration carries a large affine (~0.77 scale
  plus real rotation) so `out - in` is still 225 µm.
- **Compression is a dead end** — 1.13–1.17x for all three; float32 mantissas are
  high-entropy at the bit level.
- **int16 would halve the files for free** (all quant errors are far below the 8 nm source
  voxel), and affine-factored residuals would allow a coarser grid — 8 µm would be 64x fewer
  nodes. That is the real size lever if 543 MB ever becomes a problem. Not done yet.

This is, incidentally, exactly the format the `.h5` files already use. Worth matching if the
fields are ever published widely.

---

## Performance, and why the tail hops were left alone

Per-point cost, measured:

| | µs/point |
|---|---|
| elastix (per call, plus ~0.35 s fixed) | 9.8 |
| H5transform, cold | ~11–19 |
| H5transform, warm cache | ~11 |
| **baked field, memmapped** | **0.2–0.35** |

The baked lookup has **no fixed per-call cost** — 0.35 µs/point at 2,469 points and at
25,000. So **batching is not needed**; the old pipeline wanted it only to amortise elastix's
per-call spawn.

The remaining H5 hop is now the slower half (~11 µs/point) but the transform stage as a
whole is ~0.1% of per-neuron runtime, which is dominated by fetch:

```
fetch skeleton   0.56 s
fetch mesh       1.92 s   <- 62%
cut              ~0
transform        ~0.005 s <- was 5.9 s of elastix
write SWC + OBJ  1.03 s
                ------
                 ~3.5 s   -> 81,965 neurons ~= 10 h on 8 workers
```

So the H5 tails are deliberately **not** baked: it would duplicate data that is already
dense and already correct, to optimise 0.1% of runtime.

The one real argument for baking them is memory, not speed:

| | per worker | 8 workers |
|---|---|---|
| `H5transform.full_ingest()` | 11.6 s startup, **4.6 GB resident** | ~37 GB |
| memmapped `.npy` | 0 s, **0 GB** (page cache) | **543 MB shared** |

Memmapped arrays are shared by the OS page cache across any number of readers with no fork
requirement; `h5py` handles are additionally **not fork-safe**. Revisit only if worker memory
becomes a constraint.

Also ruled out: the H5 multi-resolution levels are not a speed lever — level 1 and 2 gave
**23 µm mean error** against level 0 and were *slower*.

---

## Deployment shape

- Ship the fields on **local disk** (memmapping a network mount defeats it). Preferred:
  a persistent cache directory on each Jenkins agent, populated by an idempotent stage
  step that fetches only when absent and verifies a checksum — rather than a 543 MB
  container layer. `$BANC_FIELD_DIR` points at it.
- `banc_baked.register()` then `banc_baked.self_check()` once per process at startup.
- Workers stay **one neuron at a time**; no batching. Worker count is set by network and
  data-server write throughput, not memory or CPU.
- No elastix in the image. Existing `redo`/skip logic is unchanged.
- ~543 MB of `.npy` replaces the `transformix` binary and its runtime dependency.
  int16 would halve this for free (see above) if transfer or image size ever matters.

### Two data dependencies, not one

The job needs **both** halves of the chain on the agent:

| what | where | how it gets there |
|---|---|---|
| baked BANC fields (543 MB) | `$BANC_FIELD_DIR` | ours; staged, see above |
| Saalfeld H5 bridging registrations | `$FLYBRAINS_DATA` (default `~/flybrain-data`) | `flybrains.download_jrc_transforms()` / `download_jrc_vnc_transforms()` |

`JRC2018U_JRC2018F.h5` and `JRCVNC2018U_JRCVNC2018F.h5` are the tail hop. They have a
supported fetch, but must be cached on the agent or every build re-downloads them.

Note neither comes from the BANC bucket. The bucket supplies the *geometry*; these two
supply the *transform*.

### Bucket access needs no credentials — but cloudvolume does need `use_https=True`

Verified 2026-08-25 from an isolated `HOME` with no `~/.cloudvolume`, no gcloud ADC and no
`GOOGLE_APPLICATION_CREDENTIALS`. Everything the loader reads is anonymous HTTPS against
`storage.googleapis.com`:

| | how |
|---|---|
| `banc_888_meta.feather` (work list) | plain HTTPS GET |
| `..._skeleton.swc` / `..._l2.swc` | plain HTTPS GET |
| mesh manifest `<root>:0` + fragment `<root>:0:1` | plain HTTPS GET |

No CAVE token, no SeaTable, no `caveclient`. The agent needs only outbound HTTPS to
`storage.googleapis.com`.

**The trap:** `CloudVolume('precomputed://gs://...')` without `use_https=True` falls through
to the `google-cloud-python` client and dies with `DefaultCredentialsError` — it only works
locally if the developer happens to have ADC. With `use_https=True` it reads the same bucket
anonymously. Always pass it:

```python
CloudVolume(f'precomputed://gs://{BUCKET}/neuron_meshes', use_https=True, progress=False)
```

Keep cloudvolume rather than hand-rolling the two GETs: the fragments are uploaded with
`compress=TRUE`, so something has to decode the precomputed/draco payload.

### Data staging: bulk for skeletons, parallel fetch for meshes

Measured 2026-08-25 by listing both layers in full.

| | size | shape |
|---|---|---|
| skeletons, bucket | **36.73 GB** (36.52 `_skeleton` + 0.21 `_l2`) | 185,280 loose files, already v888-clean |
| skeletons, Dataverse | **16.58 GB** | **one zip**, DOI-pinned, mixes v888 + v626 |
| meshes, bucket | **229.89 GB** | 184,307 meshes, mean 1.25 MB, exactly 1 fragment each |
| meshes, Dataverse | — | **no archive exists** |

**Skeletons: bulk-download once, then read locally.** Per-neuron fetching costs ~0.52 s of
*fixed* request latency, which across 81,965 neurons is **~11.8 h of pure latency** — more
than the elastix bake saved. One 36.73 GB pull at 100 MB/s is ~6 min, after which every
per-neuron read is a local file open. Prefer the Dataverse zip if reproducibility matters
(one request, DOI-pinned) but **filter to `root_888` yourself** — it deliberately carries
both materialisations. The bucket directory is pre-filtered but mutable.

**Meshes: there is nothing to bulk-download to.** With no archive, bulk and per-neuron make
the *same* two requests per neuron (manifest + fragment); `gsutil -m rsync` merely runs them
concurrently. So the lever is **concurrency, not bulk** — ~24 h of serialised latency
collapses to under an hour at 32 threads. Fetch only the roots needed (~102 GB for 82k
neurons); do **not** mirror the whole layer, since ~35 GB of it is stale v626 roots.

**Agent disk sizing** is mesh-driven: 36.73 GB of skeletons is trivial, but 102–230 GB of
mesh on top of the 543 MB of baked fields is a real provisioning ask. Another reason to
ship skeletons first.

### How a missing field is caught

`banc_baked` is **strict by default** as of 2026-08-25, because the fallback was silent:

- `resolve_field_dir()` reads `$BANC_FIELD_DIR` **at call time** (not import time) and
  reports which of the three sources chose the directory. `built-in default` in a build
  log means the env var was never set on the agent.
- `register()` raises `MissingFieldsError` when a field is absent, naming the paths and
  the fix. `required=False` restores the old graceful fallback for interactive use.
- `self_check()` asserts the **expected** field set. It previously iterated whatever
  `load()` returned, so with zero fields on disk it found no problems and returned
  `True` — passing vacuously in exactly the case it existed to catch.
- `assert_baked_path()` (called by `self_check`) asserts no `ElastixTransform` survives in
  the path to `JRC2018F`/`JRC2018U`/`JRCVNC2018F`/`JRCVNC2018U`. Fields on disk are
  necessary but not sufficient — this catches `register()` never running, and a caller
  passing `via=`/`avoid=`, which bypass weighting entirely.

Without these, a misconfigured agent either dies with an error `except Exception` cannot
catch (`ISSUES.md` CODE-2) or, if transformix happens to be installed, quietly runs ~30x
slower and emits correct-looking output.
