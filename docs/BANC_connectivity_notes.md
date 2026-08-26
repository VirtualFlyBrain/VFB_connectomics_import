# BANC Connectivity Import

> **⚠️ This document describes v626, which is superseded.** As of 2026-08-18 the KB
> has BANC **v888** as the data source (`DataSet Bates2026`, `Site BANC888`,
> `is_data_source` set); v626 is `Bates2025` / `BANC626` with the flag unset. v888
> has 146,511 neurons vs v626's 80,832 — 65,053 carried over, 81,458 new, 15,779
> dropped. The GCS bucket has a `neuron_connectivity/v888/` folder. The OWL on the
> data server is still v626-derived and needs rebuilding; PDB is still on v626.
>
> When rebuilding, **put the version in the output filename** (see
> [README.md](README.md#artifact-naming-include-the-source-version-todo)) — the
> current name records nothing about its source version and it cannot be recovered
> from the file afterwards.

## Overview

The BANC (Brain And Nerve Cord) connectivity importer successfully retrieves connectivity data from publicly available files on Google Cloud Storage, avoiding the need for CAVE API authentication.

## Data Access

BANC connectivity data is publicly available on Google Cloud Storage:
- **Bucket**: `gs://lee-lab_brain-and-nerve-cord-fly-connectome`
- **Connectivity files**: `gs://lee-lab_brain-and-nerve-cord-fly-connectome/neuron_connectivity/v626/`
- **Primary file**: `synapses_v1_human_readable_sizethresh3_connectioncounts_countthresh3.parquet`

This parquet file contains:
- `pre_root_id`: Presynaptic neuron root ID
- `post_root_id`: Postsynaptic neuron root ID
- `num_synapses`: Number of synapses (weight)
- **Total edges**: ~8.67 million connections
- **Size**: ~61 MB
- **Pre-applied filters**: 
  - Synapse size threshold: 3 (sizethresh3)
  - Connection count threshold: 3 (countthresh3)
  - Only includes connections with ≥3 synapses

## VFB Dataset Info

- **Dataset name in VFB**: `Bates2025`
- **Site short_form**: `BANC626`
- **Materialization version**: 626
- **Anatomical scope**: adult brain|adult ventral nerve cord (whole CNS)
- **Neurons in VFB**: 80,832
- **Connectivity edges within VFB dataset**: 1,898,631

## Implementation

The BANC importer uses a simple, efficient approach:

1. **Query VFB** for all neurons in the Bates2025 dataset
2. **Download** the connectivity parquet file from GCS (if not already cached)
3. **Filter** to include only connections between VFB neurons
4. **Apply threshold** (optional, default=0)
5. **Generate** ROBOT template TSV

### Files Created

- `/src/vfb_connectomics_import/BANC_import.py`: Neuron curation TSV generator
- `/-m vfb_connectomics_import.connectivity.cli.banc`: Main connectivity import script
- `/src/vfb_connectomics_import/connectomics_import.py`: Core connectivity processing

## Usage

```bash
# Generate connectivity ROBOT template
python -m vfb_connectomics_import.connectivity.cli.banc \
  --dataset Bates2025 \
  --output BANC_n2n.tsv \
  --threshold 0

# Apply additional threshold (e.g., only include connections with >10 synapses)
# Note: The source file already filters to ≥3 synapses
python -m vfb_connectomics_import.connectivity.cli.banc \
  --dataset Bates2025 \
  --output BANC_n2n_thresh10.tsv \
  --threshold 10

# Optional: specify custom connectivity file path
python -m vfb_connectomics_import.connectivity.cli.banc \
  --dataset Bates2025 \
  --output BANC_n2n.tsv \
  --connectivity-file /path/to/custom/connectivity.parquet
```

### Convert to OWL using ROBOT

```bash
# Download ROBOT if not already installed
curl -L https://github.com/ontodev/robot/releases/download/v1.9.6/robot.jar -o /tmp/robot.jar

# Generate OWL file from ROBOT template.
# NOTE the version token (BANC888) in BOTH the output filename and the version IRI,
# and the dc:source annotation — without these the artifact's provenance is
# unrecoverable. Substitute the Site short_form you actually built from.
java -jar /tmp/robot.jar template \
  --input-iri http://purl.obolibrary.org/obo/ro.owl \
  --add-prefix "n2o: http://neo2owl/custom/" \
  --add-prefix "VFB: http://virtualflybrain.org/reports/VFB_" \
  --template BANC_n2n.tsv \
  annotate --ontology-iri http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl \
           --version-iri  http://virtualflybrain.org/data/VFB/OWL/BANC888_import.owl \
           --annotation dc:source "BANC v888 (Site BANC888, gs://lee-lab_brain-and-nerve-cord-fly-connectome/neuron_connectivity/v888/)" \
  convert -f ofn --output src/vfb_connectomics_import/OWL/connectome_BANC888_n2n.owl

# Compress the OWL file (reduces from ~430 MB to ~11 MB)
gzip -9 src/vfb_connectomics_import/OWL/connectome_BANC_n2n.owl

# Verify compressed file integrity
gunzip -t src/vfb_connectomics_import/OWL/connectome_BANC_n2n.owl.gz
```

**Output files:**
- `src/vfb_connectomics_import/OWL/connectome_BANC_n2n.owl`: 430 MB (uncompressed OWL)
- `src/vfb_connectomics_import/OWL/connectome_BANC_n2n.owl.gz`: 11 MB (compressed, 97.4% reduction)

## Performance

The script processes BANC connectivity efficiently:
- **Loading parquet file**: < 1 second
- **Filtering 8.67M edges**: ~2-3 seconds
- **Generating ROBOT template**: ~10-15 seconds
- **Total runtime**: ~15-20 seconds

## Advantages of This Approach

1. **No authentication required** - Uses public GCS data
2. **Fast** - Local parquet file processing
3. **Reliable** - Not dependent on CAVE API availability
4. **Reproducible** - Fixed materialization version (626)
5. **Simple** - Minimal dependencies (just pandas + gsutil)

## Notes

- The connectivity file is automatically downloaded on first run if not found
- Requires `gsutil` to be installed (`gcloud` SDK)
- **Important**: The parquet file has pre-applied thresholds:
  - Synapse size threshold: 3
  - Connection count threshold: 3
  - All connections in the file have ≥3 synapses
- The script's `--threshold` parameter applies an *additional* filter on top of this
- Root ID 0 represents background/unlabeled segments and should be filtered out in VFB queries
