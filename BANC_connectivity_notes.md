# BANC Connectivity Import

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

- `/src/VFB_connectomics_import/BANC_import.py`: Neuron curation TSV generator
- `/src/VFB_connectomics_import/script_runner_BANC.py`: Main connectivity import script
- `/src/VFB_connectomics_import/connectomics_import.py`: Core connectivity processing

## Usage

```bash
# Generate connectivity ROBOT template
python src/VFB_connectomics_import/script_runner_BANC.py \
  --dataset Bates2025 \
  --output BANC_n2n.tsv \
  --threshold 0

# Apply additional threshold (e.g., only include connections with >10 synapses)
# Note: The source file already filters to ≥3 synapses
python src/VFB_connectomics_import/script_runner_BANC.py \
  --dataset Bates2025 \
  --output BANC_n2n_thresh10.tsv \
  --threshold 10

# Optional: specify custom connectivity file path
python src/VFB_connectomics_import/script_runner_BANC.py \
  --dataset Bates2025 \
  --output BANC_n2n.tsv \
  --connectivity-file /path/to/custom/connectivity.parquet
```

### Convert to OWL using ROBOT

```bash
robot template \
  --input-iri http://purl.obolibrary.org/obo/ro.owl \
  --add-prefix "n2o: http://neo2owl/custom/" \
  --add-prefix "VFB: http://virtualflybrain.org/reports/VFB_" \
  --template BANC_n2n.tsv \
  annotate --ontology-iri http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl \
  convert -f ofn --output connectome_BANC_n2n.owl
```

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
