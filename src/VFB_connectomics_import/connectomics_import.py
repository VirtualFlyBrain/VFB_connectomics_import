from dotenv import load_dotenv
import os
import neuprint
from neuprint import Client
from neuprint import fetch_adjacencies, NeuronCriteria, fetch_simple_connections
import pandas as pd

#define neuprint API token variable from .env (located in src)
env_path='/Users/alexmclachlan/Documents/GitHub/VFB_connectomics_import/src/.env.txt'
load_dotenv(dotenv_path=env_path)
token = os.getenv('neuPRINT_API_token')

#login to neuprint
client = neuprint.Client('https://neuprint.janelia.org', dataset='hemibrain:v1.1', token=token)
client.fetch_version()

#fetch body ids of only neurons with types - just make this an arg with the current as default?
neur_ids = client.fetch_custom("""MATCH (n:hemibrain_Neuron) WHERE exists(n.type) RETURN n.bodyId as ID""")

#fetch neuron-neuron connectivity for only the filtered neurons within PRIMARY rois only and collapse rois to total
neuron_df, conn_df = fetch_adjacencies(sources=neur_ids['ID'][0], targets=neur_ids['ID'])
conn_df=conn_df.groupby(['bodyId_pre', 'bodyId_post'], as_index=False)['weight'].sum()

