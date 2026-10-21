"""Shared plumbing for the connectivity CLIs.

Every build is driven by one VFB Site short_form (`--site`), the canonical version
token. The source release (neuprint dataset, CAVE materialization, CATMAID server)
is derived from that Site's link_base (see ../provenance.py) and the neurons are the
Site's cross-referenced individuals.

`--output X.owl` writes the OWL directly (../owl_writer.py), stamped with the
release, and validates the complete file (../validate.py). `--output X.tsv` writes
the old ROBOT template plus `<template>.provenance` instead — kept only for the
release pipeline's CATMAID step until it moves to .owl output.
"""
import argparse
import os
import sys

import pandas as pd

from vfb_connectomics_import.connectivity.provenance import write_provenance


def base_parser(description, default_site=None, site_required=None):
    """site_required defaults to True unless a default Site is given; a CLI that
    still accepts a legacy spelling of the Site passes False and checks itself."""
    if site_required is None:
        site_required = default_site is None
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--site", "-s", default=default_site, required=site_required,
                   help="VFB Site short_form of the release to build (e.g. BANC888, "
                        "male-cns_v1_0, flywire783, catmaid_l1em). The source release "
                        "is derived from it." + (" Default: %s." % default_site if default_site else ""))
    p.add_argument("--dataset", "-d", default=None,
                   help="Optionally restrict to neurons of this VFB DataSet as well as the Site")
    p.add_argument("--threshold", "-t", type=int, default=1,
                   help="Keep connections with MORE than this many synapses "
                        "(default: 1, i.e. >= 2, the same for every connectome)")
    p.add_argument("--output", "-o", required=site_required,
                   help="Output path: X.owl writes and validates the OWL directly; "
                        "X.tsv writes the legacy ROBOT template + .provenance")
    p.add_argument("--ontology-iri", default=None,
                   help="Ontology IRI for .owl output (default: "
                        "http://virtualflybrain.org/data/VFB/OWL/<output file name>)")
    p.add_argument("--previous", default=None,
                   help="Previous artifact (.owl or .owl.gz) to diff the new one against "
                        "(reported, not failed)")
    p.add_argument("--no-robot", action="store_true",
                   help="Skip the ROBOT sample parse + SPARQL shape checks")
    return p


def accessions_for_site(ci, site, dataset=None):
    accessions = ci.get_accessions_from_vfb(dataset=dataset, db=site)
    if not accessions:
        print(f"ERROR: No neuron accessions found for Site '{site}'"
              + (f" and dataset '{dataset}'" if dataset else "") + ".")
        print("Check that the Site short_form is the KB spelling (e.g. male-cns_v1_0, not "
              "male_cns_v1_0) and that its neurons carry database_cross_references to it.")
        sys.exit(1)
    return accessions


def vfb_edges(ci, site, conn_df):
    """conn_df (source, target, weight; source accessions) -> (pre, post, weight) as
    VFB ids, via the Site's cross-references. Stops if any edge end does not map, or
    maps to more than one individual."""
    import pandas as pd
    # cross-references with no accession cannot be an edge end; leave them out
    mapping = {k: v for k, v in ci.vc.neo_query_wrapper.xref_2_vfb_id(db=site).items()
               if k is not None}
    ambiguous = sorted(k for k, v in mapping.items() if len({m["vfb_id"] for m in v}) > 1)
    ids = {k: v[0]["vfb_id"] for k, v in mapping.items()}
    pre = conn_df["source"].astype(str).map(ids)
    post = conn_df["target"].astype(str).map(ids)
    unmapped = int(pre.isna().sum() + post.isna().sum())
    if unmapped:
        sys.exit(f"ERROR: {unmapped} edge ends did not map to a VFB id via Site {site}")
    used = set(conn_df["source"].astype(str)) | set(conn_df["target"].astype(str))
    if any(a in used for a in ambiguous):
        sys.exit(f"ERROR: accessions mapping to more than one VFB individual via Site {site}: "
                 f"{[a for a in ambiguous if a in used][:5]}")
    return pd.DataFrame({"pre": pre.values, "post": post.values,
                         "weight": conn_df["weight"].astype("int64").values})


def write_output(ci, site, conn_df, args, prov):
    """--output .owl: write the OWL directly and validate it in full; .tsv: the
    legacy ROBOT template + .provenance."""
    if not args.output.endswith(".owl"):
        return write_template(ci, site, conn_df, args.output, prov)
    from vfb_connectomics_import.connectivity.owl_writer import OWL_BASE, write_n2n_owl
    from vfb_connectomics_import.connectivity.validate import ValidationError, check
    edges = vfb_edges(ci, site, conn_df)
    iri = args.ontology_iri or OWL_BASE + os.path.basename(args.output)
    n_ind, n_edges = write_n2n_owl(args.output, edges, iri, prov.version_iri, prov.dc_source)
    print(f"OWL written to: {args.output} ({n_edges} edges, {n_ind} individuals; "
          f"{prov.dc_source})")
    try:
        check(args.output, site=site, threshold=args.threshold, expected_edges=n_edges,
              previous=args.previous, use_robot=not args.no_robot)
    except ValidationError as e:
        sys.exit(f"ERROR: {e}")


def write_template(ci, site, conn_df, output, prov):
    """Write the ROBOT template and its .provenance; stop if any edge end did not
    map to a VFB id via the Site."""
    print("Generating ROBOT template...")
    template_df = ci.generate_n_n_template(db=site, conn_df=conn_df)
    unmapped = template_df["ID"].isna().sum() + template_df["FACT"].isna().sum()
    if unmapped:
        sys.exit(f"ERROR: {unmapped} edge ends did not map to a VFB id via Site {site}")
    template_df.to_csv(output, sep="\t", index=False)
    prov_path = write_provenance(output, prov)
    print(f"ROBOT template written to: {output} ({len(template_df) - 1} edges)")
    print(f"Provenance written to: {prov_path} ({prov.dc_source})")
    print("Legacy template output: build the OWL with robot template + annotate "
          "--version-iri/--annotation dc:source from that file, or use --output X.owl.")


def neuprint_token(path=None):
    """Token from $NEUPRINT_TOKEN, else the given file, else ~/neuprint_token.txt.
    Never from the command line or the source code."""
    if os.environ.get("NEUPRINT_TOKEN"):
        return os.environ["NEUPRINT_TOKEN"].strip()
    path = os.path.expanduser(path or "~/neuprint_token.txt")
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    sys.exit("No neuprint token: set NEUPRINT_TOKEN or put it in ~/neuprint_token.txt")


def load_pair_weights_file(source, accessions, pre, post, weight, threshold):
    """(source, target, weight) between VFB neurons from a bulk connectivity file
    (feather or parquet, local path or URL), summing rows per pair — the file may
    be split by neuropil — and keeping weight > threshold. pre/post/weight name the
    file's columns. Read one record batch at a time, so a GB-scale file needs
    little memory once cut down to VFB neurons."""
    import fsspec
    import pyarrow as pa
    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq
    ids = pd.Series(sorted(int(a) for a in accessions), dtype="int64")
    cols = [pre, post, weight]
    parts = []
    with fsspec.open(source, "rb") as fh:
        if str(source).endswith(".parquet"):
            pf = pq.ParquetFile(fh)
            batches = (pf.read_row_group(i, columns=cols) for i in range(pf.num_row_groups))
        else:
            reader = ipc.open_file(pa.PythonFile(fh, mode="r"))
            batches = (reader.get_batch(i).select(cols) for i in range(reader.num_record_batches))
        for b in batches:
            df = b.to_pandas()
            df = df[df[pre].isin(ids) & df[post].isin(ids)]
            parts.append(df.groupby([pre, post])[weight].sum())
    if not parts:
        return pd.DataFrame(columns=["source", "target", "weight"])
    w = pd.concat(parts).groupby(level=[0, 1]).sum()
    w = w[w > threshold]
    return w.rename("weight").reset_index().rename(columns={pre: "source", post: "target"})

