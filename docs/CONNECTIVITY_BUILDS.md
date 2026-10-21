# Neuron-to-neuron connectivity builds

How each `connectome_*.owl` (and the CATMAID imports) is built, and what the
rebuild of 2026-10-21 showed when diffed against the files then on the VFB data
server. Every build takes one release input, `--site` (the VFB Site short_form),
derives the source release from it, and writes `<template>.provenance`, which
`data_owl/chunked_n2n_build.sh` stamps into the OWL header (README, "Artifact
versions"). All use the same cut: connections of **>= 2** synapses (`--threshold 1`).

## Commands

```bash
B=src/vfb_connectomics_import/connectivity/data_owl/chunked_n2n_build.sh
OWL=http://virtualflybrain.org/data/VFB/OWL

python -m vfb_connectomics_import.connectivity.cli.<cli> --site <Site> [options] --output X.tsv
$B X.tsv <served name> $OWL/<ontology IRI name> 2000000
gzip -9k <served name>          # committed as data_owl/<served name>.gz
```

| Served file | `cli` | `--site` | Edge source | Build time |
|---|---|---|---|---|
| `connectome_BANC_n2n.owl` | `banc` | `BANC888` | BANC bucket `v888/…_connectioncountsperneuropil.parquet`, summed per pair (default) | ~12 min |
| `connectome_flywire_fafb.owl` | `flywire` | `flywire783` | Zenodo 10676866 `proofread_connections_783.feather`, summed per pair (default; `--source cave` for CAVE) | ~7 min |
| `connectome_malecns_n2n.owl` | `neuprint` | `male-cns_v1_0` | `--connectivity-file` flat connectome `connectome-weights-male-cns-v1.0-minconf-0.5.feather` (`gs://flyem-male-cns/v1.0/connectome-data/flat-connectome/`) | ~15 min |
| `connectome_jrc_ol.owl` | `neuprint` | `neuprint_JRC_OpticLobe_v1_0_1` | `--connectivity-file` flat connectome `connectome-weights-2023-10-31-27a052-minconf-0.5-ol.feather` (`gs://flyem-optic-lobe/v1.0/optic-lobe-v1.0.1-flat-connectome/`) | ~4 min |
| `connectome_manc.owl` | `neuprint` | `neuprint_JRC_Manc_1_2_1` | neuprint `ConnectsTo` weights, queried per batch of source bodies (default) | ~4 min |
| `connectome_hemibrain.owl` | `neuprint` | `neuprint_JRC_Hemibrain_1point2point1` | neuprint `ConnectsTo` weights (default) | ~3 min |
| `L1EM_CATMAID_import.owl` | `catmaid` | `catmaid_l1em` | VFB CATMAID server (live; built by the release pipeline) | < 1 min |
| `FAFB_CATMAID_import.owl` | `catmaid` | `catmaid_fafb` | VFB CATMAID server (live; built by the release pipeline) | < 1 min |

Times are from a laptop run, including the chunked OWL build. The neuprint
`ConnectsTo` query returns each pair's total once, instead of `fetch_adjacencies`'
one row per pair per primary ROI; for male-CNS and optic lobe the published flat
connectome avoids neuprint altogether.

## Rebuild of 2026-10-21 against the live files

Edges compared as (source, target, weight) between VFB individuals.

| Connectome | Live edges | Rebuilt edges | Result |
|---|---|---|---|
| male-CNS v1.0 | 15,283,255 | 15,283,255 | **identical** — every edge and weight |
| optic lobe v1.0.1 | 3,958,978 | 3,958,978 | **identical** |
| MANC v1.2.1 | 3,105,275 | 3,105,275 | **identical** |
| FlyWire 783 | 7,595,968 | 7,595,967 | identical except 7 live edges whose target IRI was the empty `…/reports/VFB_` (an unmapped neuron in the old build); the rebuild has those edges to a real neuron. CAVE route and Zenodo file agree exactly. |
| L1EM CATMAID | 72,199 | 72,199 | **identical** |
| FAFB CATMAID | 35,551 | 35,551 | **identical** |
| BANC | 1,898,631 (v626) | 5,479,385 (v888) | release change, as intended: shared edges have identical weights; every live-only edge involves a neuron dropped in v888; new edges are new v888 neurons plus the >= 2 cut (v626 was >= 3). Rebuilt with `--site` it matches the v888 build of 2026-10-12 exactly. |
| hemibrain | 3,392,973 | 1,727,995 | the live file (`neuprint_JRC_Hemibrain_1point1_connectomics.owl`, "v1.1, static since 2022" per the release pipeline) kept **1-synapse** connections: 1,679,253 of its 1,679,992 live-only edges have weight 1. Of the 1,712,981 shared edges 95.9% have equal weights and 4.0% are higher in v1.2.1 (median +26%); 739 live-only edges of weight >= 2. Consistent with v1.1 connectivity on v1.2.1's (bodyId-stable) individuals. |

So the rebuilds change nothing except where the live file was wrong (FlyWire's 7
edges), out of date (BANC v626, hemibrain v1.1), or cut differently (hemibrain at
>= 1).
