#!/usr/bin/env python3
"""Concatenate ROBOT-template chunk OWL (OFN) files into one ontology.

Used by chunked_n2n_build.sh. Each chunk emits the identical Prefix block +
`Ontology(<iri>` header + body of Declaration/ObjectPropertyAssertion lines +
closing `)`. We keep ONE header (from the first chunk, up to and including the
`Ontology(` line), append every chunk's body, and close once. Duplicate
declarations across chunks are idempotent in OWL, so no dedup is needed.

This avoids `robot merge`, which would reload all axioms into a single OWLAPI
ontology and hit the same out-of-memory wall the chunking was meant to dodge.

Usage: concat_ofn_chunks.py <workdir-with-out_*.owl> <final.owl>
"""
import sys, glob, os

work, final = sys.argv[1], sys.argv[2]
chunks = sorted(glob.glob(os.path.join(work, "out_*.owl")))
if not chunks:
    sys.exit("no chunk files (out_*.owl) found in " + work)

written = 0
with open(final, "w") as fo:
    # header: first chunk up to and including the Ontology( line
    with open(chunks[0]) as f:
        for line in f:
            fo.write(line)
            if line.startswith("Ontology("):
                break
    # bodies: each chunk's lines after Ontology( and before the final )
    for path in chunks:
        with open(path) as f:
            lines = f.readlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("Ontology("))
        body = lines[start + 1:]
        while body and body[-1].strip() == "":
            body.pop()
        if body and body[-1].strip() == ")":
            body.pop()
        fo.writelines(body)
        written += sum(1 for l in body if l.startswith("ObjectPropertyAssertion"))
    fo.write(")\n")

print(f"    merged {len(chunks)} chunks, {written} ObjectPropertyAssertion axioms")
