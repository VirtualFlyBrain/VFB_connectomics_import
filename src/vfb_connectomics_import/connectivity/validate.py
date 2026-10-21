"""Validate a neuron-to-neuron connectivity OWL (functional syntax), in full.

    python -m vfb_connectomics_import.connectivity.validate connectome_X.owl[.gz] \\
        --site <Site> [--threshold 1] [--previous old.owl[.gz]] [--no-robot]

Three layers, run by every build and usable on any connectome_* file:

1. validate_n2n_owl — a streaming pass over the COMPLETE file (GB-scale is fine).
   Every line must be one of the forms an n2n file contains (prefix, the one ontology
   header with its version IRI and dc:source, a declaration, a weighted RO_0002120
   assertion, a comment or blank) and the file must close once. On top of the syntax:
   the version IRI must be <base>/<Site>_import.owl (and the expected Site, if given),
   every individual used must be declared and a well-formed VFB id (an empty
   `.../reports/VFB_` — as the old FlyWire build had — fails), weights must be
   integers > threshold, and no (pre, post) pair may repeat.
2. robot_sample_check — OWLAPI (ROBOT) parses a self-contained sample of the file
   and the SPARQL shape checks in sparql/ run on it. A full OWLAPI parse of the large
   files needs tens of GB of heap; the full-file pass above covers what it would.
3. diff_report — edges kept / added / removed / re-weighted against the previous
   artifact. Reported, not failed: a new release legitimately changes a lot.
"""
import argparse
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile

from vfb_connectomics_import.connectivity.owl_writer import (
    DC_SOURCE, OWL_BASE, RO_SYNAPSED_TO, VFB, WEIGHT)

SPARQL_DIR = os.path.join(os.path.dirname(__file__), "sparql")

_ASSERTION = re.compile(
    r'ObjectPropertyAssertion\(Annotation\(<' + re.escape(WEIGHT) + r'> "(-?\d+)"\^\^xsd:integer\) '
    r'<' + re.escape(RO_SYNAPSED_TO) + r'> <' + re.escape(VFB) + r'([^>]*)> <' + re.escape(VFB) + r'([^>]*)>\)')
_DECL_IND = re.compile(r'Declaration\(NamedIndividual\(<' + re.escape(VFB) + r'([^>]*)>\)\)')
_DECL_OTHER = {"Declaration(ObjectProperty(<%s>))" % RO_SYNAPSED_TO,
               "Declaration(AnnotationProperty(<%s>))" % WEIGHT,
               "Declaration(AnnotationProperty(<%s>))" % DC_SOURCE}
_ONTOLOGY = re.compile(r"Ontology\(<([^>]+)>\s*(?:<([^>]+)>)?$")
_IRI_LINE = re.compile(r"<([^>]+)>$")
_DC = re.compile(r'Annotation\(<' + re.escape(DC_SOURCE) + r'> "((?:[^"\\]|\\.)*)"\)$')
_VFB_ID = re.compile(r"VFB_[0-9a-z]+")
_VERSION = re.compile(re.escape(OWL_BASE) + r"([A-Za-z0-9_.-]+?)_import\.owl")


class ValidationError(ValueError):
    pass


def _open(path):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)


def iter_edges(path):
    """(pre, post, weight) of every weighted RO_0002120 assertion in an n2n OFN file."""
    with _open(path) as fh:
        for line in fh:
            if line.startswith("ObjectPropertyAssertion("):
                m = _ASSERTION.fullmatch(line.rstrip("\n"))
                if m:
                    yield m.group(2), m.group(3), int(m.group(1))


def validate_n2n_owl(path, site=None, threshold=1, expected_edges=None, max_errors=20):
    """Validate the whole file; return a summary dict, or raise ValidationError
    listing the first problems found."""
    errors = []

    def err(lineno, msg):
        if len(errors) < max_errors:
            errors.append("line %d: %s" % (lineno, msg))

    ontology = version = dc_source = None
    header_open = False          # between Ontology( and the first axiom/declaration
    closed_at = None
    declared, used = set(), set()
    pairs = set()
    n_edges = 0
    with _open(path) as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if closed_at is not None and line.strip():
                err(lineno, "content after the ontology was closed on line %d" % closed_at)
                continue
            if not line.strip() or line.startswith("#"):
                continue
            if line.startswith("Prefix("):
                if ontology is not None:
                    err(lineno, "Prefix after the ontology header")
                continue
            if line.startswith("Ontology("):
                m = _ONTOLOGY.fullmatch(line)
                if ontology is not None:
                    err(lineno, "second Ontology header")
                elif not m:
                    err(lineno, "malformed Ontology header: %s" % line[:120])
                else:
                    ontology, version = m.group(1), m.group(2)
                    header_open = True
                continue
            if header_open and version is None and _IRI_LINE.fullmatch(line):
                version = _IRI_LINE.fullmatch(line).group(1)
                continue
            if header_open and line.startswith("Annotation("):
                m = _DC.fullmatch(line)
                if m and dc_source is None:
                    dc_source = m.group(1)
                else:
                    err(lineno, "unexpected ontology annotation: %s" % line[:120])
                continue
            if line.startswith("Declaration("):
                header_open = False
                m = _DECL_IND.fullmatch(line)
                if m:
                    vid = m.group(1)
                    if not _VFB_ID.fullmatch(vid):
                        err(lineno, "declared individual is not a VFB id: %r" % (VFB + vid))
                    declared.add(vid)
                elif line not in _DECL_OTHER:
                    err(lineno, "unexpected declaration: %s" % line[:120])
                continue
            if line.startswith("ObjectPropertyAssertion("):
                header_open = False
                m = _ASSERTION.fullmatch(line)
                if not m:
                    err(lineno, "not a weighted RO_0002120 assertion between VFB individuals: %s"
                        % line[:160])
                    continue
                w, pre, post = int(m.group(1)), m.group(2), m.group(3)
                for vid in (pre, post):
                    if not _VFB_ID.fullmatch(vid):
                        err(lineno, "edge end is not a VFB id: %r" % (VFB + vid))
                    used.add(vid)
                if w <= threshold:
                    err(lineno, "weight %d is not above the threshold %d" % (w, threshold))
                key = hash((pre, post))
                if key in pairs:
                    err(lineno, "repeated edge %s -> %s" % (pre, post))
                pairs.add(key)
                n_edges += 1
                continue
            if line == ")":
                closed_at = lineno
                continue
            err(lineno, "unexpected line: %s" % line[:160])

    if ontology is None:
        errors.append("no Ontology header")
    if closed_at is None:
        errors.append("the ontology is never closed (truncated file?)")
    m = _VERSION.fullmatch(version or "")
    stamped = m.group(1) if m else None
    if stamped is None:
        errors.append("no version IRI of the form %s<Site>_import.owl (found %r)" % (OWL_BASE, version))
    elif site and stamped != site:
        errors.append("version IRI names Site %s, expected %s" % (stamped, site))
    if dc_source is None:
        errors.append("no dc:source annotation")
    undeclared = used - declared
    if undeclared:
        errors.append("%d individuals used but not declared, e.g. %s"
                      % (len(undeclared), sorted(undeclared)[:3]))
    if expected_edges is not None and n_edges != expected_edges:
        errors.append("%d edges written, %d expected" % (n_edges, expected_edges))
    if errors:
        raise ValidationError("%s failed validation:\n  " % path + "\n  ".join(errors))
    return {"edges": n_edges, "individuals": len(used), "declared": len(declared),
            "ontology": ontology, "site": stamped, "dc_source": dc_source}


def robot_sample_check(path, n_edges=5000, robot=None):
    """OWLAPI-parse a self-contained sample (the header, the first n_edges
    assertions and the declarations they need) and run the SPARQL shape checks.
    Returns "passed", or "skipped: ..." when ROBOT is not installed; raises
    ValidationError on a parse or shape failure."""
    robot = robot or shutil.which("robot")
    if not robot:
        return "skipped: robot not on PATH"
    work = tempfile.mkdtemp(prefix="n2n_sample_")
    try:
        header, edges = [], []
        with _open(path) as fh:
            for line in fh:
                if line.startswith("ObjectPropertyAssertion("):
                    edges.append(line)
                    if len(edges) >= n_edges:
                        break
                elif line.startswith("Declaration(NamedIndividual("):
                    continue
                elif line.strip() != ")":
                    header.append(line)
        needed = sorted({vid for line in edges for vid in re.findall(re.escape(VFB) + r"([^>]*)>", line)})
        sample = os.path.join(work, "sample.ofn")
        with open(sample, "w") as out:
            out.writelines(header)
            out.writelines("Declaration(NamedIndividual(<%s%s>))\n" % (VFB, v) for v in needed)
            out.writelines(edges)
            out.write(")\n")
        ttl = os.path.join(work, "sample.ttl")
        queries = sorted(os.path.join(SPARQL_DIR, q) for q in os.listdir(SPARQL_DIR)
                         if q.endswith("-violation.sparql"))
        for cmd in ([robot, "convert", "-i", sample, "-f", "ttl", "-o", ttl],
                    [robot, "verify", "-i", ttl, "--queries", *queries, "-O", work]):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise ValidationError("ROBOT %s failed on a sample of %s:\n%s"
                                      % (cmd[1], path, (r.stdout + r.stderr)[-2000:]))
        return "passed (%d edges, %d SPARQL checks)" % (len(edges), len(queries))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _sorted_edges(path, work, name):
    raw = os.path.join(work, name + ".raw")
    with open(raw, "w") as out:
        out.writelines("%s\t%s\t%d\n" % e for e in iter_edges(path))
    srt = os.path.join(work, name + ".tsv")
    subprocess.run(["sort", "-S", "1G", "-o", srt, raw], check=True, env={**os.environ, "LC_ALL": "C"})
    os.remove(raw)
    return srt


def diff_report(new_path, previous_path):
    """Edges kept, added, removed and re-weighted between two n2n files, by a
    sorted merge so neither file has to fit in memory."""
    work = tempfile.mkdtemp(prefix="n2n_diff_")
    try:
        a, b = _sorted_edges(previous_path, work, "old"), _sorted_edges(new_path, work, "new")
        stats = dict(kept=0, reweighted=0, added=0, removed=0)

        def rows(p):
            with open(p) as fh:
                for line in fh:
                    s, t, w = line.rstrip("\n").split("\t")
                    yield (s, t), int(w)
            yield None, None

        ia, ib = rows(a), rows(b)
        ka, wa = next(ia)
        kb, wb = next(ib)
        while ka is not None or kb is not None:
            if kb is None or (ka is not None and ka < kb):
                stats["removed"] += 1
                ka, wa = next(ia)
            elif ka is None or kb < ka:
                stats["added"] += 1
                kb, wb = next(ib)
            else:
                stats["kept" if wa == wb else "reweighted"] += 1
                ka, wa = next(ia)
                kb, wb = next(ib)
        return stats
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check(path, site=None, threshold=1, expected_edges=None, previous=None, use_robot=True):
    """All three layers; prints a report and returns the validation summary."""
    summary = validate_n2n_owl(path, site=site, threshold=threshold, expected_edges=expected_edges)
    print("validated %s: %d edges, %d individuals, Site %s"
          % (path, summary["edges"], summary["individuals"], summary["site"]))
    if use_robot:
        print("ROBOT sample check:", robot_sample_check(path))
    if previous:
        d = diff_report(path, previous)
        print("against %s: kept %d, re-weighted %d, added %d, removed %d"
              % (previous, d["kept"], d["reweighted"], d["added"], d["removed"]))
    return summary


def main():
    p = argparse.ArgumentParser(description="Validate a neuron-to-neuron connectivity OWL")
    p.add_argument("owl", help="connectome_*.owl or .owl.gz")
    p.add_argument("--site", help="expected Site in the version IRI")
    p.add_argument("--threshold", type=int, default=1,
                   help="weights must be above this (default 1, i.e. >= 2)")
    p.add_argument("--previous", help="previous artifact to diff against (report only)")
    p.add_argument("--no-robot", action="store_true", help="skip the ROBOT sample check")
    a = p.parse_args()
    try:
        check(a.owl, site=a.site, threshold=a.threshold, previous=a.previous,
              use_robot=not a.no_robot)
    except ValidationError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
