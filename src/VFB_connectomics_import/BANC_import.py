#aim here is to import BANC skeleton and meshes for anat_ curation, following the same pattern as MANC_import.py
from fafbseg import flywire
import pandas as pd
import navis
import flybrains

def generate_curation_tsv(root_ids):
    '''generate anat_ tsv for loading BANC neurons via the VFB curation interface

    Parameters
    ----------
    root_ids  :  list
                 List of BANC root IDs
    '''
    
    df = pd.DataFrame({"filename": list(root_ids)})
    curation_tsv = pd.DataFrame()
    curation_tsv['filename'] = df['filename']
    curation_tsv['is_a'] = 'adult neuron'
    curation_tsv['part_of'] = 'adult brain|adult ventral nerve cord'  # BANC covers whole CNS
    curation_tsv['label'] = 'BANC:' + df['filename'].astype(str)
    curation_tsv['comment'] = 'BANC connectome neuron'
    curation_tsv['dbxrefs'] = 'flywire_banc:' + df['filename'].astype(str)
    return curation_tsv


##### Example usage (similar to MANC_import.py):

# testset = [123456789012345678, 234567890123456789]  # Example BANC root IDs
# curation_tsv = generate_curation_tsv(testset)

##### scraps for testing skels/meshes, code runs on jenkins (similar to MANC/FlyWire loaders).

# Load flybrains transforms
# flybrains.download_jrc_transforms()
# flybrains.register_transforms()

### Getting skeletons
# neuronlist = flywire.get_skeletons(testset, dataset='banc')
# navis.plot3d([neuronlist]).show()

### Bridging skeletons (update source/target when BANC transform is known)
# transformed_neuron_df = navis.xform_brain(neuronlist, source='BANCraw', target='JRC2018U')
# navis.plot3d([transformed_neuron_df, flybrains.JRC2018U]).show()

### Getting meshes
# mesh_neuron_list = flywire.get_mesh_neuron(testset, dataset='banc', lod=2)
# navis.plot3d([mesh_neuron_list]).show()

### Bridging meshes (update source/target/via when BANC transform is known)
# transformed_mesh_neuron_df = navis.xform_brain(mesh_neuron_list, source='BANCraw', target='JRC2018U', via='JRCFIB2022M')
# navis.plot3d([transformed_mesh_neuron_df, flybrains.JRC2018U]).show()
