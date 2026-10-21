# vfb_connectomics_import
A project to produce RDF/OWL representations of connectomics data for import to the VFB integration layer triple store.

## 📊 Import status dashboard

**[Open the live dashboard →](https://virtualflybrain.github.io/VFB_connectomics_import/)**

A colour-coded, always-current matrix of every connectome import — stage, version,
and whether it's live in the release. Rebuilt automatically (nightly + on push).
How it works and how to extend it: [`dashboard/`](dashboard/).

## 🪰 EM neuron images

Writes `volume.swc`, `volume_man.obj` and `volume.nrrd` onto the VFB templates for a whole
connectome. `--connectome` selects the dataset; everything that differs between them —
the bucket, the cut planes, the transform chain, the DataSet/Site and the LOD ladder — is
declared in [`images/connectomes.py`](src/vfb_connectomics_import/images/connectomes.py),
not in the job. Adding a dataset is a change there.

| | neurons | status |
|---|---|---|
| `banc` — BANC v888 (`Bates2026`) | 146,511 | live, Jenkins `load-banc-neurons` |
| `malecns` — male-CNS v1.0 (`Berg2025a`) | 166,701 | ready to run — see [`docs/MALECNS_REBUILD.md`](docs/MALECNS_REBUILD.md) |

```bash
export IMAGE_FIELD_DIR=/nas/.../malecns_transform_fields   # baked transforms, one dir per connectome
export KB_USER=... KB_PASSWORD=...                         # KB only; neither v888 nor v1.0 is in pdb
pip install -e ".[images]"
vfb-em-images --connectome malecns --region both --ledger run.jsonl
```

**Two things you must set**: `$IMAGE_FIELD_DIR` (the baked fields — preflight prints which
of three sources it resolved and fails in seconds if wrong) and KB credentials. BANC also
needs `$FLYBRAINS_DATA` for its JRC2018F→JRC2018U H5 tail hop, fetched automatically if
absent; maleCNS is baked end to end and reads no H5 at all. Nothing per-neuron touches an
authenticated service — all geometry is anonymous HTTPS from a public bucket.
(`$BANC_FIELD_DIR`, `$BANC_SWC_DIR` and `vfb-banc-images` all still work, so existing BANC
jobs are unaffected.)

**It replaces in place, one neuron at a time.** Almost every neuron already has an image.
The complete new set is built to `volume.partial.*` and swapped in with `os.replace`, so a
served file goes straight from old to new and is never briefly absent. On any failure the
partials are discarded and the old image keeps serving. The job can therefore be stopped at
any moment without leaving the site broken — which is why its speed does not much matter.

**`--ledger` is required**, not optional: file existence cannot indicate progress when
almost every neuron already has files. It is the only record of where a run got to, and
`error` is never recorded as terminal, so failures retry themselves next build. Give each
connectome, region and shard its own.

**It deletes images too.** When a rebuild finds no depictable material in a region *and* a
usable source was available, the image there is spurious and is removed — that is the only
thing that cleans up BANC's ~4,660 wrong-template images (IMG-3), and maleCNS's ~161,000
uncut duplicates (IMG-2). With **no** usable source nothing is deleted, because absent input
is not evidence: upstream mesh coverage is only 94.4%/68.8%, and a transient fetch failure
raises rather than being read as "nothing here". Beyond the three products it writes it also
deletes `volume.obj` and `volume.dps.pkl` — the latter because NBLAST only refreshes its
combined cache when a neuron's dotprops have changed, so a stale one would freeze the old
shape there. `volume.wlz` and thumbnails are left for the jobs that own them.

**Mesh size.** Where the publisher ships an LOD ladder we pick one of their rungs and serve
their geometry unaltered; where they do not (BANC, LOD 0 only) we decimate. Both the wire
budget and the density ceiling are enforced on the face count that actually arrives, never
on the prediction. See [`docs/MESH_SIZING.md`](docs/MESH_SIZING.md). Note `--mesh-budget-mb`
is now the hard **cap** (default 20 MB); the old "leave it alone" sense is `--mesh-skip-mb`.

`--region both` does both templates in one pass. `--limit N` takes a test batch and logs
exactly which neurons; `--shard i --of n` splits an array job; `--archive DIR` keeps the
pre-replacement images so `vfb-banc-compare` can render old-vs-new 3D pages, and is a
verified undo. `tools/rehearsal/run.sh` rehearses a destructive run against a local mirror
of the live images, so deletion and archiving execute for real with nothing at risk — run it
before any dataset's first real build. Tests: `pytest tests/` (54, no network needed).

Detail lives in [`docs/MALECNS_REBUILD.md`](docs/MALECNS_REBUILD.md) (the live piece of
work), [`docs/TRANSFORMS.md`](docs/TRANSFORMS.md) (transform paths, staging, the
`use_https` trap), [`docs/MESH_SIZING.md`](docs/MESH_SIZING.md) (which rung, or decimate)
and [`docs/ISSUES.md`](docs/ISSUES.md) (IMG-1 mesh size, IMG-2 uncut maleCNS, IMG-3 spurious
images, IMG-4 the missing-image gap).

## 🧭 Transforms

**[`TRANSFORMS.md`](docs/TRANSFORMS.md)** — how BANC and maleCNS reach the JRC2018 templates: the
exact paths, why the BANC legs are pre-baked and the JRC legs are not, the baked-field format
and its accuracy, and the deployment shape. Read it before changing any `xform_brain` call —
`via=`/`avoid=` in particular behave in non-obvious ways.

## 🐛 Known issues / work queue

**[`ISSUES.md`](docs/ISSUES.md)** — cross-cutting defects in the loaded data and the import code,
with evidence and fix direction. The dashboard tracks *stage progress* ("has n2n been
built?"); this tracks *correctness* ("is what we built right?"). Currently topped by
**IMG-2**: maleCNS writes the whole neuron into *both* templates uncut, so ~161,000 of its
333,402 image folders hold a file that should not exist — and by **IMG-1**, served OBJ
meshes reaching 626 MB for a single neuron, across every EM connectome. The fix for both is
built and verified; see [`docs/MALECNS_REBUILD.md`](docs/MALECNS_REBUILD.md).

## 🔻 Before changing how meshes are written

Read **[`MESH_SIZING.md`](docs/MESH_SIZING.md)** first — it settles *whether* to reprocess a
mesh at all, and the answer is usually no: where a publisher ships an LOD ladder we pick one
of their rungs and serve their geometry unaltered, because the objective is responsibility
rather than quality. It is implemented in
[`images/sizing.py`](src/vfb_connectomics_import/images/sizing.py) and has been run.

Then **[`DECIMATION.md`](docs/DECIMATION.md)**, which settles *how* to decimate when nothing
the publisher ships fits — today that is BANC alone, which publishes LOD 0 only. The finding
it records is not obvious and
was got wrong once in the opposite direction: hemibrain APL and maleCNS APL are the same cell
with the **same surface area** (62,244 vs 60,334 µm²) and a **5.4× difference in triangle
count**, so the entire filesize gap is redundant tessellation and hemibrain's 37 faces/µm² is
a measured "displays fine" threshold rather than a guess. It also records the six approaches
that were measured and rejected, the one metric that still disagrees, and the rasteriser trap
that manufactures damage which is not there.

## ⚠️ Before migrating a connectome to a new release

Read **[`VERSIONING.md`](docs/VERSIONING.md)**. It holds the neuron-identity and curation rules
that the [canonical VFB versioning docs](https://virtualflybrain.org/docs/data/em/versioning/)
do not cover — why a root ID is a version rather than an identity, why curation is
re-derived each release instead of carried across a mapping, when an existing image can and
cannot be reused, and what `term_replaced_by` is and is not for. None of it is deducible
from the code, and getting it wrong silently produces wrong data.

## 🧭 Before touching a template transform

Read **[`TRANSFORMS.md`](docs/TRANSFORMS.md)**. Two things in it are not deducible from the code
and cost real time to re-derive: navis's `via=`/`avoid=` kwargs **abandon the weighted path
search entirely**, so the `via=` calls in this repo currently resolve to 16- and 19-hop
routes through the wrong templates; and the way to make image generation fast is not to
shorten the hop chain but to keep the deformation fields in RAM, or — for anything with an
elastix or CMTK hop, i.e. all of BANC — to bake the whole chain onto a single displacement
field. It also records the measured support bands of the two BANC registrations, which is
what makes the neck-connective cut safe.

## ✅ Before trusting a transformed image

Read **[`VALIDATION.md`](docs/VALIDATION.md)**. It is a *plan, not a result* — nothing in it has
been run yet. It records where the reference neuropil ROIs live (VFB already serves 46
painted domains on JRC2018Unisex and 21 on JRC2018UnisexVNC, no auth), and the trap that
makes the obvious test misleading: **BANC's own neuropil ROIs are the ITO/COURT/MANC atlases
registered *into* BANC through the very transform under test**, so round-tripping them
measures forward∘inverse consistency, not accuracy. maleCNS and MANC ROIs are EM-derived and
so are not affected. It also ranks four non-circular alternatives.

Note what this is *not*: `images/verify_baked.py` compares a baked field against the exact
multi-hop chain it was built from, and both maleCNS fields pass it comfortably (brain mean
16.5 nm, VNC 74.8 nm, zero domain disagreement). That proves the bake faithful to the
registration — it cannot tell you the registration is right, which is what VALIDATION.md is
for and what remains unrun. The environment blocker it records is resolved; see
[`docs/TRANSFORMS.md`](docs/TRANSFORMS.md) for the working env.

## Functional specification

The VFB KB has records for neurons imported from sources that have connectomic data: currently neuprint + multiple CATMAID databases.  These records include the IDs for these neurons used in the sources they are imported from (e.g. bodyIDs from neuprint)  The aim of library is to provide simple, extensible code for importing connectomics assertions about these neurons into the VFB integration layer triple store, via the generation of RDF/OWL. 

Schema for neuron:neuron connectomics:

(i)-[synapsed_to: { weight: n }]->(j)

* In future we may add:
   * more complex details (e.g. weight by ROI)
   * methods for adding neuron-region connectivity 

The generated OWL must have an IRI = resolveable URL pointing to location of stored OWL file. Loading will then be a simple matter of adding this URL to the triple store config. 

### Artifact versions: recorded in the file, not the name

Every connectivity OWL records the source release it was built from **in its header**:
a version IRI `http://virtualflybrain.org/data/VFB/OWL/<Site>_import.owl` and a
`dc:source` annotation, where `<Site>` is the VFB `Site` short_form — the canonical
version token in both the KB and PDB (`BANC888`, `male-cns_v1_0`, `flywire783`, …).
Filenames stay stable (`connectome_BANC_n2n.owl`, `connectome_malecns_n2n.owl`), so
nothing downstream has to follow a rename.

How it is applied:

- **Each build takes one argument, `--site`.** The source release is derived from that
  Site's `link_base` (`connectivity/provenance.py`): the neuprint dataset
  (`dataset=male-cns:v1.0`), the CAVE / bucket materialization (`data_version=888`),
  or, for a live CATMAID server, the build date. Nothing about the release is
  hard-coded or passed separately, so the edges and the recorded release cannot
  disagree.
- **The build writes the OWL itself** (`connectivity/owl_writer.py`), with the stamp
  in its header, and **validates the complete file** before accepting it
  (`connectivity/validate.py`): a full streaming check of every line, an OWLAPI parse
  plus SPARQL shape checks on a sample, and, with `--previous`, a diff against the
  last artifact. CI (`.github/workflows/tests.yml`) checks the writer against ROBOT
  (`robot diff` must report identical ontologies) and that the checks reject
  malformed files. The ROBOT-template route remains only as `--output X.tsv`, for the
  release pipeline's CATMAID step.
- **The import dashboard reads it back** (`owl_header` probe): it range-requests the
  first 64 kB of the uploaded file and compares the stamped Site with the target.

The command for each connectome, its edge source, and the diff of the 2026-10-21 rebuild
against the live files are in [`docs/CONNECTIVITY_BUILDS.md`](docs/CONNECTIVITY_BUILDS.md).

Files built before this have no stamp; the dashboard shows them as orange, "release not
recorded". Their release can only be recovered by hand — e.g. the old BANC n2n OWL took
range-requesting part of the 451 MB file and fingerprinting its neurons against KB
dataset membership — and `last-modified` is no guide (that file was dated two months
after its newest input).

## Tech spec 

* Python code generates the connectivity OWL directly (`connectivity/owl_writer.py`), checked against ROBOT's output in CI and validated in full on every build (`connectivity/validate.py`); see `docs/CONNECTIVITY_BUILDS.md`.
* The relevant neurons and their identifiers will be found using VFB_connect to query VFB to generate simple lookups for converting between VFB IDs and external IDs
* Connectomic reports from external sites may be generated as Pandas tables, allowing efficient column based methods to be used for ID conversion.


## Architecture

Suggested: 
 - Simple wrapper class for connections
 - runner script with argparse for specific template generation jobs




