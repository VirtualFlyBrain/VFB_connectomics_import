"""Generate the ROBOT template TSV for BANC neuron-to-neuron connectivity.

Edges come from BANC's per-neuropil connection counts for the given release
(synapses_v1_human_readable_sizethresh3_connectioncountsperneuropil.parquet:
the v1 synapse set, size > 3, with NO connection-count threshold), summed over
neuropils per (pre, post) pair, restricted to neurons VFB holds for that
release, and kept where weight > --threshold. The default threshold of 1 keeps
connections of >= 2 synapses, the same cut as the neuprint, FlyWire and CATMAID
imports. (BANC's own *_countthresh3.parquet is the same data cut at >= 3; the
pair sums here reproduce it exactly at that threshold.)

The file is ~1.1 GB / ~177M rows, so it is streamed one row group at a time and
only rows between VFB neurons are kept. It is read over HTTPS from the public
bucket (or from --connectivity-file if given), so gsutil is not needed.

See docs/BANC_connectivity_notes.md for the full procedure, including the
chunked OWL build and the version-stamped output name.
"""
import argparse
import sys

import fsspec
import pandas as pd
import pyarrow.parquet as pq

from vfb_connectomics_import.connectivity.core import ConnectomicsImport

BUCKET = "https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome"
PER_NEUROPIL = "synapses_v1_human_readable_sizethresh3_connectioncountsperneuropil.parquet"
# VFB DataSet for each BANC release (the Site is BANC<version>)
DATASETS = {"626": "Bates2025", "888": "Bates2026"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate ROBOT template TSV for BANC connectivity data"
    )
    parser.add_argument("--version", type=str, default="888",
                        help="BANC materialization (default: 888). Sets the VFB Site "
                             "(BANC<version>), the default dataset, and the bucket folder.")
    parser.add_argument("--dataset", type=str, default=None,
                        help="VFB dataset name (default: the one for --version, e.g. Bates2026)")
    parser.add_argument("--db", type=str, default=None,
                        help="VFB Site short_form (default: BANC<version>)")
    parser.add_argument("--threshold", type=int, default=1,
                        help="Keep connections with MORE than this many synapses "
                             "(default: 1, i.e. >= 2, as the other connectome imports)")
    parser.add_argument("--output", type=str, required=True, help="Output TSV path for ROBOT template")
    parser.add_argument("--connectivity-file", type=str, default=None,
                        help="Local path or URL of the per-neuropil connection counts parquet "
                             "(default: the --version file in the public BANC bucket)")
    return parser.parse_args()


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
    args = parse_args()
    dataset = args.dataset or DATASETS.get(args.version)
    if dataset is None:
        sys.exit(f"No VFB dataset known for BANC v{args.version}; pass --dataset")
    db = args.db or f"BANC{args.version}"
    source = args.connectivity_file or \
        f"{BUCKET}/neuron_connectivity/v{args.version}/{PER_NEUROPIL}"

    ci = ConnectomicsImport()

    print(f"Fetching accessions from VFB for dataset {dataset}, Site {db}")
    accessions = ci.get_accessions_from_vfb(dataset=dataset, db=db)
    print(f"Found {len(accessions)} accessions")
    if not accessions:
        print(f"ERROR: No neuron accessions found for dataset '{dataset}' with db '{db}'. "
              "Cannot proceed with connectivity import.")
        print("Please verify that:")
        print("  1. The dataset name is correct")
        print("  2. The dataset exists in the VFB knowledge base")
        print(f"  3. Neurons in the dataset have '{db}' cross-references")
        sys.exit(1)

    print(f"Summing per-neuropil connection counts from: {source}")
    conn_df = load_pair_weights(source, accessions)
    print(f"{len(conn_df)} connected pairs between VFB neurons "
          f"({int(conn_df['weight'].sum()) if len(conn_df) else 0} synapses)")

    conn_df = conn_df[conn_df["weight"] > args.threshold]
    print(f"After threshold > {args.threshold}: {len(conn_df)} edges "
          f"({int(conn_df['weight'].sum()) if len(conn_df) else 0} synapses)")

    print("Generating ROBOT template...")
    template_df = ci.generate_n_n_template(db=db, conn_df=conn_df)
    unmapped = template_df["ID"].isna().sum() + template_df["FACT"].isna().sum()
    if unmapped:
        sys.exit(f"ERROR: {unmapped} edge ends did not map to a VFB id via Site {db}")

    template_df.to_csv(args.output, sep="\t", index=False)
    print(f"ROBOT template written to: {args.output} ({len(template_df) - 1} edges)")


if __name__ == "__main__":
    main()
