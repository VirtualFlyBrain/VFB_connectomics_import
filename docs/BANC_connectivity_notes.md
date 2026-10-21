# BANC Connectivity Import

Current release: **v888** — KB `DataSet Bates2026`, `Site BANC888` (`is_data_source`),
146,511 neurons. v626 (`Bates2025` / `BANC626`) is superseded: 65,053 neurons carried
over, 81,458 new, 15,779 dropped. See [VERSIONING.md](VERSIONING.md) before migrating a
release.

## Data source

Public, no authentication: `gs://lee-lab_brain-and-nerve-cord-fly-connectome`, read over
HTTPS as `https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/...`.

| File (under `neuron_connectivity/v888/`) | What it is |
|---|---|
| `synapses_v1_human_readable_sizethresh3_connectioncountsperneuropil.parquet` | **Used.** v1 synapse set (synapse size > 3), counted per (pre, post, neuropil), **no connection-count threshold**. ~1.1 GB, ~177M rows. Columns `pre_root_id`, `post_root_id`, `neuropil`, `num_synapses`. |
| `synapses_v1_human_readable_sizethresh3_connectioncounts_countthresh3.parquet` | The same synapses summed per (pre, post) and cut at **>= 3**. v626 was built from this. |

Edges are the per-neuropil counts **summed per (pre, post) pair** and kept where the
weight is **>= 2** (`--threshold 1`, i.e. `weight > 1`) — the same cut as the neuprint,
FlyWire and CATMAID imports. Verified 2026-10-12: cut at >= 3 instead, the pair sums
reproduce the `countthresh3` file exactly (all 3,373,590 pairs between VFB's v888
neurons, identical weights), so the two files are the same data and only the cut differs.

Root ID `0` is background / unsegmented; it never matches a VFB accession, so it drops
out when edges are restricted to VFB neurons.

### v888 numbers (2026-10-12)

The build of 2026-10-12 took the 146,511 KB accessions under `Bates2026` / `BANC888`,
which include 5 neurons flagged deprecated (pdb leaves deprecated neurons out of
connectivity results anyway); the comparison rows exclude those 5. The CLI now selects
neurons by Site alone (`--dataset` can still narrow it).

| | edges | synapses |
|---|---|---|
| **>= 2, as built (146,511 accessions)** | **5,479,385** | **31,826,732** |
| all connected pairs (146,506 non-deprecated) | 11,532,949 | 37,880,265 |
| >= 2 (146,506 non-deprecated) | 5,479,365 | 31,826,681 |
| >= 3, BANC's `countthresh3` file (146,506 non-deprecated) | 3,373,590 | 27,615,131 |

For comparison, the v626 build had 1,898,631 edges (80,832 neurons, >= 3).

## Build

```bash
python -m vfb_connectomics_import.connectivity.cli.banc --site BANC888 \
    --output connectome_BANC_n2n.owl \
    --previous src/vfb_connectomics_import/connectivity/data_owl/connectome_BANC_n2n.owl.gz
gzip -9k connectome_BANC_n2n.owl
```

`--site` (default `BANC888`) is the only release input: the BANC release (888) and the
bucket folder are derived from the Site's `link_base`, and the neurons are the Site's
cross-referenced individuals. `--threshold 1` (>= 2) is the default;
`--connectivity-file` takes a local copy or another URL. The parquet is streamed one row
group at a time and cut down to VFB-to-VFB rows before summing, so memory stays modest.

The OWL is written directly, with the version IRI `.../BANC888_import.owl` and a
`dc:source` in its header, and the ontology IRI `BANC_import.owl` (what the loader has
always seen). The build stops if any edge end fails to map to a VFB id via the Site, then
validates the complete file and, with `--previous`, reports what changed against the last
artifact (docs/CONNECTIVITY_BUILDS.md). No ROBOT or large Java heap is needed.

### 3. Publish

Replace `connectome_BANC_n2n.owl` on the VFB data server with the new build (same name).
The dashboard's n2n cell (`owl_header`) reads the release from the file's header, so it
turns green by itself once the v888 file is there; until then it shows the current
unstamped v626 file as orange, "release not recorded".

## Notes

- Weights are `n2o:weight` on `RO:0002120` (synapsed to), with `n2o:` =
  `http://neo2owl/custom/`, as in every other `connectome_*` file; pdb loads it as the
  `synapsed_to` edge's `weight`.
- Autapses (pre = post) are kept, as in v626.
- Region counts and whole-neuron synapse totals for BANC are built in
  [vfb-region-connectivity](https://github.com/VirtualFlyBrain/vfb-region-connectivity)
  from the same per-neuropil file, so edges, region counts and totals all describe the
  same synapses.
