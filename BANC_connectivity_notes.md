# BANC Connectivity Import Notes

## Current Status

The BANC connectivity importer has been set up but requires the `banc` Python package which has some dependency conflicts with the current environment (specifically with numpy versions for vfb-connect).

## BANC Data Access

BANC (Brain And Nerve Cord) uses its own CAVE infrastructure, separate from the public FlyWire dataset. Access requires:

1. **Installation of banc package**: `pip install banc`
   - Repository: https://github.com/jasper-tms/the-BANC-fly-connectome
   
2. **CAVE Credentials**: 
   - Get API key from: https://global.daf-apis.com/auth/api/v1/create_token
   - Save using: `banc.save_cave_credentials("YOUR_API_KEY")`
   - Or manually create `~/.cloudvolume/secrets/cave-secret.json`:
     ```json
     {
       "token": "YOUR_API_KEY",
       "brain_and_nerve_cord": "YOUR_API_KEY"
     }
     ```

3. **VFB Dataset Info**:
   - Dataset name in VFB: `Bates2025`
   - Site short_form: `BANC626`
   - Materialization version: 626
   - Anatomical scope: adult brain|adult ventral nerve cord (whole CNS)

## Implementation Approach

### Option 1: Use banc package (Recommended if available)

The `banc` package provides a `connectivity` module with functions like:
- `get_synapses(seg_ids, direction='outputs', threshold=3)`
- Returns DataFrame with synapse information

```python
import banc
from banc import connectivity

# Get CAVE client
client = banc.get_caveclient()

# Query synapses
synapses = connectivity.get_synapses(
    seg_ids=root_ids,
    direction='outputs',  # or 'inputs'
    threshold=3,
    client=client
)

# Convert to connectivity matrix
# Group by pre/post to get edge weights
conn_df = synapses.groupby(['pre_pt_root_id', 'post_pt_root_id']).size().reset_index(name='weight')
conn_df.rename(columns={'pre_pt_root_id': 'source', 'post_pt_root_id': 'target'}, inplace=True)
```

### Option 2: Use fafbseg with correct parameters

If BANC data is accessible via fafbseg (currently getting connection errors):

```python
from fafbseg import flywire

conn_df = flywire.get_connectivity(
    root_ids,
    upstream=False,
    downstream=True,
    materialization=626,
    dataset='banc',  # BANC dataset identifier
    filtered=True,
    clean=True,
    proofread_only=True
)
```

## Files Created

- `/src/VFB_connectomics_import/BANC_import.py`: Simple neuron curation TSV generator
- `/src/VFB_connectomics_import/script_runner_BANC.py`: Connectivity script (uses get_adjacencies_flywire with BANC parameters)
- `/src/VFB_connectomics_import/connectomics_import.py`: Added dataset/materialization parameters to get_adjacencies_flywire()

## Current Script Usage (once dependencies resolved)

```bash
# Generate connectivity ROBOT template
python src/VFB_connectomics_import/script_runner_BANC.py \
  --dataset Bates2025 \
  --output BANC_n2n.tsv

# Convert to OWL using ROBOT
robot template \
  -input-iri http://purl.obolibrary.org/obo/ro.owl \
  --add-prefix "n2o: http://neo2owl/custom/" \
  --add-prefix "VFB: http://virtualflybrain.org/reports/VFB_" \
  --template BANC_n2n.tsv \
  annotate --ontology-iri http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl \
  convert -f ofn --output connectome_BANC_n2n.owl
```

## Next Steps

1. Resolve numpy version conflict (vfb-connect requires numpy<2.0.0, banc installed numpy 2.2.6)
2. Test BANC connectivity access once credentials and environment are properly configured
3. Verify data can be retrieved for the 80,832 neurons in Bates2025 dataset
4. Run end-to-end workflow to generate OWL file
