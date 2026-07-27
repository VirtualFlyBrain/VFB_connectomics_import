"""Status probes for the VFB connectome import dashboard.

Each probe answers ONE question about ONE stage-cell and is deliberately
failure-tolerant: any network/parse error degrades to an "unknown" state (or,
for the live check, to "not checked") rather than raising — so a flaky endpoint
never breaks dashboard generation in CI.

Probes are pure-stdlib (urllib) so CI needs no dependencies beyond PyYAML.

A fill probe returns (state, detail):
    state  in FILL_STATES
    detail is a short human string shown in the cell tooltip
A live probe returns (live, detail):
    live   is True / False / None   (None = not checked / not applicable)
An update probe returns (needs_update, detail):
    needs_update is True / False / None
"""

import glob
import json
import os
import re
import ssl
import urllib.request
import urllib.error

FILL_STATES = ("done", "needs_update", "in_progress", "not_started", "unknown")

_HTTP_TIMEOUT = 25
_index_cache = {}   # url -> {filename: (date_str, size_int)}

# Build a verified SSL context (prefer certifi's CA bundle if installed).
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:                         # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()
_UNVERIFIED_CTX = ssl._create_unverified_context()


# --------------------------------------------------------------------------- #
# low-level HTTP helpers
# --------------------------------------------------------------------------- #
def _urlopen(req):
    """Open a request, falling back to an unverified context only if the local
    trust store can't validate the cert (public read-only endpoints)."""
    try:
        return urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=_SSL_CTX)
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            return urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT,
                                          context=_UNVERIFIED_CTX)
        raise


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with _urlopen(req) as r:
        return r.read().decode("utf-8", "replace")


def _post_json(url, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with _urlopen(req) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------- #
# owl_index — is a matching OWL live on the VFB data server?
# --------------------------------------------------------------------------- #
_INDEX_RE = re.compile(
    r'<a href="([^"/]+)">[^<]*</a>\s+'
    r'(\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2})\s+(\d+|-)'
)


def _fetch_index(url):
    if url not in _index_cache:
        entries = {}
        try:
            html = _get(url)
            for name, date, size in _INDEX_RE.findall(html):
                entries[name] = (date, int(size) if size.isdigit() else 0)
        except Exception as e:            # noqa: BLE001 — degrade, never raise
            _index_cache[url] = {"__error__": str(e)}
            return _index_cache[url]
        _index_cache[url] = entries
    return _index_cache[url]


def probe_owl_index(cfg, ctx, connectome=None, stage_id=None):
    index = _fetch_index(ctx["owl_index_url"])
    if "__error__" in index:
        return "unknown", "data server unreachable: " + index["__error__"]
    pattern = re.compile(cfg.get("match", "$^"), re.IGNORECASE)
    hits = [(n, d, s) for n, (d, s) in index.items() if pattern.search(n)]
    if not hits:
        return "not_started", "no matching OWL on data server"
    hits.sort(key=lambda h: h[1], reverse=True)   # newest by mtime string
    name, date, size = hits[0]
    return "done", "uploaded: %s (%s, %.0f MB)" % (name, date, size / 1e6)


# --------------------------------------------------------------------------- #
# repo_glob — is a matching artifact present in this repo?
# --------------------------------------------------------------------------- #
def probe_repo_glob(cfg, ctx, connectome=None, stage_id=None):
    pat = os.path.join(ctx["repo_root"], cfg.get("match", ""))
    hits = sorted(glob.glob(pat))
    if not hits:
        return "not_started", "no matching file in repo"
    return "done", "in repo: " + os.path.relpath(hits[-1], ctx["repo_root"])


# --------------------------------------------------------------------------- #
# jenkins — status of a build job
# --------------------------------------------------------------------------- #
def probe_jenkins(cfg, ctx, connectome=None, stage_id=None):
    base = (ctx.get("jenkins_base") or "").rstrip("/")
    job = cfg.get("job") or ""
    if not base or not job:
        return "unknown", "jenkins job not configured"
    url = "%s/job/%s/lastBuild/api/json?tree=building,result,timestamp" % (base, job)
    try:
        info = json.loads(_get(url))
    except Exception as e:                # noqa: BLE001
        return "unknown", "jenkins unreachable: %s" % e
    if info.get("building"):
        return "in_progress", "Jenkins job '%s' is running" % job
    result = info.get("result")
    if result == "SUCCESS":
        return "done", "Jenkins job '%s' succeeded" % job
    if result in ("FAILURE", "UNSTABLE", "ABORTED"):
        return "in_progress", "Jenkins job '%s' last result: %s" % (job, result)
    return "unknown", "Jenkins job '%s' state unclear" % job


# --------------------------------------------------------------------------- #
# neuprint_upstream — is a newer version available upstream? (update probe)
# --------------------------------------------------------------------------- #
def probe_neuprint_upstream(cfg, ctx, connectome):
    token = os.environ.get("NEUPRINT_TOKEN")
    ds = connectome.get("neuprint_dataset")
    if not token or not ds:
        return None, "upstream check skipped (no NEUPRINT_TOKEN or dataset)"
    try:
        data = json.loads(_get(
            "https://neuprint.janelia.org/api/dbmeta/datasets",
            headers={"Authorization": "Bearer " + token},
        ))
    except Exception as e:                # noqa: BLE001
        return None, "neuprint unreachable: %s" % e
    # datasets keyed like "male-cns:v1.0"; find newest version for this dataset
    versions = []
    for key, val in (data or {}).items():
        name = key.split(":")[0]
        if name == ds:
            versions.append(str(val.get("lastDatabaseEdit") or key.split(":")[-1]))
    if not versions:
        return None, "dataset '%s' not found upstream" % ds
    latest = sorted(versions)[-1]
    local = str(connectome.get("version") or "")
    if local and local not in latest and latest not in local:
        return True, "upstream latest: %s (local %s)" % (latest, local)
    return False, "up to date with upstream (%s)" % latest


# --------------------------------------------------------------------------- #
# pdb_cypher — is it actually LIVE in the current release? (live probe)
# --------------------------------------------------------------------------- #
def _default_live_query(stage_id, site):
    """Stage-aware default Cypher; returns None if no sensible default."""
    if not site:
        return None
    base = ("MATCH (n)-[:database_cross_reference|hasDbXref]-"
            "(:Site {short_form:'%s'}) " % site)
    if stage_id == "neurons":
        return base + "RETURN count(DISTINCT n) AS c"
    if stage_id == "n2n":
        return (base + "WITH n LIMIT 3000 "
                "MATCH (n)-[r:synapsed_to]-() RETURN count(r) AS c")
    if stage_id == "n2r":
        return (base + "WITH n LIMIT 3000 MATCH (n)-[r:has_presynaptic_terminals_in|"
                "has_postsynaptic_terminal_in|has_synaptic_IO_in_region]-() "
                "RETURN count(r) AS c")
    return None   # skel / types have no default -> no dot


def probe_pdb_cypher(cfg, ctx, connectome, stage_id):
    query = cfg.get("query")
    if not query:
        query = _default_live_query(stage_id, connectome.get("vfb_site"))
    if not query:
        return None, "no live query for this cell"
    try:
        res = _post_json(ctx["pdb_tx_url"], {"statements": [{"statement": query}]})
    except Exception as e:                # noqa: BLE001
        return None, "PDB unreachable: %s" % e
    if res.get("errors"):
        return None, "PDB query error: %s" % res["errors"]
    try:
        count = res["results"][0]["data"][0]["row"][0]
    except (KeyError, IndexError, TypeError):
        return None, "PDB returned no rows"
    live = bool(count and count > 0)
    return live, ("live: %s in release" % count) if live else "not live in current release"


# --------------------------------------------------------------------------- #
# manual — fixed state (last resort)
# --------------------------------------------------------------------------- #
def probe_manual(cfg, ctx, connectome=None, stage_id=None):
    state = cfg.get("state", "unknown")
    if state not in FILL_STATES:
        state = "unknown"
    return state, "set manually in manifest"


def probe_pdb_exists(cfg, ctx, connectome, stage_id):
    """Fill probe: present in PDB -> done, else not_started. For stages whose
    'done' and 'live' are the same fact (e.g. neurons loaded)."""
    live, detail = probe_pdb_cypher(cfg, ctx, connectome, stage_id)
    if live is True:
        return "done", detail
    if live is False:
        return "not_started", detail
    return "unknown", detail


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
_FILL = {
    "owl_index": probe_owl_index,
    "repo_glob": probe_repo_glob,
    "jenkins": probe_jenkins,
    "manual": probe_manual,
    "pdb_cypher": probe_pdb_exists,
}


def run_fill(cfg, ctx, connectome, stage_id):
    if not cfg:
        return "not_started", "no probe configured"
    fn = _FILL.get(cfg.get("type"))
    if not fn:
        return "unknown", "unknown probe type: %s" % cfg.get("type")
    try:
        return fn(cfg, ctx, connectome, stage_id)
    except Exception as e:                # noqa: BLE001
        return "unknown", "probe error: %s" % e


def run_update(cfg, ctx, connectome):
    if not cfg or cfg.get("type") != "neuprint_upstream":
        return None, ""
    try:
        return probe_neuprint_upstream(cfg, ctx, connectome)
    except Exception as e:                # noqa: BLE001
        return None, "update probe error: %s" % e


def run_live(cfg, ctx, connectome, stage_id):
    if not cfg or cfg.get("type") != "pdb_cypher":
        return None, ""
    try:
        return probe_pdb_cypher(cfg, ctx, connectome, stage_id)
    except Exception as e:                # noqa: BLE001
        return None, "live probe error: %s" % e
