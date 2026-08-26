# Connectome version updates: identity and curation rules

**Read this before touching anything that migrates a connectome from one release to the
next** — human or agent.

## Scope

The *mechanics* of a VFB dataset update are documented elsewhere and are not repeated here:

- Canonical: <https://virtualflybrain.org/docs/data/em/versioning/>
- Dashboard-facing summary: [`dashboard/README.md`](../dashboard/README.md) §"How VFB dataset
  updates work" — new `Site` + `DataSet` per release, `Connectome` label and
  `is_data_source` flag move to the current release, `term_replaced_by` links old to new,
  connectivity and images replaced for non-deprecated neurons.

This file holds what those do **not** say: how neuron *identity* behaves across releases,
and what that means for curation and images. It exists because this reasoning is not
written down anywhere, is not deducible from the code, and has been re-derived from
scratch more than once — each time via a chain of expensive queries against published
mapping tables.

Numbers below are measurements, with dates. Re-measure rather than trust them if the
release has moved on; the *rules* are what should be stable.

---

## Rule 1 — a root ID is a version, not an identity

Chunked-graph segmentations (BANC, FlyWire, FANC) identify a neuron by the root of its
agglomeration. **Any merge or split mints a new root ID.** Therefore:

- same root ID across two materialisations ⇒ the segment was **not edited**
- different root ID ⇒ the segment **was edited** ⇒ its morphology differs

Measured 2026-08-19, BANC v626 → v888, from the project's own published mapping
(`compiled_data/banc_888/banc_888_meta.feather`, 188,508 rows):

| | count |
|---|---|
| root ID identical | 115,737 (61%) |
| root ID changed | 72,771 (39%) |

**Do not generalise a subset's stability to the dataset.** VFB's imported BANC subset is
far more stable than BANC as a whole — 65,053 of 80,832 (80.5%) unchanged, because VFB
took the proofread neurons and those are the ones that stopped moving. Widening the import
should be expected to bring churn nearer 39%.

## Rule 2 — never inherit curation across a changed root ID; re-derive it

A changed root ID means the cell was edited, so **its identity claim has to be
re-established, not assumed.** A split may reveal that one cell was really two; a merge
that two were one. Inheriting the old type would propagate a claim the proofreading has
just contradicted.

So the pipeline is, every release:

```
source annotations (e.g. BANC codex_annotations / *_meta cell_type)
        ->  VFB / FBbt term mapping
        ->  typing on the new individual
```

**The previous version's type is irrelevant by design.** A root-ID mapping table is *not*
a curation-transfer mechanism — it tells you two records are related, not that anything
transfers.

Observed 2026-08-19: both BANC MBON03s are correctly typed `mushroom body output neuron 3`
(`FBbt_00100232`) in v626 *and* v888, as separate individuals with no link between them —
re-derived from BANC's published `cell_type`, not carried.

| | v626 | v888 |
|---|---|---|
| side=right | `VFB_001060ke` / root `720575941486707853` | `VFB_00107o96` / root `720575941477965105` |
| side=left | `VFB_00105q6x` / root `720575941532752357` | `VFB_00107ay0` / root `720575941394436502` |

## Rule 3 — images follow the root ID, not the mapping

- root ID **unchanged** → same morphology → existing image is reusable *in principle*
- root ID **changed** → edited → morphology differs → image **must be rebuilt**

A mapping table therefore saves **no** image work. Do not plan a migration on the
assumption that mapped neurons can have their images copied or re-pointed.

Separately, an unchanged root ID still does not guarantee the image is *current*. Root-ID
stability covers the agglomeration only. These move independently:

- **registration version** — BANC's are `registrations/{brain,vnc}_240721/`, i.e. dated
  2024-07-21. Same morphology, re-registered, lands elsewhere.
- **skeletonisation** — the published L2 skeletons are refreshed periodically; the BANC
  bucket carries `_prel2refresh_bak/`, `.pre_l2patch_20260629`, `.pre_shoreup_20260812`.
- **our own pipeline** — cut logic, `flybrains` version, transform routing.

## Rule 4 — `term_replaced_by` is identifier continuity, and only for 1:1

It is not a curation channel. Its only job is that a cited or bookmarked VFB ID redirects
instead of dead-ending.

It is **only well defined when succession is one-to-one.** A split (1→many) or merge
(many→1) has no single successor, and asserting one would contradict the proofreading.
So this is a per-case judgement, **never a bulk join** over a mapping table.

Observed 2026-08-19: of BANC's 15,779 v626-only neurons, 15,778 carry a bare `deprecated`
property — but none carry `term_replaced_by`, and there is no relationship of any kind to
their successors. Retirement ran; linking did not.

## Rule 5 — store a version-stable anchor, not just the root ID

Root IDs cannot anchor identity across releases (Rule 1). What can:

- **supervoxel ID** — belongs to the base segmentation, survives proofreading
- **nucleus ID / representative point** — spatial, survives re-agglomeration

The operation is *resolve anchor → root ID at target timestamp*
(`CAVEclient.get_roots`, `fafbseg.flywire.supervoxels_to_roots(..., timestamp=...)` as in
`src/vfb_connectomics_import/flywire_import.py`).

Caveat: supervoxels are stable only while the **base** segmentation is. If it is
regenerated, supervoxel IDs move too and you fall back to spatial matching. Check the
source's segmentation notes (for BANC, `documentation/banc_v888_segmentation.md` in the
bucket) before committing to supervoxels as the anchor.

**Current state (2026-08-19): there is no version-stable anchor for any connectome in the
VFB KB.** No supervoxel `Site` exists at all. `BANC_import.py` writes a `flywire_banc:`
dbxref to a Site that does not exist (the real ones are `BANC626` / `BANC888`), and
`flywire_import.py` writes `flywire_supervoxel:` but the KB holds only `flywire783` and
`neuronbridge`. Adding such a Site is the single change that would make cross-release
identity tractable.

---

## Traps

- **Do not use VFB's own accessions to decide whether the segmentation changed.** If the
  new release's accessions were derived from the old ones, the comparison is circular.
  Use the source's published mapping. (This error was made and corrected on 2026-08-19:
  comparing VFB Site accessions suggested 0% churn; the published table said 39%.)
- **Do not read a version from a file's mtime.** BANC's n2n OWL was dated 17-Aug-2026 but
  built from v626 data — two months newer than the newest input in this repo. See
  [`README.md`](README.md#artifact-naming-include-the-source-version-todo).
- **KB and PDB do not spell `short_form`s identically** (KB `male-cns_v1_0`, PDB
  `male_cns_v1_0`), and PDB lags the KB by a release. Curation state is a KB question;
  "is it live" is a PDB question.
- **Do not match Templates by `label`.** Two nodes can share one (`VFB_00200000`
  "JRC2018UnisexVNC" vs `VFBc_00200000` "JRC2018UnisexVNC_c"). Match `short_form`.

## Checks worth running before a migration

1. **True churn** — join the source's published cross-version mapping and count
   identical vs changed root IDs. Never infer it from VFB's own records.
2. **Which release the images are from** — sample neurons that exist *only* in the new
   release and HEAD their `volume.swc`. All 404 means no images have been built for it.
3. **Retirement and linking** — count old-release neurons with `deprecated` set, and
   separately those with `term_replaced_by`. These are different numbers and both matter.
4. **Typing coverage on the new release** — instances per FBbt class for the new DataSet.
   Re-derived typing should be complete without any reference to the old release.
