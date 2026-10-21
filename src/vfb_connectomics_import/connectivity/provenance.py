"""Which source release a connectivity build came from, derived from its VFB Site.

The VFB `Site` short_form is the canonical version token for a connectome (BANC888,
male-cns_v1_0, flywire783, ...). Everything else a build needs to know about its
source release is recorded on that Site's `link_base`:

  * neuprint  — `dataset=male-cns:v1.0`        -> neuprint dataset to query
  * codex     — `data_version=888` (+ `dataset=banc`) -> CAVE / bucket materialization
  * CATMAID   — `https://<host>/?pid=<n>`      -> live server, no version

so each build takes one argument, `--site`, and derives the rest here. The build
stamps it into the OWL header it writes (version IRI + dc:source; owl_writer.py),
so the artifact records its release no matter what it is named; for the legacy
ROBOT-template output it is written alongside as `<template>.provenance`. The
import dashboard reads the header back (`owl_header` probe).

Parsing is kept free of network and heavy imports so it can be tested on its own.
"""
import datetime
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

VERSION_IRI_BASE = "http://virtualflybrain.org/data/VFB/OWL/"


@dataclass
class Provenance:
    site: str                 # VFB Site short_form, the version token
    kind: str                 # "neuprint" | "codex" | "catmaid"
    source: str               # e.g. "male-cns:v1.0", "banc:888", "flywire:783"
    version: str = ""         # source release: "v1.0", "888", or the build date for CATMAID
    endpoint: str = ""        # CATMAID server base URL

    @property
    def neuprint_dataset(self):
        """neuprint dataset string ("male-cns:v1.0"); only for kind == neuprint."""
        return self.source if self.kind == "neuprint" else None

    @property
    def materialization(self):
        """CAVE / bucket materialization (int); only for kind == codex."""
        return int(self.version) if self.kind == "codex" else None

    @property
    def version_iri(self):
        return VERSION_IRI_BASE + self.site + "_import.owl"

    @property
    def dc_source(self):
        if self.kind == "catmaid":
            return "CATMAID %s (Site %s), as of %s" % (self.endpoint, self.site, self.version)
        return "%s (Site %s)" % (self.source, self.site)


def parse_site_links(site, link_texts, today=None):
    """Provenance from a Site's link_base / homepage strings.

    Raises ValueError if none of them identifies a source release, so a build
    never proceeds with a version it could not establish."""
    texts = [unquote(t) for t in link_texts if isinstance(t, str)]
    for text in texts:
        m = re.search(r"[?&]dataset=([^&\s]+:v[^&\s]+)", text)
        if m and "neuprint" in text:
            ds = m.group(1)
            return Provenance(site, "neuprint", ds, ds.partition(":")[2])
    for text in texts:
        q = parse_qs(urlsplit(text).query)
        if "data_version" in q and "codex" in text:
            name = (q.get("dataset") or ["flywire"])[0]
            v = q["data_version"][0]
            return Provenance(site, "codex", "%s:%s" % (name, v), v)
    for text in texts:
        parts = urlsplit(text)
        if "catmaid" in parts.netloc:
            pid = (parse_qs(parts.query).get("pid") or ["1"])[0]
            day = (today or datetime.date.today()).isoformat()
            return Provenance(site, "catmaid", "%s:%s" % (site, day), day,
                              endpoint="%s://%s/" % (parts.scheme, parts.netloc))
    raise ValueError("cannot tell which source release Site %r is from its links: %r"
                     % (site, link_texts))


def site_links(nc, site):
    """link_base and homepage strings of a Site, via a vfb_connect Neo4jConnect."""
    q = ('MATCH (s:Site {short_form:"%s"}) RETURN s.link_base AS lb, s.homepage AS hp'
         % site.replace('"', ''))
    rows = nc.commit_list([q])
    data = rows[0]["data"] if rows and rows[0].get("data") else []
    if not data:
        raise ValueError("no Site %r in the KB" % site)
    out = []
    for val in data[0]["row"]:
        out.extend(val if isinstance(val, list) else [val])
    return [v for v in out if v]


def site_provenance(nc, site, today=None):
    return parse_site_links(site, site_links(nc, site), today=today)


def write_provenance(template_path, prov):
    """Write <template>.provenance (tab-separated KEY, VALUE lines) next to a legacy
    ROBOT template, for whoever runs `robot template` on it to stamp into the OWL
    header (annotate --version-iri / --annotation dc:source). Returns the path."""
    path = template_path + ".provenance"
    with open(path, "w") as fh:
        for key, value in (("SITE", prov.site), ("SOURCE", prov.source),
                           ("VERSION_IRI", prov.version_iri), ("DC_SOURCE", prov.dc_source)):
            fh.write("%s\t%s\n" % (key, value))
    return path


_VERSION_IRI_RE = re.compile(re.escape(VERSION_IRI_BASE) + r"([A-Za-z0-9_.-]+?)_import\.owl")


def site_from_owl_header(text):
    """The Site stamped into an OWL file's version IRI, from the first few kB of the
    file (functional syntax or RDF/XML), or None if it carries no version IRI.

    In OFN the version IRI is the second IRI of `Ontology(<iri> <version-iri>`; in
    RDF/XML it is `owl:versionIRI rdf:resource="..."`. Only a version IRI counts:
    the ontology IRI (e.g. BANC_import.owl) never encodes a release."""
    m = re.search(r"Ontology\(\s*<[^>]+>\s*<([^>]+)>", text)
    if not m:
        m = re.search(r"versionIRI[^>]*?rdf:resource=\"([^\"]+)\"", text)
    if not m:
        return None
    v = _VERSION_IRI_RE.fullmatch(m.group(1))
    return v.group(1) if v else None
