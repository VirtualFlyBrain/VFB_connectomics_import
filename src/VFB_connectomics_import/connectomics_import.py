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
        elif catmaid_endpint:
            self.rm=pymaid.CatmaidInstance(catmaid_endpoint, '', '', '')
            #no self?
        else: self.neuprint_client=None
        self.vc = VfbConnect()

    def get_accessions_from_vfb(self, dataset):
        accessions = list(map(int, self.vc.neo_query_wrapper.xref_2_vfb_id(db=dataset).keys()))
        return accessions #call function

    def get_adjacencies_neuprint(self, accessions, threshold=1, testmode=False):# add testmode?
        #fetch neuron-neuron connectivity for only between the accessions and only within PRIMARY rois and collapse rois to total
        neuron_df, conn_df = fetch_adjacencies(sources=accessions, targets=accessions)
        conn_df = conn_df.groupby(['bodyId_pre', 'bodyId_post'], as_index=False)['weight'].sum()
        conn_df.rename(columns={'bodyId_pre': 'source', 'bodyId_post': 'target'}, inplace=True)
        #filter by synapse count threshold (using total neuron-neuron connectivity in whole brain
        conn_df = conn_df[conn_df.weight > threshold]
        return conn_df

    def get_adjacencies_CATMAID(self, accessions, threshold=1):
        conn_df = pymaid.get_edges(accessions)
        return conn_df

    def generate_template(self, dataset, conn_df):
        robot_template_df=pd.DataFrame({'ID': ['ID'], 'TYPE': ['Type'], 'FACT': ["I 'synapsed to'"], 'Weight': ['>AT n2o:weight^^xsd:integer']})
        vfb_ids = self.vc.neo_query_wrapper.xref_2_vfb_id(db=dataset).items()
        vfb_ids = {k: v[0]['vfb_id'] for (k, v) in vfb_ids}
        conn_df = conn_df.applymap(str)
        conn_df['source']=conn_df['source'].map(vfb_ids)
        conn_df['target']=conn_df['target'].map(vfb_ids)
        conn_df.rename(columns={'source': 'ID', 'target': 'FACT', 'weight': 'Weight'}, inplace=True)
        conn_df['ID']=conn_df['ID'].str.replace('_', ':')
        conn_df['FACT']=conn_df['FACT'].str.replace('_', ':')
        conn_df['TYPE']='owl:NamedIndividual'
        robot_template_df=robot_template_df.append(conn_df)
        return robot_template_df


#TODO args for both should stay the same