#aim here is to test importing MANC skeleton and meshes for anat_ curation. Potentially expand to add annotations.
from neuprint import Client, fetch_custom_neurons
import pandas as pd
import navis
import navis.interfaces.neuprint as neu
c = Client('neuprint.janelia.org', dataset='manc:v1.0', token='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6ImFkbTcxQGNhbS5hYy51ayIsImxldmVsIjoibm9hdXRoIiwiaW1hZ2UtdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUFjSFR0ZnhLRU5vLTRTQ0JBNWx2T194S3FLQjlTU09YRkVwU0RuVU1QLWFKcXpqPXM5Ni1jP3N6PTUwP3N6PTUwIiwiZXhwIjoxODczNTczMDI4fQ.Wp2D7KmnVlg01S8k2U7mMv5-L0vMr3VzJVIHZef7TE0')
import flybrains

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
        idneurons = neurons_df.dropna(subset='vfbId')
        curation_tsv = pd.DataFrame()
        curation_tsv['anat_id'] = idneurons[['vfbId']]
        curation_tsv['filename'] = idneurons[['bodyId']]
        curation_tsv['is_a'] = 'adult neuron'
        curation_tsv['part_of'] = 'male organism|adult ventral nerve cord'
        curation_tsv['label'] = idneurons['instance'] + ' (MANC:' + idneurons['bodyId'].astype(str) + ')'
        curation_tsv['comment'] = ''
        curation_tsv['comment'][idneurons['cropped'].isna()] = 'tracing status-' + idneurons['statusLabel']
        curation_tsv['comment'][~idneurons['cropped'].isna()] = 'tracing status-' + idneurons['statusLabel'] + ', cropped-' + idneurons['cropped'].astype(str)
        idneurons.fillna('None', inplace=True)
        curation_tsv['comment'] = curation_tsv['comment'] + ', MANC classification: class-' + idneurons['class'].astype(str) + ', subclass-' + idneurons['subclass'].astype(str) + ', systematic type-' + idneurons['systematicType'].astype(str)
        curation_tsv['dbxrefs'] = 'neuprint_JRC_Manc:' + idneurons['bodyId'].astype(str)
        return curation_tsv

query = 'MATCH (n :Neuron) RETURN n LIMIT 100'
curation_tsv=neuprint_curation.generate_curation_tsv(query)



##### scraps for testing skels/meshes, code runs on jenkins.

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

