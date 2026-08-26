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

import base64
import glob
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
import urllib.error

FILL_STATES = ("done", "needs_update", "in_progress", "not_started", "unknown")

_HTTP_TIMEOUT = 25

# Server-side budget for a single Cypher statement, in ms.
#
# A client timeout only ends OUR side of the conversation — the transaction keeps
# running on the database. VFB has been bitten by exactly this: a runaway query
# took pdb.virtualflybrain.org down and carried on after the client had given up
# and been killed, with each retry stacking another copy onto an already
# struggling server. Neo4j's HTTP API honours `max-execution-time`; the
# documented `Neo4j-Transaction-Timeout` is ignored by this server.
#
# Deliberately ABOVE _HTTP_TIMEOUT: we abandon at 25s, so anything this budget
# kills is work we already stopped waiting for. That ordering means the budget
# can never turn a query we'd have accepted into a spurious ExecutionFailed.
_MAX_EXECUTION_MS = 60000

_index_cache = {}   # url -> {filename: (date_str, size_int)}

# Build a verified SSL context (prefer certifi's CA bundle if installed).
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:                         # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()
_UNVERIFIED_CTX = ssl._create_unverified_context()


# --------------------------------------------------------------------------- #
# safety rails
#
# These do not assume anything about what a credential is *allowed* to do. The
# KB account may be read-only today; it may not be tomorrow, and a different
# credential may be used later. The guard is the thing that stays true.
# --------------------------------------------------------------------------- #
class ReadOnlyViolation(Exception):
    """Raised rather than sending a statement that could mutate the graph."""


# Clauses that write, plus CALL. CALL is included because it is precisely how a
# denylist like this gets bypassed (apoc.cypher.runWrite, apoc.do.when, ...) —
# blocking it is what makes the rest of the list hold. No probe needs it.
_WRITE_CLAUSES = ("CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP",
                  "FOREACH", "CALL", "LOAD", "TERMINATE", "GRANT", "REVOKE")
_WRITE_RE = re.compile(r"\b(%s)\b" % "|".join(_WRITE_CLAUSES), re.IGNORECASE)


def _assert_read_only(payload):
    """Reject any Cypher that isn't plainly a read.

    Matters because connectomes.yaml accepts arbitrary `query:` strings. That is
    harmless against public read-only PDB, but the same code path carries KB
    credentials — so a typo or an edit to that YAML must not be able to write.
    Word-boundary matching keeps identifiers like `DataSet`, `is_data_source`
    and `database_cross_reference` from tripping it.
    """
    for stmt in (payload or {}).get("statements") or []:
        hit = _WRITE_RE.search(stmt.get("statement") or "")
        if hit:
            raise ReadOnlyViolation(
                "refusing to send non-read-only Cypher (found %r)"
                % hit.group(1).upper())


# Env vars whose values must never reach the published page. KB_USER is
# deliberately absent: a username is not a secret, and blanket-replacing a
# common value like "neo4j" would corrupt legitimate text such as
# 'Basic realm="Neo4j"'.
_SECRET_ENV_VARS = ("KB_PASSWORD", "NEUPRINT_TOKEN")
_USERINFO_RE = re.compile(r"://[^/\s:@]+:[^/\s@]+@")


def _secret_values():
    """Every string that must never be published — including DERIVED forms.

    Actions masks the literal secret in logs, but not transformations of it:
    base64("user:pass") is not the secret string, so neither Actions' masking nor
    a plain replace() of KB_PASSWORD would catch an Authorization header that
    leaked into an error message — and it decodes straight back to the password.
    """
    out = []
    for name in _SECRET_ENV_VARS:
        val = os.environ.get(name)
        if val and len(val) >= 3:
            out.append((val, name))
    user, password = os.environ.get("KB_USER"), os.environ.get("KB_PASSWORD")
    if user and password:
        basic = base64.b64encode(("%s:%s" % (user, password)).encode("utf-8"))
        out.append((basic.decode("ascii"), "KB_BASIC_AUTH"))
    return out


def _scrub(text):
    """Strip known secrets from a string headed for site/index.html.

    GitHub Actions masks secrets in *logs*, but the dashboard writes probe
    details into a page it publishes to GitHub Pages — that masking does not
    apply there, so it has to happen here.
    """
    if not text:
        return text
    out = str(text)
    for val, name in _secret_values():
        out = out.replace(val, "***%s***" % name)
    return _USERINFO_RE.sub("://***:***@", out)


def kb_auth_header():
    """Basic auth header for the KB, or None when no credential is configured.

    The KB answers 401 with `Basic realm="Neo4j"`. Sent as a header rather than
    URL userinfo so it cannot end up inside an exception string.
    """
    user = os.environ.get("KB_USER")
    password = os.environ.get("KB_PASSWORD")
    if not user or not password:
        return None
    token = base64.b64encode(("%s:%s" % (user, password)).encode("utf-8"))
    return {"Authorization": "Basic " + token.decode("ascii")}


# --------------------------------------------------------------------------- #
# low-level HTTP helpers
# --------------------------------------------------------------------------- #
class UnverifiedCredentialError(Exception):
    """Raised instead of re-sending a credential over an unverified connection."""


# Header names that carry a secret. Checked case-insensitively, because
# urllib rewrites header keys with str.capitalize().
_SECRET_HEADERS = frozenset((
    "authorization", "proxy-authorization", "cookie", "x-api-key",
    "api-key", "token", "x-auth-token", "private-token",
))


def _carries_credential(req):
    names = list(req.headers) + list(getattr(req, "unredirected_hdrs", None) or {})
    return any(n.lower() in _SECRET_HEADERS for n in names)


def _urlopen(req):
    """Open a request, falling back to an unverified context only if the local
    trust store can't validate the cert.

    The fallback exists because a machine with an empty CA store (a python.org
    macOS build has zero roots) would otherwise fail every probe. For the public
    read-only endpoints that trade is fine — the worst case is a wrong colour on
    a dashboard cell.

    It is NOT fine for a request carrying a credential: retrying unverified would
    hand the secret (e.g. NEUPRINT_TOKEN) to an unauthenticated peer. Those are
    allowed to fail, and the calling probe degrades to "unknown" — which is
    exactly what it already does when the token is missing entirely.
    """
    try:
        return urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=_SSL_CTX)
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise
        if _carries_credential(req):
            raise UnverifiedCredentialError(
                "refusing to retry an authenticated request without TLS "
                "verification (%s) — install certifi or fix the CA store" % e.reason
            ) from e
        return urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT,
                                      context=_UNVERIFIED_CTX)


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with _urlopen(req) as r:
        return r.read().decode("utf-8", "replace")


def _post_json(url, payload, headers=None):
    """POST a Neo4j transaction payload. This is the ONLY way the dashboard talks
    to PDB — no vfb_connect, no driver, no session to initialise: a probe is just
    'send Cypher, check the response'.

    Every Cypher statement passes _assert_read_only here, so the guard cannot be
    sidestepped by a new probe forgetting to call it.
    """
    _assert_read_only(payload)
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "application/json",
            "max-execution-time": str(_MAX_EXECUTION_MS)}
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
def _parse_version(s):
    """'v1.2.3' or '1.2' -> (1, 2, 3); non-numeric -> ()."""
    nums = re.findall(r"\d+", str(s).lstrip("vV"))
    return tuple(int(n) for n in nums)


def _built_version(connectome):
    """The version the BUILT ARTIFACTS came from — what an update probe must
    compare against.

    `version` in the manifest is the version being TARGETED, which is not the
    same thing once a migration is under way: BANC targets v888 while the OWL on
    the data server is still built from v626. Comparing the target against
    upstream would report "up to date" and hide the stale artifact, because
    artifact filenames carry no version for `owl_index` to discriminate on.

    Connectomes that are not mid-migration omit `built_version` and get the old
    behaviour.
    """
    return connectome.get("built_version") or connectome.get("version")


def probe_neuprint_upstream(cfg, ctx, connectome):
    """Compare the connectome's local version to the newest version neuPrint
    offers. neuPrint's /api/dbmeta/datasets (== Client.fetch_datasets) keys each
    dataset as 'name:vX.Y.Z', so the latest version is the max key suffix.
    Requires NEUPRINT_TOKEN (the endpoint is authenticated)."""
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
    candidates = []
    for key, val in (data or {}).items():
        name, _, ver = key.partition(":")
        if name == ds and ver:
            candidates.append((_parse_version(ver), ver, (val or {}).get("last-mod")))
    if not candidates:
        return None, "dataset '%s' not found upstream" % ds
    candidates.sort()
    _, latest, last_mod = candidates[-1]
    local = _built_version(connectome)
    if not local:
        return None, "upstream latest %s (no local version to compare)" % latest
    if _parse_version(local) < _parse_version(latest):
        return True, "upstream %s available (built from %s, mod %s)" % (latest, local, last_mod)
    return False, "up to date (upstream latest %s)" % latest


# --------------------------------------------------------------------------- #
# pdb_cypher — is it actually LIVE in the current release? (live probe)
# --------------------------------------------------------------------------- #
def probe_gcs_versions(cfg, ctx, connectome):
    """Update probe: list version folders in a public GCS bucket prefix and
    compare the newest to the connectome's local version. Tokenless — uses the
    public JSON storage API. e.g. BANC: bucket=lee-lab_...-connectome,
    prefix=neuron_connectivity/, pattern='v(\\d+)' -> v626, v888."""
    bucket = cfg.get("bucket")
    prefix = cfg.get("prefix", "")
    if not bucket:
        return None, "gcs check skipped (no bucket)"
    url = ("https://storage.googleapis.com/storage/v1/b/%s/o?prefix=%s&delimiter=/"
           % (urllib.parse.quote(bucket), urllib.parse.quote(prefix)))
    try:
        data = json.loads(_get(url))
    except Exception as e:                # noqa: BLE001
        return None, "gcs unreachable: %s" % e
    pat = re.compile(cfg.get("pattern", r"v(\d+)"))
    versions = []
    for p in data.get("prefixes", []):
        m = pat.search(p)
        if m:
            token = m.group(1) if m.groups() else m.group(0)
            versions.append((_parse_version(token), token))
    if not versions:
        return None, "no versioned folders under gs://%s/%s" % (bucket, prefix)
    versions.sort()
    latest = versions[-1][1]
    local = _built_version(connectome)
    if not local:
        return None, "gcs latest v%s (no local version to compare)" % latest
    if _parse_version(local) < _parse_version(latest):
        return True, "gcs v%s available (built from v%s)" % (latest, local)
    return False, "up to date (gcs latest v%s)" % latest


def _default_live_query(stage_id, site):
    """Stage-aware default Cypher; returns None if no sensible default."""
    if not site:
        return None
    if stage_id == "dataset":
        # Existence of the Site node itself, not neurons hanging off it: the
        # dataset record can be published a release before any neuron is.
        return "MATCH (s:Site {short_form:'%s'}) RETURN count(s) AS c" % site
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


def probe_kb_cypher(cfg, ctx, connectome, stage_id):
    """Same as `probe_pdb_cypher` but against the KB, using the KB's short_form.

    Needed because "done" and "live" are NOT the same fact for a version still
    being prepared: neurons can be fully loaded in the KB for a release that PDB
    has not published yet. Probing PDB alone reports not_started and so claims
    the loading has not begun.
    """
    headers = kb_auth_header()
    if not headers:
        return None, "KB_USER / KB_PASSWORD not set — cannot check the KB"
    url = ctx.get("kb_tx_url")
    if not url:
        return None, "no kb_tx_url configured in manifest meta"
    query = cfg.get("query")
    if not query:
        site = connectome.get("kb_site") or connectome.get("vfb_site")
        query = _default_live_query(stage_id, site)
    if not query:
        return None, "no KB query for this cell"
    try:
        res = _post_json(url, {"statements": [{"statement": query}]}, headers=headers)
    except Exception as e:                # noqa: BLE001
        return None, "KB unreachable: %s" % e
    if res.get("errors"):
        return None, "KB query error: %s" % res["errors"]
    try:
        count = res["results"][0]["data"][0]["row"][0]
    except (KeyError, IndexError, TypeError):
        return None, "KB returned no rows"
    present = bool(count and count > 0)
    return present, (("%s in KB" % count) if present else "nothing in KB")


def probe_kb_exists(cfg, ctx, connectome, stage_id):
    """Fill probe: curated in the KB -> done, else not_started."""
    present, detail = probe_kb_cypher(cfg, ctx, connectome, stage_id)
    if present is True:
        return "done", detail
    if present is False:
        return "not_started", detail
    return "unknown", detail


# --------------------------------------------------------------------------- #
# pdb_dataset — does this version's Site / DataSet record exist yet?
# --------------------------------------------------------------------------- #
_SITE_Q = ("MATCH (s:Site {short_form:$sf}) "
           "RETURN 'Connectome' IN labels(s) AS conn, s.is_data_source AS flag")
_DS_Q = "MATCH (d:DataSet {short_form:$df}) RETURN count(d) AS c"


def _truthy(v):
    """PDB returns some booleans wrapped in a single-element list
    (is_data_source comes back as [True], not True)."""
    if isinstance(v, (list, tuple)):
        return any(bool(x) for x in v)
    return bool(v)


def _dataset_record_probe(ctx, connectome, store, url_key, site_key, ds_key,
                          headers=None):
    """Shared implementation of the 'Dataset record' stage check.

    Per VFB versioning (https://virtualflybrain.org/docs/data/em/versioning/)
    each release is a NEW Site, and the `Connectome` label + `is_data_source`
    flag MOVE to it when it becomes authoritative. So there are three states
    worth distinguishing, not two:

      no Site at all                  -> not_started
      Site exists, is_data_source set  -> done
      Site exists, flag NOT set        -> in_progress (record built, not yet
                                         the current source for this release)

    Runs against either store. KB and PDB do NOT share short_form spelling —
    the KB writes e.g. `male-cns_v1_0` and PDB publishes it as `male_cns_v1_0`
    — so each store gets its own manifest key, falling back to the PDB one when
    a connectome does not need to distinguish them.

    The DataSet node is only checked when the manifest supplies a dataset name;
    an absent field is reported, never treated as a failure.
    """
    site = connectome.get(site_key) or connectome.get("vfb_site")
    if not site:
        return "unknown", "no %s in manifest" % site_key
    url = ctx.get(url_key)
    if not url:
        return "unknown", "no %s configured in manifest meta" % url_key
    ds = connectome.get(ds_key) or connectome.get("vfb_dataset")
    stmts = [{"statement": _SITE_Q, "parameters": {"sf": site}}]
    if ds:
        stmts.append({"statement": _DS_Q, "parameters": {"df": ds}})
    try:
        res = _post_json(url, {"statements": stmts}, headers=headers)
    except Exception as e:                # noqa: BLE001
        return "unknown", "%s unreachable: %s" % (store, e)
    if res.get("errors"):
        return "unknown", "%s query error: %s" % (store, res["errors"])

    results = res.get("results") or []
    rows = (results[0].get("data") if results else None) or []
    if not rows:
        return "not_started", "no Site '%s' in %s yet" % (site, store)
    row = list(rows[0].get("row") or [])
    if len(row) < 2:
        # Response shape changed under us — say "unknown" rather than silently
        # reporting every connectome as in_progress.
        return "unknown", ("unexpected %s response shape for Site '%s'"
                           % (store, site))
    conn, flag = row[0], row[1]

    if ds:
        try:
            ds_count = results[1]["data"][0]["row"][0]
        except (IndexError, KeyError, TypeError):
            ds_count = None
        if ds_count == 0:
            return "in_progress", ("Site '%s' present in %s but DataSet '%s' missing"
                                   % (site, store, ds))
        ds_note = "DataSet %s present" % ds
    else:
        ds_note = "DataSet not checked (no dataset name in manifest)"

    if not _truthy(flag):
        return "in_progress", ("Site '%s' exists in %s but is_data_source is unset "
                               "— not yet the current source; %s"
                               % (site, store, ds_note))
    extra = "" if _truthy(conn) else "; warning: no Connectome label"
    return "done", ("Site '%s' is current data source in %s; %s%s"
                    % (site, store, ds_note, extra))


def probe_pdb_dataset(cfg, ctx, connectome, stage_id=None):
    """'Dataset record' as PUBLISHED — the record is live in the current release."""
    return _dataset_record_probe(ctx, connectome, "PDB", "pdb_tx_url",
                                 "vfb_site", "vfb_dataset")


def probe_kb_dataset(cfg, ctx, connectome, stage_id=None):
    """'Dataset record' as CURATED — the record has been authored in the KB.

    Use this rather than `pdb_dataset` for the dataset cell: creating the Site /
    DataSet nodes is a curation step that happens in the KB, and PDB only catches
    up at the next release. Probing PDB for a target version that has been built
    but not yet released reports `not_started`, which reads as "nobody has begun"
    when in fact the work is done and waiting — the one claim this dashboard is
    not allowed to make. The `live` dot is what tracks reaching PDB.

    Needs KB_USER / KB_PASSWORD; degrades to "unknown" without them.
    """
    headers = kb_auth_header()
    if not headers:
        return "unknown", "KB_USER / KB_PASSWORD not set — cannot check the KB"
    return _dataset_record_probe(ctx, connectome, "KB", "kb_tx_url",
                                 "kb_site", "kb_dataset", headers=headers)


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
_FILL = {
    "owl_index": probe_owl_index,
    "repo_glob": probe_repo_glob,
    "jenkins": probe_jenkins,
    "manual": probe_manual,
    "pdb_cypher": probe_pdb_exists,
    "pdb_dataset": probe_pdb_dataset,
    "kb_dataset": probe_kb_dataset,
    "kb_cypher": probe_kb_exists,
}


def run_fill(cfg, ctx, connectome, stage_id):
    if not cfg:
        # "unknown", NOT "not_started": an unwired cell means we never checked,
        # which is not the same claim as "this work has not begun".
        return "unknown", "no probe configured for this cell"
    fn = _FILL.get(cfg.get("type"))
    if not fn:
        return "unknown", "unknown probe type: %s" % cfg.get("type")
    try:
        state, detail = fn(cfg, ctx, connectome, stage_id)
    except Exception as e:                # noqa: BLE001
        return "unknown", _scrub("probe error: %s" % e)
    return state, _scrub(detail)


_UPDATE = {
    "neuprint_upstream": probe_neuprint_upstream,
    "gcs_versions": probe_gcs_versions,
}


def run_update(cfg, ctx, connectome):
    if not cfg:
        return None, ""
    fn = _UPDATE.get(cfg.get("type"))
    if not fn:
        return None, ""
    try:
        needs, detail = fn(cfg, ctx, connectome)
    except Exception as e:                # noqa: BLE001
        return None, _scrub("update probe error: %s" % e)
    return needs, _scrub(detail)


def run_live(cfg, ctx, connectome, stage_id):
    if not cfg or cfg.get("type") != "pdb_cypher":
        return None, ""
    try:
        live, detail = probe_pdb_cypher(cfg, ctx, connectome, stage_id)
    except Exception as e:                # noqa: BLE001
        return None, _scrub("live probe error: %s" % e)
    return live, _scrub(detail)
