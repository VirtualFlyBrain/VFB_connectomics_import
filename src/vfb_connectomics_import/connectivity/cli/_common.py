"""Shared plumbing for the connectivity CLIs.

Every build is driven by one VFB Site short_form (`--site`), the canonical version
token. The source release (neuprint dataset, CAVE materialization, CATMAID server)
is derived from that Site's link_base (see ../provenance.py), the neurons are the
Site's cross-referenced individuals, and the ROBOT template is written together with
a `<template>.provenance` file that chunked_n2n_build.sh stamps into the OWL header.
"""
import argparse
import os
import sys

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
                   help="Output TSV path for the ROBOT template")
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
    print("Build the OWL with data_owl/chunked_n2n_build.sh, which stamps it from that file.")


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
