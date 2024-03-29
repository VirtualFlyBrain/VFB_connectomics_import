import neuprint
from neuprint import Client
from neuprint import fetch_adjacencies
import pandas as pd
from vfb_connect.cross_server_tools import VfbConnect
import pymaid

class ConnectomicsImport:
    def __init__(self, neuprint_endpoint=None, neuprint_dataset=None, neuprint_token=None, catmaid_endpoint=None):
        if neuprint_endpoint and neuprint_dataset and neuprint_token:
            self.neuprint_client=neuprint.Client(neuprint_endpoint, dataset=neuprint_dataset, token=neuprint_token)
        elif catmaid_endpoint:
            self.rm=pymaid.CatmaidInstance(catmaid_endpoint, '', '', '')
            #no self?
        else: self.neuprint_client=None
        self.vc = VfbConnect(neo_endpoint="http://kb.virtualflybrain.org")

    def get_accessions_from_vfb(self, dataset):
        accessions = list(self.vc.neo_query_wrapper.xref_2_vfb_id(db=dataset).keys())
        return accessions #call function

    # def get_minimal_metadata_neuprint(self):
    # import yaml
    #     q = "MATCH (n:Neuron) WHERE exists(n.type) return n.bodyId, n.instance, n.statusLabel, n.cropped"
    #     bodyIds1_1 = np1_1_client.fetch_custom(q).astype(str)

    # bodyIds1_1 = bodyIds1_1.rename(columns={'n.bodyId': 'filename'})
    # bodyIds1_1['label'] = bodyIds1_1['n.instance'] + ' - ' + bodyIds1_1['filename']
    # bodyIds1_1['is_a'] = 'neuron'
    # bodyIds1_1['part_of'] = 'female organism|adult brain'
    # bodyIds1_1['dbxrefs'] = 'neuprint_JRC_Hemibrain_1point1:' + bodyIds1_1['filename']
    # bodyIds1_1['comment'] = 'tracing status-' + bodyIds1_1['n.statusLabel'] + ', ' + 'cropped-' + bodyIds1_1['n.cropped']
    # bodyIds1_1 = bodyIds1_1.drop(['n.instance', 'n.statusLabel', 'n.cropped'], axis=1)
    # bodyIds1_1.to_csv('anat_' + 'Xu2020NeuronsV1point1' + '_' + date.today().strftime('%Y%m%d')[2:8] + '.tsv', sep='\t',index=False)

    ##create yaml data and write file
    # yaml data
    # yaml_data = dict(
    #     DataSet='Xu2020NeuronsV1point1',
    #     Curator='adm71',
    #     Template='JRC_FlyEM_Hemibrain_c',
    #     Imaging_type='SB-SEM')
    # write yaml file
    # with open('anat_' + 'Xu2020NeuronsV1point1' + '_' + date.today().strftime('%Y%m%d')[2:8] + '.yaml', 'w') as outfile:
    #     yaml.dump(yaml_data, outfile, default_flow_style=False)

    def get_adjacencies_neuprint(self, accessions, threshold=1, testmode=False):# add testmode?
        #fetch neuron-neuron connectivity for only between the accessions and only within PRIMARY rois and collapse rois to total
        neuron_df, conn_df = fetch_adjacencies(sources=accessions, targets=accessions)
        conn_df = conn_df.groupby(['bodyId_pre', 'bodyId_post'], as_index=False)['weight'].sum()
        conn_df.rename(columns={'bodyId_pre': 'source', 'bodyId_post': 'target'}, inplace=True)
        #filter by synapse count threshold (using total neuron-neuron connectivity in whole brain
        conn_df = conn_df[conn_df.weight > threshold]
        return conn_df

    def get_adjacencies_CATMAID(self, accessions, threshold=0):
        conn_df = pymaid.get_edges(accessions)
        conn_df = conn_df[conn_df.weight > threshold]
        return conn_df

    def get_adjacencies_flywire(self, accessions, threshold=0):
        conn_df = flywire.fetch_connectivity(accessions) #can this be limited during grabbing rather than after?
        conn_df = conn_df[conn_df.weight > threshold]
        return conn_df

#    def get_regions_CATMAID(self, accessions): #TODO add threshold, volumes?
#       volume=pymaid.get_volume('FAFB volume name') [use pymaid.get_volume() to get list]
#       adj=pymaid.adjacency_matrix(accessions, volume_filter=volume)
#       adj['output_syn']=adj.sum(axis=0)
#       adj.loc['input_syn'] = adj.sum(axis=1)
#       output_sum = pd.DataFrame(adj['output_syn'])
#       output_sum['ID'] = output_sum.index
#       input_sum = pd.DataFrame(adj.loc['input_syn'])
#       input_sum['ID'] = input_sum.index
#       adj_sum[(adj.T != 0).any()] #not quite working though, some 0 getting through
#       in_out_region = input_sum.merge(output_sum, how='outer', on='')
#
#       TODO need to convert per region adjacency matrices to template rows somehow. Is this the best way to do this, I'm pretty sure could work but slow?

    def generate_n_n_template(self, dataset, conn_df):
        robot_template_df=pd.DataFrame({'ID': ['ID'], 'TYPE': ['TYPE'], 'FACT': ["I 'synapsed to'"], 'Weight': ['>AT n2o:weight^^xsd:integer']})
        vfb_ids = self.vc.neo_query_wrapper.xref_2_vfb_id(db=dataset).items()
        vfb_ids = {k: v[0]['vfb_id'] for (k, v) in vfb_ids}
        conn_df = conn_df.applymap(str)
        conn_df['source']=conn_df['source'].map(vfb_ids)
        conn_df['target']=conn_df['target'].map(vfb_ids)
        conn_df.rename(columns={'source': 'ID', 'target': 'FACT', 'weight': 'Weight'}, inplace=True)
        conn_df['ID']=conn_df['ID'].str.replace('_', ':')
        conn_df['FACT']=conn_df['FACT'].str.replace('_', ':')
        conn_df['TYPE']='owl:NamedIndividual'
        robot_template_df = pd.concat([robot_template_df, conn_df], ignore_index=True)
        return robot_template_df
