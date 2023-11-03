from connectomics_import import ConnectomicsImport
import argparse

#Setup arguments for argparse to allow input of ds, doi and filepaths in terminal
parser = argparse.ArgumentParser(description='Script accepts a VFB dataset name and external database login details (neuprint/CATMAID (only neuprint currently)) and returns the neuron-neuron connectivity between the neurons in the dataset. A threshold can be set to filter out connections at or below the threshold (default=1).')
parser.add_argument('--threshold', '-t', type=int, help='Neuron-neuron connections which are not greater than this integer will be omitted')
parser.add_argument('--dataset', '-d', type=str, help='VFB dataset string')
parser.add_argument('--catmaid_endpoint', '-c_e', type=str, help='CATMAID endpoint URL string (see VFB website for public CATMAID servers')
parser.add_argument('--output_file', '-o', type=str, help='output filepath')
#add catmaid/neuprint as arg
args = vars(parser.parse_args())

#asign args to variables
threshold = args['threshold']
dataset = args['dataset']
catmaid_endpoint = args['catmaid_endpoint']
output_file=args['output_file']

# for testing FAFB
# threshold = 100
# dataset = 'catmaid_fafb'
# catmaid_endpoint = 'https://fafb.catmaid.virtualflybrain.org/'
# output_file = 'test.tsv'

#for testing L1EM
# threshold = 1
# dataset = 'catmaid_l1em'
# catmaid_endpoint = 'https://l1em.catmaid.virtualflybrain.org/'
# output_file = 'test.tsv'

ci=ConnectomicsImport(catmaid_endpoint=catmaid_endpoint)

accessions=ci.get_accessions_from_vfb(dataset)

conn_df=ci.get_adjacencies_CATMAID(accessions, threshold=threshold)

robot_template_df=ci.generate_n_n_template(dataset, conn_df)

robot_template_df.to_csv(output_file, sep='\t', index=False)