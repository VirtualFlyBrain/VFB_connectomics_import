from connectomics_import import ConnectomicsImport
# import argparse
#
# #Setup arguments for argparse to allow input of ds, doi and filepaths in terminal
# parser = argparse.ArgumentParser(description='Script accepts a VFB dataset name and external database login details (neuprint/CATMAID (only neuprint currently)) and returns the neuron-neuron connectivity between the neurons in the dataset. A threshold can be set to filter out connections at or below the threshold (default=1).')
# parser.add_argument('--neuprint_endpoint', '-n_e', type=str, help='NeuPrint endpoint URL string')#just enpoint for catmaid check for optional
# parser.add_argument('--neuprint_dataset', '-n_d', type=str, help='NeuPrint dataset string')
# parser.add_argument('--neuprint_token', '-n_t', type=str, help='NeuPrint auth token string')
# parser.add_argument('--threshold', '-t', type=int, help='Neuron-neuron connections which are not greater than this integer will be omitted')
# parser.add_argument('--dataset', '-d', type=str, help='VFB dataset string')
# parser.add_argument('--output_file', '-o', type=str, help='output filepath')
# #add catmaid/neuprint as arg
# args = vars(parser.parse_args())
#
# #asign args to variables
# neuprint_endpoint = args['neuprint_endpoint']
# neuprint_dataset = args['neuprint_dataset']
# neuprint_token = args['neuprint_token']
# threshold = args['threshold']
# dataset = args['dataset']
# output_file = args['output_file']

dataset = 'Dorkenwald2023'
threshold = 1
output_file = 'connectome_FAFBFL_1_0_n2n.tsv'
db = 'flywire783'

ci=ConnectomicsImport()

accessions=ci.get_accessions_from_vfb(dataset, db)

conn_df=ci.get_adjacencies_flywire(accessions=accessions, threshold=threshold)

robot_template_df=ci.generate_n_n_template(db, conn_df)

robot_template_df.to_csv(output_file, sep='\t', index=False)
