#!/usr/bin/env python3
"""Concatenate ROBOT-template chunk OWL (OFN) files into one ontology.

Used by chunked_n2n_build.sh. Each chunk emits the identical Prefix block +
`Ontology(<iri>` header — then, if the build stamped them, a version-IRI line and
ontology Annotation(...) lines (dc:source) — + body of Declaration/ObjectPropertyAssertion
lines + closing `)`. We keep ONE preamble (the first chunk's, up to its first axiom, so the
version IRI and annotations appear once and before any axiom, as OWL requires), append
every chunk's axioms, and close once. Duplicate declarations across chunks are idempotent
in OWL, so no dedup is needed.

This avoids `robot merge`, which would reload all axioms into a single OWLAPI
ontology and hit the same out-of-memory wall the chunking was meant to dodge.

Usage: concat_ofn_chunks.py <workdir-with-out_*.owl> <final.owl>
"""
import sys, glob, os

AXIOM_STARTS = ("Declaration(", "ObjectPropertyAssertion(")


def first_axiom(lines, after):
    """Index of the first axiom line after the Ontology( line."""
    return next((i for i in range(after + 1, len(lines)) if lines[i].startswith(AXIOM_STARTS)),
                len(lines))

work, final = sys.argv[1], sys.argv[2]
chunks = sorted(glob.glob(os.path.join(work, "out_*.owl")))
if not chunks:
    sys.exit("no chunk files (out_*.owl) found in " + work)

written = 0
with open(final, "w") as fo:
    for n, path in enumerate(chunks):
        with open(path) as f:
            lines = f.readlines()
        onto = next(i for i, l in enumerate(lines) if l.startswith("Ontology("))
        start = first_axiom(lines, onto)
        if n == 0:
            # preamble: prefixes, Ontology( line, version IRI, ontology annotations
            fo.writelines(lines[:start])
        # body: each chunk's axioms, without the final )
        body = lines[start:]
        while body and body[-1].strip() == "":
            body.pop()
        if body and body[-1].strip() == ")":
            body.pop()
        fo.writelines(body)
        written += sum(1 for l in body if l.startswith("ObjectPropertyAssertion"))
    fo.write(")\n")

print(f"    merged {len(chunks)} chunks, {written} ObjectPropertyAssertion axioms")
