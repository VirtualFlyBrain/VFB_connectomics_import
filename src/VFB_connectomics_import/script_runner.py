from connectomics_import import ConnectomicsImport

#TODO add argparse here

ci=ConnectomicsImport(neuprint_endpoint='https://neuprint.janelia.org',
                      neuprint_dataset='hemibrain:v1.1',
                      neuprint_token='')

accessions=ci.get_accessions_from_vfb('neuprint_JRC_Hemibrain_1point1')

conn_df=ci.get_adjacencies_neuprint(accessions=accessions[0:100])

robot_template_df=ci.generate_template('neuprint_JRC_Hemibrain_1point1', conn_df)

robot_template_df.to_csv('Robot_template.tsv', sep='\t', index=False)

