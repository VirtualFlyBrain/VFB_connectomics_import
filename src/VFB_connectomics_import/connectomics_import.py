import neuprint
from neuprint import Client
from neuprint import fetch_adjacencies
import pandas as pd
from vfb_connect.cross_server_tools import VfbConnect
from fafbseg import flywire
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

    def get_accessions_from_vfb(self, dataset, db=None):
        #flywire needs to know the version to get the correct accessions
        if db:
            query = 'MATCH (ds {short_form:"' + dataset + '"})-[:has_source]-(n)-[a:database_cross_reference|hasDbXref]-(:Site {short_form: "' + db + '"}) RETURN DISTINCT a.accession[0]'
        else:
            query = 'MATCH (ds {short_form:"' + dataset + '"})-[:has_source]-(n)-[a:database_cross_reference|hasDbXref]-(:Site) RETURN DISTINCT a.accession[0]'
        accessions = self.vc.nc.commit_list([query])
        
        # Handle empty results
        if not accessions or not accessions[0].get('data'):
            print(f"Warning: No data returned from query for dataset '{dataset}'" + (f" and db '{db}'" if db else ""))
            print(f"Query: {query}")
            return []
        
        df = pd.DataFrame(accessions[0]['data'])
        if 'row' not in df.columns:
            print(f"Warning: Query returned data but no 'row' column. Columns: {df.columns.tolist()}")
            print(f"Data: {accessions[0]['data']}")
            return []
            
        accessions_list = list(df['row'].explode())
        accessions_list = list(map(int, accessions_list))
        return accessions_list #call function

    ##get_adjacencies functions must return a df of 'source' - xref (bodyId), 'target' - xref (bodyId), 'weight'- int
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

    ###This function seems to crash my mac if too man neurons are requested. - try using get_connectivity based function below.
    # def get_adjacencies_flywire(self, accessions, threshold=0):
    #     conn_df = flywire.get_adjacency(accessions, materialization=783, filtered=True)
    #     conn_df = conn_df.stack().reset_index(name='weight')
    #     conn_df = conn_df[conn_df.weight > threshold]
    #     return conn_df

    def get_adjacencies_flywire(self, accessions, threshold=0, batchsize=1000, dataset='public', materialization=783):
        conn_df=pd.DataFrame()
        batchsize = batchsize # batching allows filtering to be applied periodically so that the df isn't clogged with irrelevant connectivity
        for i in range(0, len(accessions), batchsize): #should probably print overall progress as well.
            batch = accessions[i:i + batchsize] #last batch will likely not be as large as the batchsize, also these batches are also sub batched by the get_connectivity below
            batch_df = flywire.get_connectivity(batch, upstream=False, downstream=True, materialization=materialization, filtered=True, clean=True, batch_size=100, dataset=dataset, proofread_only=True) #getting all downstream connectivity gets all connectivity.
            batch_df = batch_df[batch_df['post'].isin(accessions)][batch_df.weight > threshold] #filter out connections below threshold + only need connections to downstream partners which exist in vfb
            conn_df=pd.concat([conn_df, batch_df]) #add batch to main conn_df
        conn_df.rename(columns={'pre': 'source', 'post': 'target'}, inplace=True)
        return conn_df

    def generate_n_n_template(self, db, conn_df):
        robot_template_df=pd.DataFrame({'ID': ['ID'], 'TYPE': ['TYPE'], 'FACT': ["I 'synapsed to'"], 'Weight': ['>AT n2o:weight^^xsd:integer']})
        vfb_ids = self.vc.neo_query_wrapper.xref_2_vfb_id(db=db).items()
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
    #       TODO need to convert per region adjacency matrices to template rows somehow. Is this the best way to do this, I'm pretty sure could work but slow?

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