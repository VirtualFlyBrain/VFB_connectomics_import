# VFB_connectomics_import
A project to produce RDF/OWL representations of connectomics data for import to the VFB integration layer triple store.

## 📊 Import status dashboard

**[Open the live dashboard →](https://virtualflybrain.github.io/VFB_connectomics_import/)**

<<<<<<< Updated upstream
<!-- CONNECTOME-DASHBOARD:START -->
_Auto-generated 2026-07-28 08:41 UTC — see the [live dashboard](https://virtualflybrain.github.io/VFB_connectomics_import/) or [dashboard/STATUS.md](dashboard/STATUS.md)._

Legend: 🟩 done · 🟧 needs update · 🟥 in progress / not live · ⬜ not started · 🔳 unknown  ·  🔵 live in release · ⚪ done but not live yet

| Connectome | Ver | Neurons loaded | Skeletons / Meshes | Connectivity n→n | Connectivity n→r | Neuron types in ontology | Owner |
|---|---|---|---|---|---|---|---|
| male-CNS | 1.0 | ⬜ | 🔳 | 🟩⚪ | ⬜ | ⬜ | @adm |
| MANC | 1.2.1 | 🟩🔵 | 🔳 | 🟩🔵 | ⬜ | ⬜ | — |
| Hemibrain | 1.2.1 | 🟩🔵 | 🔳 | 🟩🔵 | 🟩🔵 | ⬜ | — |
| Optic Lobe | 1.0.1 | 🟩🔵 | 🔳 | 🟩🔵 | ⬜ | ⬜ | @adm |
| FlyWire (FAFB) | 783 | 🟩🔵 | 🔳 | 🟩🔵 | ⬜ | ⬜ | @adm |
| BANC | 626 | 🟩🔵 | 🔳 | 🟩🔵 | ⬜ | ⬜ | @adm |
| FAFB (CATMAID) | — | 🟩🔵 | ⬜ | 🟩🔵 | ⬜ | ⬜ | @adm |
| L1EM (CATMAID) | — | 🟩🔵 | ⬜ | 🟩🔵 | ⬜ | ⬜ | @adm |
<!-- CONNECTOME-DASHBOARD:END -->
=======
A colour-coded, always-current matrix of every connectome import — stage, version,
and whether it's live in the release. Rebuilt automatically (nightly + on push).
How it works and how to extend it: [`dashboard/`](dashboard/).
>>>>>>> Stashed changes

## Functional specification

The VFB KB has records for neurons imported from sources that have connectomic data: currently neuprint + multiple CATMAID databases.  These records include the IDs for these neurons used in the sources they are imported from (e.g. bodyIDs from neuprint)  The aim of library is to provide simple, extensible code for importing connectomics assertions about these neurons into the VFB integration layer triple store, via the generation of RDF/OWL. 

Schema for neuron:neuron connectomics:

(i)-[synapsed_to: { weight: n }]->(j)

* In future we may add:
   * more complex details (e.g. weight by ROI)
   * methods for adding neuron-region connectivity 

The generated OWL must have an IRI = resolveable URL pointing to location of stored OWL file. Loading will then be a simple matter of adding this URL to the triple store config. 

## Tech spec 

* Python code will generate Robot templates which can then be used to generate OWL for loading into the triple store. 
* An additional MakeFile will drive generation of OWL using ROBOT (including setting OWL file IRI)
* The relevant neurons and their identifiers will be found using VFB_connect to query VFB to generate simple lookups for converting between VFB IDs and external IDs
* Connectomic reports from external sites may be generated as Pandas tables, allowing efficient column based methods to be used for ID conversion.


## Architecture

Suggested: 
 - Simple wrapper class for connections
 - runner script with argparse for specific template generation jobs




