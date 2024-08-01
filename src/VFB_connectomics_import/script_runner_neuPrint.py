from connectomics_import import ConnectomicsImport
import argparse

#Setup arguments for argparse to allow input of ds, doi and filepaths in terminal
parser = argparse.ArgumentParser(description='Script accepts a VFB dataset name and external database login details (neuprint/CATMAID (only neuprint currently)) and returns the neuron-neuron connectivity between the neurons in the dataset. A threshold can be set to filter out connections at or below the threshold (default=1).')
parser.add_argument('--neuprint_endpoint', '-n_e', type=str, help='NeuPrint endpoint URL string')#just enpoint for catmaid check for optional
parser.add_argument('--neuprint_dataset', '-n_d', type=str, help='NeuPrint dataset string')
parser.add_argument('--neuprint_token', '-n_t', type=str, help='NeuPrint auth token string')
parser.add_argument('--threshold', '-t', type=int, help='Neuron-neuron connections which are not greater than this integer will be omitted')
parser.add_argument('--dataset', '-d', type=str, help='VFB dataset string')
parser.add_argument('--output_file', '-o', type=str, help='output filepath')
#add catmaid/neuprint as arg
args = vars(parser.parse_args())

#asign args to variables
neuprint_endpoint = args['neuprint_endpoint']
neuprint_dataset = args['neuprint_dataset']
neuprint_token = args['neuprint_token']
threshold = args['threshold']
dataset = args['dataset']
output_file = args['output_file']

neuprint_endpoint = 'https://neuprint.janelia.org'
neuprint_dataset = 'optic-lobe:v1.0'
neuprint_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6ImFkbTcxQGNhbS5hYy51ayIsImxldmVsIjoibm9hdXRoIiwiaW1hZ2UtdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jTFhRZzltNUpUWjVibmdjRl9lSXROa1cxQUtVcU5IWmpfVENJWXl1VnZwT19mUHJBPXM5Ni1jP3N6PTUwP3N6PTUwIiwiZXhwIjoxOTAxNjQ3MDMwfQ.bqzIwWAGNEcrpvaRX_M-U33d46xfTK7XxVKhz6P6BqQ'
threshold = 1
dataset = 'Nern2024'
output_file = 'Nern2024_n_2_n.tsv'
db='neuprint_JRC_OpticLobe_v1_0'

ci=ConnectomicsImport(neuprint_endpoint=neuprint_endpoint,
                      neuprint_dataset=neuprint_dataset,
                      neuprint_token=neuprint_token)

accessions=ci.get_accessions_from_vfb(dataset) #TODO this should have dataset

conn_df=ci.get_adjacencies_neuprint(accessions=accessions, threshold=threshold)

robot_template_df=ci.generate_n_n_template(db, conn_df)

robot_template_df.to_csv(output_file, sep='\t', index=False)