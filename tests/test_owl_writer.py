"""The direct n2n OWL writer and the full-file validator (no network, no ROBOT)."""
import gzip
import shutil

import pandas as pd
import pytest

from vfb_connectomics_import.connectivity.owl_writer import ofn_literal, write_n2n_owl
from vfb_connectomics_import.connectivity.validate import (
    ValidationError, diff_report, iter_edges, validate_n2n_owl)

IRI = "http://virtualflybrain.org/data/VFB/OWL/connectome_test.owl"
VER = "http://virtualflybrain.org/data/VFB/OWL/BANC888_import.owl"
SRC = 'banc:888 (Site BANC888) "quoted" \\ backslash'


def edges(rows):
    return pd.DataFrame(rows, columns=["pre", "post", "weight"])


GOOD = edges([("VFB_0000000b", "VFB_0000000a", 3), ("VFB_0000000a", "VFB_0000000b", 2),
              ("VFB_0000000a", "VFB_0000000a", 7),            # autapse
              ("VFB_jrmc3let", "VFB_fw116009", 123456)])


@pytest.fixture
def good_owl(tmp_path):
    path = tmp_path / "good.owl"
    assert write_n2n_owl(str(path), GOOD, IRI, VER, SRC) == (4, 4)
    return path


def test_written_file_validates(good_owl):
    s = validate_n2n_owl(str(good_owl), site="BANC888", threshold=1, expected_edges=4)
    assert s["edges"] == 4 and s["individuals"] == 4 and s["site"] == "BANC888"
    assert s["dc_source"] == SRC.replace("\\", "\\\\").replace('"', '\\"')


def test_edges_sorted_and_roundtrip(good_owl):
    got = list(iter_edges(str(good_owl)))
    assert got == sorted(got) and sorted(got) == sorted(map(tuple, GOOD.values.tolist()))


def test_deterministic(tmp_path):
    a, b = tmp_path / "a.owl", tmp_path / "b.owl"
    write_n2n_owl(str(a), GOOD, IRI, VER, SRC)
    write_n2n_owl(str(b), GOOD.sample(frac=1, random_state=1), IRI, VER, SRC)
    assert a.read_bytes() == b.read_bytes()


def test_gz_validates(good_owl, tmp_path):
    gz = tmp_path / "good.owl.gz"
    with open(good_owl, "rb") as src, gzip.open(gz, "wb") as dst:
        shutil.copyfileobj(src, dst)
    assert validate_n2n_owl(str(gz), site="BANC888")["edges"] == 4


def test_literal_escaping():
    assert ofn_literal('a "b" \\c') == '"a \\"b\\" \\\\c"'


@pytest.mark.parametrize("rows,msg", [
    ([("VFB_", "VFB_0000000a", 3)], "not a VFB individual id"),        # FlyWire's empty id
    ([("VFB_0000000a", None, 3)], "not a VFB individual id"),
    ([("VFB_0000000a", "VFB_0000000b", 0)], "positive integer"),
    ([("VFB_0000000a", "VFB_0000000b", 2.5)], "positive integer"),
    ([("VFB_0000000a", "VFB_0000000b", 2), ("VFB_0000000a", "VFB_0000000b", 5)], "repeated edge"),
])
def test_writer_refuses_bad_edges(tmp_path, rows, msg):
    with pytest.raises(ValueError, match=msg):
        write_n2n_owl(str(tmp_path / "x.owl"), edges(rows), IRI, VER, SRC)
    assert not (tmp_path / "x.owl").exists()                           # nothing half-written


def test_threshold_and_expected_count(good_owl):
    with pytest.raises(ValidationError, match="not above the threshold 2"):
        validate_n2n_owl(str(good_owl), threshold=2)
    with pytest.raises(ValidationError, match="4 edges written, 5 expected"):
        validate_n2n_owl(str(good_owl), expected_edges=5)
    with pytest.raises(ValidationError, match="expected male-cns_v1_0"):
        validate_n2n_owl(str(good_owl), site="male-cns_v1_0")


def _mutate(good_owl, tmp_path, old, new, count=1):
    text = good_owl.read_text()
    assert old in text
    path = tmp_path / "bad.owl"
    path.write_text(text.replace(old, new, count))
    return str(path)


A = "http://virtualflybrain.org/reports/VFB_0000000a"


@pytest.mark.parametrize("old,new,msg", [
    ("<%s> <" % A, "<http://virtualflybrain.org/reports/VFB_> <", "edge end is not a VFB id"),
    ('"7"^^xsd:integer', '"7"^^xsd:string', "not a weighted RO_0002120 assertion"),
    ("<http://purl.obolibrary.org/obo/RO_0002120> <%s> <%s>" % (A, A),
     "<http://purl.obolibrary.org/obo/RO_0002131> <%s> <%s>" % (A, A), "not a weighted RO_0002120"),
    ("Declaration(NamedIndividual(<%s>))\n" % A, "", "used but not declared"),
    ("\n<%s>\n" % VER, "\n", "no version IRI"),
    ("Annotation(<http://purl.org/dc/terms/source>", "Annotation(<http://purl.org/dc/terms/title>",
     "unexpected ontology annotation"),
    ("\n)\n", "\n", "never closed"),
    ("\n)\n", "\n)\nDeclaration(NamedIndividual(<%s>))\n" % A, "after the ontology was closed"),
    ("Declaration(ObjectProperty", "SubClassOf(<http://x> <http://y>)\nDeclaration(ObjectProperty",
     "unexpected line"),
])
def test_validator_rejects(good_owl, tmp_path, old, new, msg):
    with pytest.raises(ValidationError, match=msg):
        validate_n2n_owl(_mutate(good_owl, tmp_path, old, new))


def test_validator_rejects_duplicate_edge(good_owl, tmp_path):
    line = next(l for l in good_owl.read_text().splitlines() if l.startswith("ObjectPropertyAssertion"))
    with pytest.raises(ValidationError, match="repeated edge"):
        validate_n2n_owl(_mutate(good_owl, tmp_path, line + "\n", line + "\n" + line + "\n"))


def test_diff_report(tmp_path):
    old, new = tmp_path / "old.owl", tmp_path / "new.owl"
    write_n2n_owl(str(old), GOOD, IRI, VER, SRC)
    changed = GOOD.copy()
    changed.loc[0, "weight"] = 9                                       # re-weighted
    changed = pd.concat([changed.iloc[:3], edges([("VFB_0000000c", "VFB_0000000a", 2)])])
    write_n2n_owl(str(new), changed, IRI, VER, SRC)
    assert diff_report(str(new), str(old)) == dict(kept=2, reweighted=1, added=1, removed=1)


class _FakeCI:
    """Just enough of ConnectomicsImport for vfb_edges: the Site's xref mapping."""
    def __init__(self, mapping):
        wrapper = type("W", (), {"xref_2_vfb_id": lambda self, db: mapping})()
        self.vc = type("VC", (), {"neo_query_wrapper": wrapper})()


def test_vfb_edges_maps_and_ignores_accessionless_xrefs():
    from vfb_connectomics_import.connectivity.cli._common import vfb_edges
    ci = _FakeCI({"11": [{"vfb_id": "VFB_0000000a"}], "12": [{"vfb_id": "VFB_0000000b"}],
                  None: [{"vfb_id": "VFB_0000000c"}, {"vfb_id": "VFB_0000000d"}]})
    out = vfb_edges(ci, "site", pd.DataFrame({"source": [11], "target": [12], "weight": [4]}))
    assert out.values.tolist() == [["VFB_0000000a", "VFB_0000000b", 4]]


@pytest.mark.parametrize("mapping", [
    {"11": [{"vfb_id": "VFB_0000000a"}]},                                       # 12 unmapped
    {"11": [{"vfb_id": "VFB_0000000a"}],
     "12": [{"vfb_id": "VFB_0000000b"}, {"vfb_id": "VFB_0000000e"}]},           # 12 ambiguous
])
def test_vfb_edges_stops_on_unmapped_or_ambiguous(mapping):
    from vfb_connectomics_import.connectivity.cli._common import vfb_edges
    with pytest.raises(SystemExit):
        vfb_edges(_FakeCI(mapping), "site",
                  pd.DataFrame({"source": [11], "target": [12], "weight": [4]}))
