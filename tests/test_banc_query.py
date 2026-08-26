from vfb_connect.neo.neo4j_tools import Neo4jConnect
import pandas as pd

vc = Neo4jConnect("http://kb.virtualflybrain.org")

dataset = "Bates2025"
db = "flywire_banc"

query = 'MATCH (ds {short_form:"' + dataset + '"})-[:has_source]-(n)-[a:database_cross_reference|hasDbXref]-(:Site {short_form: "' + db + '"}) RETURN DISTINCT a.accession[0]'

print(f"Query: {query}\n")

accessions = vc.commit_list([query])
print(f"Raw result: {accessions}\n")

if accessions and len(accessions) > 0:
    print(f"First result: {accessions[0]}\n")
    print(f"Keys: {accessions[0].keys()}\n")
    
    if 'data' in accessions[0]:
        df = pd.DataFrame(accessions[0]['data'])
        print(f"DataFrame columns: {df.columns.tolist()}\n")
        print(f"DataFrame head:\n{df.head()}\n")
