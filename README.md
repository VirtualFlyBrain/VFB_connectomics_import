# vfb_connectomics_import
A project to produce RDF/OWL representations of connectomics data for import to the VFB integration layer triple store.

## 📊 Import status dashboard

**[Open the live dashboard →](https://virtualflybrain.github.io/vfb_connectomics_import/)**

A colour-coded, always-current matrix of every connectome import — stage, version,
and whether it's live in the release. Rebuilt automatically (nightly + on push).
How it works and how to extend it: [`dashboard/`](dashboard/).

## 🧭 Transforms

**[`TRANSFORMS.md`](TRANSFORMS.md)** — how BANC and maleCNS reach the JRC2018 templates: the
exact paths, why the BANC legs are pre-baked and the JRC legs are not, the baked-field format
and its accuracy, and the deployment shape. Read it before changing any `xform_brain` call —
`via=`/`avoid=` in particular behave in non-obvious ways.

## 🐛 Known issues / work queue

**[`ISSUES.md`](ISSUES.md)** — cross-cutting defects in the loaded data and the import code,
with evidence and fix direction. The dashboard tracks *stage progress* ("has n2n been
built?"); this tracks *correctness* ("is what we built right?"). Currently topped by
**IMG-1**: served OBJ meshes reach 626 MB for a single neuron and take minutes to load,
across every EM connectome.

## 🔻 Before changing how meshes are written

Read **[`DECIMATION.md`](DECIMATION.md)**. It is the working spec for IMG-1 — *measured and
settled, implemented for BANC only, never yet run*. The finding it records is not obvious and
was got wrong once in the opposite direction: hemibrain APL and maleCNS APL are the same cell
with the **same surface area** (62,244 vs 60,334 µm²) and a **5.4× difference in triangle
count**, so the entire filesize gap is redundant tessellation and hemibrain's 37 faces/µm² is
a measured "displays fine" threshold rather than a guess. It also records the six approaches
that were measured and rejected, the one metric that still disagrees, and the rasteriser trap
that manufactures damage which is not there.

## ⚠️ Before migrating a connectome to a new release

Read **[`VERSIONING.md`](VERSIONING.md)**. It holds the neuron-identity and curation rules
that the [canonical VFB versioning docs](https://virtualflybrain.org/docs/data/em/versioning/)
do not cover — why a root ID is a version rather than an identity, why curation is
re-derived each release instead of carried across a mapping, when an existing image can and
cannot be reused, and what `term_replaced_by` is and is not for. None of it is deducible
from the code, and getting it wrong silently produces wrong data.

## 🧭 Before touching a template transform

Read **[`TRANSFORMS.md`](TRANSFORMS.md)**. Two things in it are not deducible from the code
and cost real time to re-derive: navis's `via=`/`avoid=` kwargs **abandon the weighted path
search entirely**, so the `via=` calls in this repo currently resolve to 16- and 19-hop
routes through the wrong templates; and the way to make image generation fast is not to
shorten the hop chain but to keep the deformation fields in RAM, or — for anything with an
elastix or CMTK hop, i.e. all of BANC — to bake the whole chain onto a single displacement
field. It also records the measured support bands of the two BANC registrations, which is
what makes the neck-connective cut safe.

## ✅ Before trusting a transformed image

Read **[`VALIDATION.md`](VALIDATION.md)**. It is a *plan, not a result* — nothing in it has
been run yet. It records where the reference neuropil ROIs live (VFB already serves 46
painted domains on JRC2018Unisex and 21 on JRC2018UnisexVNC, no auth), and the trap that
makes the obvious test misleading: **BANC's own neuropil ROIs are the ITO/COURT/MANC atlases
registered *into* BANC through the very transform under test**, so round-tripping them
measures forward∘inverse consistency, not accuracy. maleCNS and MANC ROIs are EM-derived and
so are not affected. It also ranks four non-circular alternatives, and lists the environment
blocker (no python on the dev box currently has navis + flybrains).

## Functional specification

The VFB KB has records for neurons imported from sources that have connectomic data: currently neuprint + multiple CATMAID databases.  These records include the IDs for these neurons used in the sources they are imported from (e.g. bodyIDs from neuprint)  The aim of library is to provide simple, extensible code for importing connectomics assertions about these neurons into the VFB integration layer triple store, via the generation of RDF/OWL. 

Schema for neuron:neuron connectomics:

(i)-[synapsed_to: { weight: n }]->(j)

* In future we may add:
   * more complex details (e.g. weight by ROI)
   * methods for adding neuron-region connectivity 

The generated OWL must have an IRI = resolveable URL pointing to location of stored OWL file. Loading will then be a simple matter of adding this URL to the triple store config. 

### Artifact naming: include the source version (TODO)

Generated artifacts **must carry the source version in the filename** — use the VFB
`Site` `short_form`, which is the canonical version token in both the KB and PDB:

    connectome_BANC888_n2n.owl        not  connectome_BANC_n2n.owl
    connectome_male_cns_v1_0_n2n.owl  not  connectome_malecns_n2n.owl

Current artifacts do not, and the version is unrecoverable afterwards: the OWL
contains only `VFB:`/`FBbt:` IDs and `n2o:weight`, so nothing in the file records
which materialization it came from, and `last-modified` is misleading (the BANC n2n
OWL is dated two months after the newest TSV in this repo but was built from v626).
Recovering it required range-requesting part of the 451 MB file and fingerprinting
its neuron population against KB dataset membership.

Also stamp the version into the ontology itself via `robot annotate`
(`--version-iri`, plus a `dc:source` annotation naming the Site and source file), so
it survives a rename.

Apply both when each connectome is next rebuilt. Code that locates these files should
pattern-match on the version token rather than hard-code a name — see
[`dashboard/README.md`](dashboard/README.md) for how this currently forces a
`built_version` workaround in the status probes.

## Tech spec 

* Python code will generate Robot templates which can then be used to generate OWL for loading into the triple store. 
* An additional MakeFile will drive generation of OWL using ROBOT (including setting OWL file IRI)
* The relevant neurons and their identifiers will be found using VFB_connect to query VFB to generate simple lookups for converting between VFB IDs and external IDs
* Connectomic reports from external sites may be generated as Pandas tables, allowing efficient column based methods to be used for ID conversion.


## Architecture

Suggested: 
 - Simple wrapper class for connections
 - runner script with argparse for specific template generation jobs




