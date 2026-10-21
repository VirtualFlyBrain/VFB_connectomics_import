"""Write a neuron-to-neuron connectivity OWL (functional syntax) directly.

Replaces `robot template` + chunked_n2n_build.sh for the n2n builds: the output is
the same ontology ROBOT produced from the ROBOT template (tests/test_robot_equivalence.py
checks that, triple for triple), written in seconds instead of ~100 s per 2M rows and
without a multi-GB Java heap:

    Prefix(...)
    Ontology(<ontology IRI>
    <version IRI .../<Site>_import.owl>
    Annotation(<http://purl.org/dc/terms/source> "<source>")
    Declaration(ObjectProperty(<RO_0002120>))
    Declaration(AnnotationProperty(<n2o weight>))
    Declaration(AnnotationProperty(<dc:source>))
    Declaration(NamedIndividual(<VFB individual>))            # one per neuron, sorted
    ObjectPropertyAssertion(Annotation(<n2o weight> "N"^^xsd:integer) <RO_0002120> <pre> <post>)
    )

Edges are sorted by (pre, post), so a rebuild from the same data is byte-identical.
Every written file is checked by validate.py.
"""
import re

RO_SYNAPSED_TO = "http://purl.obolibrary.org/obo/RO_0002120"
WEIGHT = "http://neo2owl/custom/weight"          # the n2o: prefix every connectome_* file uses
DC_SOURCE = "http://purl.org/dc/terms/source"
VFB = "http://virtualflybrain.org/reports/"
OWL_BASE = "http://virtualflybrain.org/data/VFB/OWL/"
VFB_ID = re.compile(r"VFB_[0-9a-z]+")

PREFIXES = (
    "Prefix(owl:=<http://www.w3.org/2002/07/owl#>)",
    "Prefix(rdf:=<http://www.w3.org/1999/02/22-rdf-syntax-ns#>)",
    "Prefix(xml:=<http://www.w3.org/XML/1998/namespace>)",
    "Prefix(xsd:=<http://www.w3.org/2001/XMLSchema#>)",
    "Prefix(rdfs:=<http://www.w3.org/2000/01/rdf-schema#>)",
)


def ofn_literal(text):
    """A quoted OWL functional-syntax string literal."""
    return '"%s"' % str(text).replace("\\", "\\\\").replace('"', '\\"')


def write_n2n_owl(path, edges, ontology_iri, version_iri, dc_source):
    """Write `edges` — a DataFrame with columns pre, post (VFB ids) and weight — to `path`.

    Raises ValueError, before writing anything, on a malformed VFB id, a weight that
    is not a positive integer, or a repeated (pre, post) pair. Checks and sorting are
    column-wise, so 15M edges need about as much memory as the DataFrame itself.
    Returns (number of individuals, number of edges)."""
    import pandas as pd
    df = pd.DataFrame({"pre": edges["pre"], "post": edges["post"], "weight": edges["weight"]})
    for col in ("pre", "post"):
        bad = ~df[col].astype(str).str.fullmatch(VFB_ID.pattern)
        if df[col].isna().any() or bad.any():
            row = df[df[col].isna() | bad].iloc[0]
            raise ValueError("not a VFB individual id: %r (edge %r -> %r)" % (row[col], row.pre, row.post))
    w = pd.to_numeric(df["weight"], errors="coerce")
    bad = w.isna() | (w < 1) | (w != w.round())
    if bad.any():
        row = df[bad].iloc[0]
        raise ValueError("weight must be a positive integer: %r (edge %s -> %s)" % (row.weight, row.pre, row.post))
    df["weight"] = w.astype("int64")
    dup = df.duplicated(["pre", "post"])
    if dup.any():
        row = df[dup].iloc[0]
        raise ValueError("repeated edge %s -> %s" % (row.pre, row.post))
    df = df.sort_values(["pre", "post"], kind="mergesort")
    individuals = sorted(set(df["pre"]) | set(df["post"]))

    with open(path, "w") as fh:
        fh.write("\n".join(PREFIXES) + "\n\n\n")
        fh.write("Ontology(<%s>\n<%s>\n" % (ontology_iri, version_iri))
        fh.write("Annotation(<%s> %s)\n\n" % (DC_SOURCE, ofn_literal(dc_source)))
        fh.write("Declaration(ObjectProperty(<%s>))\n" % RO_SYNAPSED_TO)
        fh.write("Declaration(AnnotationProperty(<%s>))\n" % WEIGHT)
        fh.write("Declaration(AnnotationProperty(<%s>))\n" % DC_SOURCE)
        fh.writelines("Declaration(NamedIndividual(<%s%s>))\n" % (VFB, v) for v in individuals)
        fh.write("\n")
        head = 'ObjectPropertyAssertion(Annotation(<%s> "' % WEIGHT
        mid = '"^^xsd:integer) <%s> <%s' % (RO_SYNAPSED_TO, VFB)
        fh.writelines(head + str(wt) + mid + a + "> <" + VFB + b + ">)\n"
                      for a, b, wt in zip(df["pre"], df["post"], df["weight"]))
        fh.write(")\n")
    return len(individuals), len(df)
