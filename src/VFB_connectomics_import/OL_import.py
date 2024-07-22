#aim here is to test importing OL skeleton and meshes for anat_ curation. Potentially expand to add annotations.
from neuprint import Client, fetch_custom_neurons, fetch_custom
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
        curation_tsv = pd.DataFrame()
        #these don't have vfb ids provided so loading with automatic assignment
        curation_tsv['filename'] = neurons_df[['bodyId']]
        curation_tsv['is_a'] = 'adult neuron'
        curation_tsv['part_of'] = 'male organism'
        curation_tsv['label'] = neurons_df['instance'] + ' (JRC_Optic_Lobe:' + neurons_df['bodyId'].astype(str) + ')'
        curation_tsv['comment'] = 'status-' + neurons_df['status'] + ', status label-' + neurons_df['statusLabel'] + ', Optic Lobe classification: type-' + neurons_df['type']
        curation_tsv['dbxrefs'] = 'neuprint_JRC_OpticLobe_v1_0:' + neurons_df['bodyId'].astype('str')
        return curation_tsv

# To enable faster queries, the subset of “Segment” nodes that are relevant for typical analyses are additionally labeled as “Neuron” nodes. To qualify as a Neuron, a Segment must have at least 100 synaptic connections, a defined “type,” “instance,” or known soma location. In most data analyses presented here, we primarily work with named Neurons, i.e. “Neuron” nodes with defined “type” and “instance” properties. We ignore non-Neuron Segments and further exclude Neurons whose types are suffixed with “_unclear”.
query = 'MATCH (n :Neuron) WHERE n.type is not null RETURN n'
# query for testing
#query = 'MATCH (n :Neuron) WHERE n.type is not null RETURN n LIMIT 100'
curation_tsv=neuprint_curation.generate_curation_tsv(query)

curation_tsv.to_csv('anat_Nern2024_' + datetime.date.today().strftime('%Y%m%d')[2:8] + '.tsv', sep='\t', index=False)

##### scraps for testing skels/meshes, code runs on jenkins (https://jenkins.virtualflybrain.org/view/ImageCreation/job/Load%20neurons%20from%20neuprint/).

# load flybrains transforms
# 
# #flybrains.download_jefferislab_transforms()
# flybrains.download_jrc_transforms()
# flybrains.download_jrc_vnc_transforms()
# ### flybrains.download_vfb_transforms()
# flybrains.register_transforms()
#
# #curation_tsv.to_csv('a.tsv', sep='\t', index= False)
#
# ### Getting skeletons
#
# neuronlist=(neu.fetch_skeletons(curation_tsv.filename[0:10]))
#
# navis.plot3d([flybrains.MANCraw, neuronlist]).show()
#
# ### Bridging skeletons
#
# transformed_neuron_df = navis.xform_brain(neuronlist, source='MANCraw', target='JRCVNC2018U')
#
# navis.plot3d([transformed_neuron_df, flybrains.JRCVNC2018U]).show()
#
# ### Getting meshes
#
# mesh_neuron_list = neu.fetch_mesh_neuron(list(curation_tsv.filename[0:10]), missing_mesh='warn')
# navis.plot3d([flybrains.MANCraw, mesh_neuron_list[0:10]]).show()
#
# ### bridgeing meshes
#
# transformed_mesh_neuron_df = navis.xform_brain(mesh_neuron_list, source='MANCraw', target='JRCVNC2018U', via='JRCVNC2018M')
# navis.plot3d([transformed_mesh_neuron_df[0:20], flybrains.JRCVNC2018U]).show()
#
#
# test2=neu.fetch_skeletons(23801)
# navis.plot3d(test2).show()

