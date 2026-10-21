"""Site -> source-release provenance, the .provenance file, and reading the release
back out of an OWL header (both the package parser and the dashboard's copy).

No network: the Site link strings are the real KB values as of 2026-10-21."""
import datetime
import importlib.util
import os

import pytest

from vfb_connectomics_import.connectivity.provenance import (
    VERSION_IRI_BASE, parse_site_links, site_from_owl_header, write_provenance)

HERE = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location(
    "dashboard_probes", os.path.join(HERE, "..", "dashboard", "probes.py"))
probes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probes)

DAY = datetime.date(2026, 10, 21)

LINKS = {
    "male-cns_v1_0": ["https://neuprint.janelia.org/results?dataset=male-cns%3Av1.0&qt=findneurons"
                      "&q=1&qr%5B0%5D%5Bcode%5D=fn&qr%5B0%5D%5Bds%5D=male-cns%3Av01.0",
                      "https://neuprint.janelia.org/?dataset=male-cns:v1.0"],
    "neuprint_JRC_Hemibrain_1point2point1": [
        "https://neuprint.janelia.org/results?dataset=hemibrain:v1.2.1&qt=findneurons&tab=0"
        "&ftab=&q=1&qr[0][code]=fn&qr[0][ds]=hemibrain:v1.2.1&qr[0]"],
    "BANC888": ["https://codex.flywire.ai/app/cell_details?dataset=banc&data_version=888&root_id=",
                "https://codex.flywire.ai/?dataset=banc"],
    "flywire783": ["https://codex.flywire.ai/app/cell_details?data_version=783&root_id=",
                   "https://flywire.ai/"],
    "catmaid_l1em": ["https://l1em.catmaid.virtualflybrain.org/?pid=1&tool=tracingtool&sid0=1"
                     "&s0=2&active_skeleton_id="],
}


@pytest.mark.parametrize("site,kind,source,version", [
    ("male-cns_v1_0", "neuprint", "male-cns:v1.0", "v1.0"),
    ("neuprint_JRC_Hemibrain_1point2point1", "neuprint", "hemibrain:v1.2.1", "v1.2.1"),
    ("BANC888", "codex", "banc:888", "888"),
    ("flywire783", "codex", "flywire:783", "783"),
    ("catmaid_l1em", "catmaid", "catmaid_l1em:2026-10-21", "2026-10-21"),
])
def test_parse_site_links(site, kind, source, version):
    p = parse_site_links(site, LINKS[site], today=DAY)
    assert (p.kind, p.source, p.version) == (kind, source, version)
    assert p.version_iri == VERSION_IRI_BASE + site + "_import.owl"
    assert site in p.dc_source


def test_typed_accessors():
    assert parse_site_links("male-cns_v1_0", LINKS["male-cns_v1_0"]).neuprint_dataset == "male-cns:v1.0"
    assert parse_site_links("BANC888", LINKS["BANC888"]).materialization == 888
    cat = parse_site_links("catmaid_l1em", LINKS["catmaid_l1em"], today=DAY)
    assert cat.endpoint == "https://l1em.catmaid.virtualflybrain.org/"
    assert cat.neuprint_dataset is None and cat.materialization is None


def test_unrecognised_links_refuse():
    with pytest.raises(ValueError):
        parse_site_links("mystery", ["https://example.org/"])


def test_write_provenance(tmp_path):
    p = parse_site_links("BANC888", LINKS["BANC888"])
    path = write_provenance(str(tmp_path / "x.tsv"), p)
    rows = dict(line.rstrip("\n").split("\t") for line in open(path))
    assert rows["SITE"] == "BANC888"
    assert rows["VERSION_IRI"] == VERSION_IRI_BASE + "BANC888_import.owl"
    assert rows["DC_SOURCE"] == "banc:888 (Site BANC888)"


OFN_STAMPED = """Prefix(owl:=<http://www.w3.org/2002/07/owl#>)

Ontology(<http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl>
<http://virtualflybrain.org/data/VFB/OWL/BANC888_import.owl>
Annotation(<http://purl.org/dc/terms/source> "banc:888 (Site BANC888)")

Declaration(ObjectProperty(<http://purl.obolibrary.org/obo/RO_0002120>))
"""
OFN_UNSTAMPED = """Ontology(<http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl>

Declaration(ObjectProperty(<http://purl.obolibrary.org/obo/RO_0002120>))
"""
RDFXML_STAMPED = """<owl:Ontology rdf:about="http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl">
    <owl:versionIRI rdf:resource="http://virtualflybrain.org/data/VFB/OWL/male-cns_v1_0_import.owl"/>
</owl:Ontology>"""
# a version IRI that does not follow the <Site>_import.owl form is not a release
OFN_OTHER_VERSION_IRI = """Ontology(<http://x/o.owl>
<http://x/o/2026-01-01/o.owl>
"""


@pytest.mark.parametrize("text,site", [
    (OFN_STAMPED, "BANC888"),
    (OFN_UNSTAMPED, None),
    (RDFXML_STAMPED, "male-cns_v1_0"),
    (OFN_OTHER_VERSION_IRI, None),
])
def test_site_from_owl_header_package_and_dashboard_agree(text, site):
    assert site_from_owl_header(text) == site
    assert probes.site_from_owl_header(text) == site


def test_dashboard_reads_dc_source_and_matches_site_spellings():
    assert probes._dc_source_from_owl_header(OFN_STAMPED) == "banc:888 (Site BANC888)"
    assert probes._same_site("male-cns_v1_0", "male_cns_v1_0")
    assert not probes._same_site("BANC626", "BANC888")
