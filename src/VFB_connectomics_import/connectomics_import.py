import neuprint
from neuprint import Client
from neuprint import fetch_adjacencies
import pandas as pd
from vfb_connect.cross_server_tools import VfbConnect

class ConnectomicsImport:
    def __init__(self, neuprint_endpoint=None, neuprint_dataset=None, neuprint_token=None):
        self.vc=VfbConnect()
        if neuprint_endpoint and neuprint_dataset and neuprint_token:
            self.neuprint_client=neuprint.Client(neuprint_endpoint, dataset=neuprint_dataset, token=neuprint_token)
        else: self.neuprint_client=None

    def get_accessions_from_vfb(self, dataset):
        accessions = list(map(int, self.vc.neo_query_wrapper.xref_2_vfb_id(db=dataset).keys()))
        return accessions

    def get_adjacencies_neuprint(self, accessions, testmode=False):# add testmode, generalise?
        # fetch neuron-neuron connectivity for only the filtered neurons within PRIMARY rois only and collapse rois to total
        neuron_df, conn_df = fetch_adjacencies(sources=accessions, targets=accessions)
        conn_df = conn_df.groupby(['bodyId_pre', 'bodyId_post'], as_index=False)['weight'].sum()
        return conn_df#add to stack? in wrapper

    def generate_template(self, dataset, conn_df):
        robot_template_df=pd.DataFrame({'ID': ['ID'], 'TYPE': ['Type'], 'FACT': ["I 'synapsed to'"], 'Weight': ['>AT n2o:weight^^xsd:integer']})
        vfb_ids = self.vc.neo_query_wrapper.xref_2_vfb_id(db=dataset).items()
        vfb_ids = {k: v[0]['vfb_id'] for (k, v) in vfb_ids}
        conn_df = conn_df.applymap(str)
        conn_df['bodyId_pre']=conn_df['bodyId_pre'].map(vfb_ids)
        conn_df['bodyId_post']=conn_df['bodyId_post'].map(vfb_ids)
        conn_df.rename(columns={'bodyId_pre': 'ID', 'bodyId_post': 'FACT', 'weight': 'Weight'}, inplace=True)
        conn_df['ID']=conn_df['ID'].str.replace('_', ':')
        conn_df['FACT']=conn_df['FACT'].str.replace('_', ':')
        conn_df['TYPE']='owl:NamedIndividual'
        robot_template_df=robot_template_df.append(conn_df)
        return robot_template_df



#TODO pull from vfb connect accessions > then to neuprint or catmaid depending, match catmaid to neuprint (neuprint or catmaid arg)/ CATMIAD runner, neuprint runner.
#TODO args for both should stay the same