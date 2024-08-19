#aim here is to test importing OL skeleton and meshes for anat_ curation. Potentially expand to add annotations.
from neuprint import Client, fetch_custom_neurons
import pandas as pd
import datetime
c = Client('neuprint.janelia.org', dataset='optic-lobe:v1.0', token='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6ImFkbTcxQGNhbS5hYy51ayIsImxldmVsIjoibm9hdXRoIiwiaW1hZ2UtdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUFjSFR0ZnhLRU5vLTRTQ0JBNWx2T194S3FLQjlTU09YRkVwU0RuVU1QLWFKcXpqPXM5Ni1jP3N6PTUwP3N6PTUwIiwiZXhwIjoxODczNTczMDI4fQ.Wp2D7KmnVlg01S8k2U7mMv5-L0vMr3VzJVIHZef7TE0')

class neuprint_curation:
    '''functions for basic neuprint curation, generating anat_ tsvs for neuprint curation and getting skels + meshes'''

    def generate_curation_tsv(query):
        '''generate anat_ tsv for loading neuprint neurons via the VFB curation interface

        Parameters
        ----------
        query  :        string
                        Cypher query for neuprint, must return neuron node(s)
        '''

        neurons_df, roi_counts_df = fetch_custom_neurons(query)
        neurons_df=neurons_df[~neurons_df.type.str.contains('unclear|TBD|\(')] #drop neurons with type containing 'unclear' as unmappable
        if neurons_df.instance.isna().any():
            print('warning - missing instances')
        neurons_df=neurons_df[~neurons_df.instance.isna()]
        curation_tsv = pd.DataFrame()
        #these don't have vfb ids provided so loading with automatic assignment
        curation_tsv['filename'] = neurons_df[['bodyId']]
        curation_tsv['is_a'] = 'adult neuron'
        curation_tsv['part_of'] = 'male organism'
        curation_tsv['label'] = neurons_df['instance'] + ' (JRC_OpticLobe:' + neurons_df['bodyId'].astype(str) + ')'
        curation_tsv['comment'] = 'status-' + neurons_df['status'] + ', status label-' + neurons_df['statusLabel'] + ', Optic Lobe classification: type-' + neurons_df['type']
        curation_tsv['dbxrefs'] = 'neuprint_JRC_OpticLobe_v1_0:' + neurons_df['bodyId'].astype('str')
        return curation_tsv

# To enable faster queries, the subset of “Segment” nodes that are relevant for typical analyses are additionally labeled as “Neuron” nodes. To qualify as a Neuron, a Segment must have at least 100 synaptic connections, a defined “type,” “instance,” or known soma location. In most data analyses presented here, we primarily work with named Neurons, i.e. “Neuron” nodes with defined “type” and “instance” properties. We ignore non-Neuron Segments and further exclude Neurons whose types are suffixed with “_unclear”.
query = 'MATCH (n :Neuron) WHERE n.type is not null RETURN n'
# query for testing
#query = 'MATCH (n :Neuron) WHERE n.type is not null RETURN n LIMIT 10'
curation_tsv=neuprint_curation.generate_curation_tsv(query)


#TODO - generalise this
# ##large records need to be split up into 20k chunks (hopefully this can be removed later)
# #testset
# curation_tsv[0:100].to_csv('anat_Nern2024_' + datetime.date.today().strftime('%Y%m%d')[2:8] + '_testset2.tsv', sep='\t', index=False)
# curation_tsv[100:20100].to_csv('anat_Nern2024_a' + datetime.date.today().strftime('%Y%m%d')[2:8] + '.tsv', sep='\t', index=False)
# curation_tsv[20100:40100].to_csv('anat_Nern2024_b' + datetime.date.today().strftime('%Y%m%d')[2:8] + '.tsv', sep='\t', index=False)
# curation_tsv[40100:len(curation_tsv)].to_csv('anat_Nern2024_c' + datetime.date.today().strftime('%Y%m%d')[2:8] + '.tsv', sep='\t', index=False)
#
# #chunk the rest
# chunk_size=20000
# tsvs = []
# for i in range((len(curation_tsv)-100)//chunk_size):
#     tsvs[i]=curation_tsv[i*chunk_size:(i+1)*chunk_size]
#
#     curation_tsv[i*chunk_size:(i+1)*chunk_size].to_csv('anat_Nern2024_' + datetime.date.today().strftime('%Y%m%d')[2:8] + '_'+ i + '.tsv', sep='\t', index=False)
#
# for s in samples:
#     sample_data = expression_data[expression_data['id']==s]
#     sample_data = sample_data.assign(hide_in_terminfo = 'true')
#     sample_id = s.replace("NCBI_SAM:", "")
#     dataset_group = sample_grouping_dict[s]
#     chunk_counter = -(-len(sample_data) // row_limit) # number of chunks to split file
#     while chunk_counter > 0:
#         start = (chunk_counter-1) * row_limit
#         end = chunk_counter * row_limit
#         if end > len(sample_data):
#             end = len(sample_data)
#         sample_data_chunk = sample_data[start:end]
#         sample_data_chunk.to_csv("expression_data/dataset_%s_%s-sample_%s_chunk_%s.tsv" %(dataset, dataset_group, sample_id, chunk_counter), sep='\t', index=None)
#         chunk_counter = chunk_counter - 1
#
# curation_tsv[100:].to_csv('anat_Nern2024_' + datetime.date.today().strftime('%Y%m%d')[2:8] + '_testset.tsv', sep='\t', index=False)
# curation_tsv[0:100].to_csv('anat_Nern2024_' + datetime.date.today().strftime('%Y%m%d')[2:8] + '_testset.tsv', sep='\t', index=False)

#use this if chunking not needed (may want a test set though)
#curation_tsv.to_csv('anat_Nern2024_' + datetime.date.today().strftime('%Y%m%d')[2:8] + '.tsv', sep='\t', index=False)



##### scraps for testing skels/meshes, code runs on jenkins (https://jenkins.virtualflybrain.org/view/ImageCreation/job/Load%20neurons%20from%20neuprint/).
### load flybrains transforms
import flybrains
import navis
import navis.interfaces.neuprint as neu

# get transforms for flybrains
flybrains.download_jefferislab_transforms()
flybrains.download_jrc_transforms()
flybrains.download_jrc_vnc_transforms()
flybrains.download_vfb_transforms()
flybrains.register_transforms()

### Getting skeletons
skellist=neu.fetch_skeletons(list(curation_tsv.filename))
navis.plot3d([flybrains.JRCFIB2022Mraw, skellist]).show(renderer='browser')

### Bridging skeletons
transformed_skel_df = navis.xform_brain(skellist, source='JRCFIB2022Mraw', target='JRC2018U')
navis.plot3d([transformed_skel_df[0], flybrains.JRC2018U]).show(renderer='browser')

### Getting meshes
mesh_neuron_list = neu.fetch_mesh_neuron(list(curation_tsv.filename), missing_mesh='warn', lod=None)
navis.plot3d([flybrains.JRCFIB2022Mraw, mesh_neuron_list[0]]).show(renderer='browser')

### bridgeing meshes
transformed_mesh_neuron_df = navis.xform_brain(mesh_neuron_list[0], source='JRCFIB2022Mraw', target='JRC2018U')
navis.plot3d([transformed_mesh_neuron_df, flybrains.JRC2018U]).show(renderer='browser')

### Testing skelmesh loader output
swc=navis.read_swc('/Users/adm/Downloads/volume(1).swc')
mesh=navis.read_mesh('/Users/adm/Downloads/volume_man(1).obj')
nrrd=navis.read_nrrd('/Users/adm/Downloads/volume.nrrd')

navis.plot3d([mesh, swc, nrrd, flybrains.JRC2018U]).show(renderer='browser')

mesh2=navis.read_mesh('/Users/adm/Downloads/volume_man(2).obj')
swc2=navis.read_swc('/Users/adm/Downloads/volume(2).swc')
navis.plot3d([mesh2, swc2, flybrains.JRC2018U]).show(renderer='browser')
mesh2