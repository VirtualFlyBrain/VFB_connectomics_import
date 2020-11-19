from dotenv import load_dotenv
import os
import neuprint
from neuprint import Client
from neuprint import fetch_adjacencies, NeuronCriteria, fetch_simple_connections
import pandas as pd
from vfb_connect.cross_server_tools import VfbConnect

class ConnectomicsImport:
    def __init__(self, neuprint_endpoint=None, neuprint_dataset=None, neuprint_token=None):
        self.vc=VfbConnect()
        if neuprint_endpoint and neuprint_dataset and neuprint_token:
            self.neuprint_client=neuprint.Client(neuprint_endpoint, dataset=neuprint_dataset, token=neuprint_token)
        else: self.neuprint_client=None

    def get_adjencies(self, accessions, testmode=False):
        # fetch body ids of only neurons with types
        neur_ids = self.neuprint_client
        # fetch neuron-neuron connectivity for only the filtered neurons within PRIMARY rois only and collapse rois to total
        neuron_df, conn_df = fetch_adjacencies(sources=neur_ids['ID'], targets=neur_ids['ID'])
        conn_df = conn_df.groupby(['bodyId_pre', 'bodyId_post'], as_index=False)['weight'].sum()
        return conn_df#add to stack? in wrapper

    def generate_template(self, dataset):
        vfb_ids_list = self.vc.neo_query_wrapper.xref_2_vfb_id(db=dataset).items()#dictionary comprhension, key first pos (accession) value VFB_id
        seed = { "ID": "ID", "FACT": "I  'synapsed to' %", "Weight": "^A n2o:weight",  "Weight": "^A n2o:weight_per_roi" }
        records = [seed]
        #map lambda function cast


#pull from neuprint function
#catmaid/neuprint
#runner script argparse to parse variables


#fetch body ids of only neurons with types
neur_ids = client.fetch_custom("""MATCH (n:hemibrain_Neuron) WHERE exists(n.type) RETURN n.bodyId as ID""")
#fetch neuron-neuron connectivity for only the filtered neurons within PRIMARY rois only and collapse rois to total
vc=VfbConnect()
vfb_ids_list=list(vc.neo_query_wrapper.xref_2_vfb_id(db=dataset).items())




