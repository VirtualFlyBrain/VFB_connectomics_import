import base64, json, os, sys, urllib.request
EP = 'http://kb.virtualflybrain.org:80'
def q(stmt, endpoint=EP):
    user = os.environ.get('KB_USER') or 'neo4j'
    pw = os.environ.get('KB_PASSWORD') or 'vfb'
    req = urllib.request.Request(
        f'{endpoint}/db/data/transaction/commit',
        data=json.dumps({'statements': [{'statement': stmt}]}).encode(),
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Basic ' + base64.b64encode(f'{user}:{pw}'.encode()).decode()})
    d = json.load(urllib.request.urlopen(req, timeout=900))
    if d.get('errors'):
        raise SystemExit(f'KB query failed: {d["errors"]}')
    return [x['row'] for x in d['results'][0]['data']]
