# Validating the template transforms with neuropil ROIs

**Status: designed, not implemented.** Written 2026-08-25 as a handoff. Nothing in this
document has been run — the environment blocker in §6 stops all of it. Everything in §1–§3
was verified live against the public endpoints on that date; §4–§5 are the plan.

The question this answers: *how do we know a BANC or maleCNS neuron actually lands in the
right place in JRC2018Unisex?* The current acceptance check is a bounding-box test, and
[`ISSUES.md`](ISSUES.md) IMG-3 already records a case where the existing VFB image **passes
the bbox test while sitting outside the neuropil**. ROI overlap is the replacement.

Related: [`ISSUES.md`](ISSUES.md) IMG-2/IMG-3/IMG-4, CODE-1/CODE-2/CODE-4 ·
[`TRANSFORMS.md`](TRANSFORMS.md) §1 (routing) · [`VERSIONING.md`](VERSIONING.md)

---

## 1. The reference side: VFB already serves it

VFB hosts painted neuropil domains on both target templates as one OBJ per domain, on the
public file server, no auth.

| template | channel short_form | domains | parcellation |
|---|---|---|---|
| JRC2018Unisex | `VFBc_00101567` | **46** | ITO (AL, MB CA/PED/aL/a'L/bL/b'L/gL, FB, EB, PB, NO, BU, GA, LAL, LH, SLP, SIP, SMP, CRE, ROB, RUB, SCL, ICL, IB, ATL, VES, EPA, GOR, SPS, IPS, SAD, AMMC, FLA, CAN, PRW, GNG, AOTU, AVLP, PVLP, PLP, WED, ME, AME, LO, LOP) |
| JRC2018UnisexVNC | `VFBc_00200000` | **21** | COURT (ProNM/MesoNM/MetaNM, ANm, AMNP, HTct, IntTct, LTct, NTct, WTct, mVAC, + DLT, DLV, DMT, MDA, VLT, ITD, ITD-CFF, ITD-HC, ITD-HT, VTV tracts) |

Mesh URL pattern — split the numeric part of the short_form 4/4:

```
https://www.virtualflybrain.org/data/VFB/i/<first4>/<last4>/<template_short_form>/volume.obj

# verified 2026-08-25:
.../i/0010/2201/VFB_00101567/volume.obj   # AL on JRC2018Unisex — HTTP 200, 5,634,100 bytes
.../i/0010/1567/VFB_00101567/volume.obj   # the template surface itself — HTTP 200
```

Enumerate the domains from the **public** VFB neo4j (basic auth `neo4j:neo4j`, no KB creds
needed — do not use `.env`'s `KB_USER`/`KB_PASSWORD` for this):

```bash
curl -s -u neo4j:neo4j -H "Content-Type: application/json" \
  -X POST https://pdb.virtualflybrain.org/db/data/transaction/commit \
  -d '{"statements":[{"statement":
      "MATCH (c)-[r:in_register_with]->(tc {short_form:\"VFBc_00101567\"})
       WHERE r.index IS NOT NULL
       MATCH (c)-[:depicts]->(d)
       RETURN d.short_form, d.label, r.index[0] AS idx ORDER BY idx"}]}'
```

Gotchas found the hard way:
- The template **Individual** is `VFB_00101567`; the thing domains are `in_register_with` is
  the **Channel** `VFBc_00101567`. Querying the Individual returns nothing.
- Direction is `(channel)-[:depicts]->(anatomy)`, not the reverse.
- `r.index` is a **list**; use `r.index[0]`.
- `VFB_001015xx` short_forms are neurons, not domains — the JRC2018U domains are
  `VFB_001021xx` / `VFB_00102271–2282`; the VNC domains are `VFB_00104633–4653`.
- VFB's brain domains appear **unsided** (46 domains vs ITO's 75 sided regions), so merge
  `_L`/`_R` on the EM side before comparing. **Verify this before trusting a Dice number** —
  it has not been confirmed by inspecting a mesh.

---

## 2. The trap: BANC's own ROIs are imported atlases, not independent anatomy

`gs://lee-lab_brain-and-nerve-cord-fly-connectome/region_outlines/` is a Neuroglancer
precomputed segmentation with 311 named segments. Names come from
`region_outlines/segment_properties/info` (inline `label` property, 311 ids).

| prefix | n | where it came from |
|---|---|---|
| `SCHLEGEL_glomerulus_*` | 116 | FAFB/FlyWire AL glomeruli |
| `MANC_vnc_*`, `MANC_tract_*`, `MANC_nerve_*` | 83 | MANC v1.2.1 |
| `ITO_midbrain_*`, `ITO_optic_*` | 75 | ITO standard brain parcellation |
| `COURT_vnc_*` | 28 | JRC2018 VNC atlas |
| `BANC_*` (segids 1–4) | 4 | **BANC-native** |
| coarse groupings (segids 5–9) | 5 | `midbrain`, `optic`, `MB`, `CX`, `hemibrain` |

`documentation/banc_neuropil_meshes.md` provenance step 5 is explicit: *"Register neuropil
meshes defined in other works (central brain, VNC) into BANC space using the elastix
registrations also deposited here."* There is a `region_outlines/JRC2018_VNC_to_BANC/`
directory in the same bucket.

**Consequence:** transforming `ITO_midbrain_AL_L` from BANC into JRC2018U and comparing it
to VFB's `AL` domain measures **forward∘inverse round-trip consistency of the elastix
registration, not its anatomical accuracy.** Do not report it as accuracy.

Only segids 1–4 are independent: `BANC_dataset` (segmentation-mask outer surface),
`BANC_neuropil`, `BANC_brain_neuropil`, `BANC_vnc_neuropil` — alpha-shapes fitted to
predicted presynaptic-site density (α = 7.5 µm). Coarse, but honest.

**Units.** The layer `info` says `resolution: [8, 8, 45]` — matching flybrains' `BANC`
space. `documentation/banc_neuropil_meshes.md` says "BANC voxel space (4 × 4 × 45 nm)".
**The `info` is authoritative for these meshes.** This is the same factor-2 trap that bit
the neck-connective plane (mip0 CAVE coords are 4×4×45, flybrains' `BANC` is 8×8×45).
Precomputed mesh vertices are already in nm = voxel × resolution, so they should drop
straight into flybrains `BANC` space with no scaling — **assert this on a known region
(e.g. `BANC_brain_neuropil` bbox vs `flybrains/meshes/BANC_brain.ply`) before running
anything else.**

**maleCNS and MANC are not affected by this.** Their ROIs were segmented on the EM volume
and are served via neuprint, independent of any light-microscopy template. For those two
datasets the ROI-overlap test *is* a genuine accuracy measurement.

---

## 3. What was checked, and what was not

Verified live 2026-08-25:
- VFB domain counts, labels, short_forms, and the neo4j query above (both templates).
- One VFB domain OBJ fetches (AL, HTTP 200, 5.6 MB).
- BANC bucket top-level prefixes; `region_outlines/{info, segment_properties/info}`;
  the 311 segment names and their prefix breakdown.
- Contents of `documentation/{banc_neuropil_meshes, banc_template_spaces,
  synapse_neuropil_lookup_v3}.md`.

**Not** checked: whether VFB brain domains are truly unsided; whether the precomputed mesh
fragments parse cleanly; neuprint ROI mesh availability for maleCNS/MANC (needs a token —
none is in `.env`, which only has `KB_USER`/`KB_PASSWORD`); anything requiring navis.

---

## 4. Test 1 — ROI overlap (run this first)

Round-trip for BANC, genuine accuracy for maleCNS/MANC. Either way it is the cheapest test
that fails on the bugs we actually have.

1. Fetch the source ROI meshes (BANC: `region_outlines/` precomputed; maleCNS/MANC:
   neuprint `fetch_roi_mesh`).
2. Transform through the **production** chain — same code path the image loader uses, no
   `via`, no `avoid` for a BANC source (`ISSUES.md` "Verified transform paths (BANC)").
3. Fetch the matching VFB domain OBJ, merge `_L`/`_R` on the EM side.
4. Voxelize **both** at 1–2 µm in template space. Do not do mesh-to-mesh Hausdorff — these
   meshes are not reliably watertight (`flybrains`' BANC PLYs are not, per
   `ISSUES.md`/notes, and the alpha-shape surfaces are only "remeshed until closed").
5. Report per ROI: **Dice**, **centroid offset (µm)**, **95th-pct surface distance (µm)**.

**Do not hard-code a pass threshold.** Calibrate against FlyWire→JRC2018U, which is already
in production and known-good, and flag regressions relative to that. EM-vs-LM parcellations
genuinely disagree at boundaries, so an absolute Dice cutoff will either pass everything or
fail everything.

Why it is worth running despite §2: IMG-2 (whole neuron written to both templates), IMG-3
(~4,660 spurious brain images), CODE-1 and CODE-4 (routing resolves to 16–19 hop garbage),
and the identity-extrapolation fallback are all **wiring** bugs. A per-ROI Dice test fails
hard on every one of them. The bbox test misses them all.

---

## 5. Tests that are not circular, ranked by value/effort

**5.1 Per-synapse ROI label agreement — best value.**
`synapses/v3.0/synapse_neuropil_lookup_v3.parquet` (2.2 GB, 259,393,451 rows) gives every
v3 synapse a `neuropil`, `neuropil_detailed`, `region` and `side` label. Sample ~1M, join
coordinates from `banc_888_synapses_v3_enriched.parquet`, push through the production
transform, point-in-mesh against the VFB JRC2018U domains, build a confusion matrix.
Millions of real points weighted by real synapse density, and it localises *which* regions
the transform gets wrong. Same idea for maleCNS via neuprint's per-synapse ROI columns.
Caveat: BANC's labels were themselves assigned against ITO meshes registered into BANC, so
it inherits some of §2's circularity — but the *point set* is real data, so it still
exposes local distortion and identity extrapolation.
Watch out: `id` is `large_string` here and `int64` in the NT parquet; `region` vocabulary is
unnormalised (`brain`, `central_brain`, `neck`, `sez`, `optic_lobes`, `vnc`, `outside`).

**5.2 The authors' own warped stain — most decisive wiring check.**
`templates/banc-synapses-v1.1-brain_aligned240721_to_JRC2018F_brain.ng` is BANC synapse
density already warped into JRC2018F *by the BANC team* (`240721` is the canonical run;
`240720` is a sibling run — do not mix them). Rasterise our transformed synapse cloud at the
same resolution and correlate. This isolates **"did we implement their registration
correctly"** from **"is their registration any good"** — which is the question actually
blocking us. The VNC counterpart is
`banc-synapses-v1.1-VNC_aligned240721_to_JRC2018F_VNC.ng`.

**5.3 Landmark residual — 5-second CI assertion.**
`registrations/brain_240721/corresponding_points_*_{JRC2018F,banc}.txt` and the `vnc_240721`
equivalents. These are the registration's own training data, so the residual is optimistic
and must not be quoted as accuracy — but it catches unit errors, axis flips and direction
reversals instantly. Add it next to the `find_bridging_path` path assertion already
proposed in `TRANSFORMS.md` §1.

**5.4 Expert-confirmed cross-dataset pairs — real independent evidence.**
`nblast/banc_malecns_v0.9_nblast.feather` plus `banc_malecns_reviewed_matches.csv` (expert
accept/reject with a `validation` flag), and `imported_meshes/malecns_v0.9_meshes_navis_
tpsreg_250206/` for the BANC-space versions. Take confirmed pairs, push each half into
JRC2018U through **its own independent chain**, measure NN distance. Two independently-built
registrations agreeing is genuine evidence — and it validates BANC and maleCNS in one pass,
which is exactly the pair being fixed. `banc_manc_reviewed_matches.csv` does the same for
the VNC.

**5.5 Soma sanity — cheap smoke test.**
Somas (`nuclei/`, `somas_v1`) must land in the cortex rind, i.e. **outside** every neuropil
mesh. A subtly collapsed or over-smoothed transform pulls them inside.

---

## 6. Blocker — read this before starting

**No python on this machine has navis + flybrains** (checked 2026-08-25):

- `.venv/` contains only pip/setuptools — no navis, flybrains, neuprint, cloudvolume,
  trimesh or nrrd.
- System python is `/Library/Frameworks/Python.framework/Versions/3.10` (3.10.4), with
  **navis 1.3.1 and no flybrains**.
- No conda, pyenv or uv environments exist.
- `~/flybrain-data/` **is** populated (the H5 bridging registrations, including
  `JRC2018U_JRC2018F.h5` and `JRCVNC2018U_JRCVNC2018F.h5`).
- elastix **is** present at `~/opt/elastix` — needs `PATH` **and** `DYLD_LIBRARY_PATH`
  (`ISSUES.md` CODE-2).

The environment recorded in `TRANSFORMS.md` and `ISSUES.md` — **navis 1.12.0 (or 1.9.1) /
flybrains 0.6.3 / elastix 5.3.1** — must be rebuilt before any test here runs. Extra deps
that were needed last time: `shapely` (for `trimesh.slice_plane`) and a `certifi` workaround
(the stock CA store on this python build is empty).

---

## 7. Suggested order of work

1. Rebuild the venv; assert `navis.transforms.registry.find_bridging_path` returns the
   3-hop BANC paths from `ISSUES.md`. Anything else means flybrains moved (`TRANSFORMS.md` §1).
2. Add §5.3, the landmark residual, as a CI test. Minutes of work, catches the worst errors.
3. Fetch one BANC `region_outlines` mesh and assert its bbox against
   `flybrains/meshes/BANC_brain.ply` — settles the 8×8×45 vs 4×4×45 question (§2) before it
   silently halves everything.
4. Build the §4 ROI-overlap harness; calibrate on FlyWire→JRC2018U; then run BANC (as a
   round-trip check) and maleCNS (as an accuracy check).
5. Build §5.1, the per-synapse confusion matrix, as the standing acceptance test — this is
   the one that should gate image regeneration.
6. Only then consider §5.2 and §5.4.

Replace the bbox acceptance check in the image pipeline with §4/§5.1 once calibrated —
`ISSUES.md` IMG-3 already flags the bbox test as inadequate.
