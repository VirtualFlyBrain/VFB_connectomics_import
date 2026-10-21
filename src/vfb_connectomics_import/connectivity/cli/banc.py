"""Generate the ROBOT template TSV for BANC neuron-to-neuron connectivity.

    python -m vfb_connectomics_import.connectivity.cli.banc --site BANC888 \\
        --output connectome_BANC_n2n.owl

The release (e.g. 888) is taken from the Site, and selects the bucket folder.
Edges come from BANC's per-neuropil connection counts for that release
(synapses_v1_human_readable_sizethresh3_connectioncountsperneuropil.parquet:
the v1 synapse set, size > 3, with NO connection-count threshold), summed over
neuropils per (pre, post) pair, restricted to the Site's neurons, and kept where
weight > --threshold. The default threshold of 1 keeps connections of >= 2
synapses, the same cut as the neuprint, FlyWire and CATMAID imports. (BANC's own
*_countthresh3.parquet is the same data cut at >= 3; the pair sums here reproduce
it exactly at that threshold.)

The file is ~1.1 GB / ~177M rows, so it is streamed one row group at a time and
only rows between VFB neurons are kept. It is read over HTTPS from the public
bucket (or from --connectivity-file if given), so gsutil is not needed.

See docs/BANC_connectivity_notes.md for the full procedure.
"""
import fsspec
import pandas as pd
import pyarrow.parquet as pq

from vfb_connectomics_import.connectivity.cli._common import (
    accessions_for_site, base_parser, write_output)
from vfb_connectomics_import.connectivity.core import ConnectomicsImport

BUCKET = "https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome"
PER_NEUROPIL = "synapses_v1_human_readable_sizethresh3_connectioncountsperneuropil.parquet"


def load_pair_weights(source, accessions):
    """Synapses per (pre, post) pair between VFB neurons, summed over neuropils.

    Streams the parquet one row group at a time; each group is cut down to rows
    whose pre AND post are VFB neurons before summing, so memory stays small.
    Root 0 (unsegmented) is never a VFB accession, so it drops out here."""
    ids = pd.Series(sorted(int(a) for a in accessions), dtype="int64")
    parts = []
    with fsspec.open(source, "rb") as fh:
        pf = pq.ParquetFile(fh)
        for i in range(pf.num_row_groups):
            rg = pf.read_row_group(i, columns=["pre_root_id", "post_root_id", "num_synapses"]
                                   ).to_pandas()
            rg = rg[rg["pre_root_id"].isin(ids) & rg["post_root_id"].isin(ids)]
            parts.append(rg.groupby(["pre_root_id", "post_root_id"])["num_synapses"].sum())
            if (i + 1) % 20 == 0 or i + 1 == pf.num_row_groups:
                print(f"  row groups read: {i + 1}/{pf.num_row_groups}")
    if not parts:
        return pd.DataFrame(columns=["source", "target", "weight"])
    weights = pd.concat(parts).groupby(level=[0, 1]).sum()
    return weights.rename("weight").reset_index().rename(
        columns={"pre_root_id": "source", "post_root_id": "target"})


def main():
    parser = base_parser("Generate ROBOT template TSV for BANC connectivity data",
                         default_site="BANC888")
    parser.add_argument("--connectivity-file", type=str, default=None,
                        help="Local path or URL of the per-neuropil connection counts parquet "
                             "(default: the Site's release folder in the public BANC bucket)")
    # BANC's OWL has always had this ontology IRI; keep it for continuity
    parser.set_defaults(ontology_iri="http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl")
    args = parser.parse_args()

    ci = ConnectomicsImport()
    prov = ci.site_provenance(args.site)
    if prov.kind != "codex" or not prov.source.startswith("banc:"):
        parser.error(f"Site {args.site} is not a BANC release ({prov.source})")
    source = args.connectivity_file or \
        f"{BUCKET}/neuron_connectivity/v{prov.materialization}/{PER_NEUROPIL}"
    print(f"Site {args.site} -> BANC v{prov.materialization}")

    accessions = accessions_for_site(ci, args.site, args.dataset)
    print(f"Summing per-neuropil connection counts from: {source}")
    conn_df = load_pair_weights(source, accessions)
    print(f"{len(conn_df)} connected pairs between VFB neurons "
          f"({int(conn_df['weight'].sum()) if len(conn_df) else 0} synapses)")
    conn_df = conn_df[conn_df["weight"] > args.threshold]
    print(f"After threshold > {args.threshold}: {len(conn_df)} edges "
          f"({int(conn_df['weight'].sum()) if len(conn_df) else 0} synapses)")
    write_output(ci, args.site, conn_df, args, prov)


if __name__ == "__main__":
    main()
