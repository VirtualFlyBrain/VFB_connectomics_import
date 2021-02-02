from connectomics_import import ConnectomicsImport
import argparse

#Setup arguments for argparse to allow input of ds, doi and filepaths in terminal
parser = argparse.ArgumentParser(description='Script accepts a VFB dataset name and external database login details (neuprint/CATMAID (only neuprint currently)) and returns the neuron-neuron connectivity between the neurons in the dataset. A threshold can be set to filter out connections at or below the threshold (default=1).')
parser.add_argument('--neuprint_endpoint', '-n_e', type=str, help='NeuPrint endpoint URL string')#just enpoint for catmaid check for optional
parser.add_argument('--neuprint_dataset', '-n_d', type=str, help='NeuPrint dataset string')
parser.add_argument('--neuprint_token', '-n_t', type=str, help='NeuPrint auth token string')
parser.add_argument('--threshold', '-t', type=int, help='Neuron-neuron connections which are not greater than this integer will be omitted')
parser.add_argument('--dataset', '-d', type=str, help='VFB dataset string')
parser.add_argument('--catmaid_endpoint', '-c_e', type=str, help='CATMAID endpoint URL string (see VFB website for public CATMAID servers')
#add catmaid/neuprint as arg
args = vars(parser.parse_args())

#asign args to variables
neuprint_endpoint = args['neuprint_endpoint']
neuprint_dataset = args['neuprint_dataset']
neuprint_token = args['neuprint_token']
threshold = args['threshold']
dataset = args['dataset']
catmaid_endpoint = args['catmaid_endpoint']

# neuprint_endpoint = 'https://neuprint.janelia.org'
# neuprint_dataset = 'hemibrain:v1.1'
# neuprint_token = ''
# threshold = 1
# dataset = 'neuprint_JRC_Hemibrain_1point1'
# catmaid_endpoint = 'https://fafb.catmaid.virtualflybrain.org/'

ci=ConnectomicsImport(neuprint_endpoint=neuprint_endpoint,
                      neuprint_dataset=neuprint_dataset,
                      neuprint_token=neuprint_token,
                      catmaid_endpoint=catmaid_endpoint)

accessions=ci.get_accessions_from_vfb(dataset)

conn_df=ci.get_adjacencies_neuprint(accessions=accessions, threshold=threshold)

robot_template_df=ci.generate_n_n_template(dataset, conn_df)

robot_template_df.to_csv('Robot_template.tsv', sep='\t', index=False)
# dataset_template

