from connectomics_import import ConnectomicsImport

#could add argparse here

nc=neuprint.Client('https://neuprint.janelia.org',
                      dataset='hemibrain:v1.1',
                      token='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6ImFkbTcxQGNhbS5hYy51ayIsImxldmVsIjoibm9hdXRoIiwiaW1hZ2UtdXJsIjoiaHR0cHM6Ly9saDQuZ29vZ2xldXNlcmNvbnRlbnQuY29tLy1pNDJ6MjMtUkUxTS9BQUFBQUFBQUFBSS9BQUFBQUFBQUFBQS9BTVp1dWNua2hPVm9rZExRVURESkdNdHVSXzJadTROeUNnL3M5Ni1jL3Bob3RvLmpwZz9zej01MD9zej01MCIsImV4cCI6MTc4NjEyODQzMn0.nqLX9LffweDHZ5QMqhSodH7w35fRO7gXAvINYE-3OGg')

accessions = list(nc.fetch_custom("""MATCH (n:hemibrain_Neuron) WHERE exists(n.type) RETURN n.bodyId as ID""")['ID'])

ci=ConnectomicsImport(neuprint_endpoint='https://neuprint.janelia.org',
                      neuprint_dataset='hemibrain:v1.1',
                      neuprint_token='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6ImFkbTcxQGNhbS5hYy51ayIsImxldmVsIjoibm9hdXRoIiwiaW1hZ2UtdXJsIjoiaHR0cHM6Ly9saDQuZ29vZ2xldXNlcmNvbnRlbnQuY29tLy1pNDJ6MjMtUkUxTS9BQUFBQUFBQUFBSS9BQUFBQUFBQUFBQS9BTVp1dWNua2hPVm9rZExRVURESkdNdHVSXzJadTROeUNnL3M5Ni1jL3Bob3RvLmpwZz9zej01MD9zej01MCIsImV4cCI6MTc4NjEyODQzMn0.nqLX9LffweDHZ5QMqhSodH7w35fRO7gXAvINYE-3OGg')

conn_df=ci.get_adjacencies(accessions=accessions)

