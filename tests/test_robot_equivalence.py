"""The direct writer produces the same ontology ROBOT did, and the ROBOT/SPARQL sample
check accepts it and rejects malformed files. Needs ROBOT on PATH (CI runs in the
ODK image); skipped otherwise."""
import shutil
import subprocess

import pandas as pd
import pytest

from vfb_connectomics_import.connectivity.owl_writer import write_n2n_owl
from vfb_connectomics_import.connectivity.validate import ValidationError, robot_sample_check

ROBOT = shutil.which("robot")
pytestmark = pytest.mark.skipif(ROBOT is None, reason="ROBOT not on PATH")

IRI = "http://virtualflybrain.org/data/VFB/OWL/connectome_test.owl"
VER = "http://virtualflybrain.org/data/VFB/OWL/male-cns_v1_0_import.owl"
SRC = "male-cns:v1.0 (Site male-cns_v1_0)"

# awkward but legal cases: autapse, 7-digit weight, every VFB id prefix in use
EDGES = pd.DataFrame([
    ("VFB_jrmc0018", "VFB_jrmc0021", 2), ("VFB_jrmc0021", "VFB_jrmc0018", 1234567),
    ("VFB_jrmc0018", "VFB_jrmc0018", 5), ("VFB_fw000001", "VFB_00102gvz", 17),
    ("VFB_00102gvz", "VFB_jrchjrch", 3), ("VFB_001091r2", "VFB_fw000001", 2),
] + [("VFB_jrcv%04d" % i, "VFB_jrcv%04d" % (i + 1), 2 + i % 50) for i in range(200)],
    columns=["pre", "post", "weight"])


def robot(*args, cwd):
    r = subprocess.run([ROBOT, *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_direct_writer_equals_robot_template(tmp_path):
    # the ROBOT template the legacy builds wrote (core.generate_n_n_template's layout)
    tpl = tmp_path / "t.tsv"
    lines = ["ID\tTYPE\tFACT\tWeight", "ID\tTYPE\tI 'synapsed to'\t>AT n2o:weight^^xsd:integer"]
    lines += ["VFB:%s\towl:NamedIndividual\tVFB:%s\t%d" % (a[4:], b[4:], w)
              for a, b, w in EDGES.itertuples(index=False)]
    tpl.write_text("\n".join(lines) + "\n")
    robot("template", "--input-iri", "http://purl.obolibrary.org/obo/ro.owl",
          "--add-prefix", "n2o: http://neo2owl/custom/",
          "--add-prefix", "VFB: http://virtualflybrain.org/reports/VFB_",
          "--template", str(tpl),
          "annotate", "--ontology-iri", IRI, "--version-iri", VER,
          "--annotation", "dc:source", SRC,
          "convert", "-f", "ofn", "--output", "robot.owl", cwd=tmp_path)
    write_n2n_owl(str(tmp_path / "direct.owl"), EDGES, IRI, VER, SRC)

    out = robot("diff", "--left", "robot.owl", "--right", "direct.owl", cwd=tmp_path)
    assert "Ontologies are identical" in out, out
    # robot diff compares axioms; compare the ontology header (IRI, version IRI,
    # dc:source) too, as everything the ontology node says about itself
    q = tmp_path / "head.sparql"
    q.write_text("SELECT ?p ?o WHERE { <%s> ?p ?o }" % IRI)
    for name in ("robot.owl", "direct.owl"):
        robot("query", "-i", name, "--query", str(q), name + ".tsv", cwd=tmp_path)
    head = [sorted((tmp_path / (n + ".tsv")).read_text().splitlines()[1:])
            for n in ("robot.owl", "direct.owl")]
    assert head[0] == head[1]
    assert any(VER in l for l in head[0]) and any(SRC in l for l in head[0])


def test_sample_check_passes_writer_output(tmp_path):
    path = tmp_path / "direct.owl"
    write_n2n_owl(str(path), EDGES, IRI, VER, SRC)
    assert robot_sample_check(str(path), n_edges=50).startswith("passed")


A = "http://virtualflybrain.org/reports/VFB_jrmc0018"


@pytest.mark.parametrize("old,new,query", [
    ("\n<%s>\n" % VER, "\n", "unstamped"),                                # no version IRI
    ("Annotation(<http://purl.org/dc/terms/source>", "Annotation(<http://purl.org/dc/terms/title>",
     "unstamped"),                                                        # no dc:source
    ('ObjectPropertyAssertion(Annotation(<http://neo2owl/custom/weight> "5"^^xsd:integer) ',
     "ObjectPropertyAssertion(", "missing-weight"),
    ('"5"^^xsd:integer', '"-5"^^xsd:integer', "bad-weight"),
    ("<http://purl.obolibrary.org/obo/RO_0002120> <%s> <%s>" % (A, A),
     "<http://purl.obolibrary.org/obo/RO_0002131> <%s> <%s>" % (A, A), "unexpected-relation"),
    ("<http://purl.obolibrary.org/obo/RO_0002120> <%s> <%s>" % (A, A),
     "<http://purl.obolibrary.org/obo/RO_0002120> <%s> <http://virtualflybrain.org/reports/VFB_>" % A,
     "nonvfb-individual"),
])
def test_sparql_checks_reject(tmp_path, old, new, query):
    path = tmp_path / "direct.owl"
    write_n2n_owl(str(path), EDGES, IRI, VER, SRC)
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))
    with pytest.raises(ValidationError, match="ROBOT verify failed"):
        robot_sample_check(str(path), n_edges=len(EDGES))
