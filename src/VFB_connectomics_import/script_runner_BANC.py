import argparse
import pandas as pd
import subprocess
import sys
from pathlib import Path
from connectomics_import import ConnectomicsImport


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate ROBOT template TSV for BANC connectivity data"
    )
    parser.add_argument("--dataset", type=str, required=True, help="VFB dataset name to query")
    parser.add_argument("--db", type=str, default="BANC626", help="Database cross-reference prefix (default: BANC626)")
    parser.add_argument("--threshold", type=int, default=0, help="Minimum synaptic weight threshold (default: 0)")
    parser.add_argument("--output", type=str, required=True, help="Output TSV path for ROBOT template")
    parser.add_argument("--connectivity-file", type=str, 
                        default="synapses_v1_human_readable_sizethresh3_connectioncounts_countthresh3.parquet",
                        help="Path to BANC connectivity parquet file (default: downloads from GCS if not found)")
    return parser.parse_args()


def download_connectivity_file(filepath):
    """Download the BANC connectivity file from Google Cloud Storage if it doesn't exist."""
    if not Path(filepath).exists():
        print(f"Connectivity file not found. Downloading from Google Cloud Storage...")
        gcs_path = "gs://lee-lab_brain-and-nerve-cord-fly-connectome/neuron_connectivity/v626/synapses_v1_human_readable_sizethresh3_connectioncounts_countthresh3.parquet"
        try:
            subprocess.run(["gsutil", "cp", gcs_path, filepath], check=True)
            print(f"Downloaded connectivity file to: {filepath}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to download connectivity file from GCS: {e}")
    return filepath


def main():
    args = parse_args()
    
    # Initialize the connectivity importer
    ci = ConnectomicsImport()
    
    # Get accessions from VFB for the specified dataset
    print(f"Fetching accessions from VFB for dataset: {args.dataset}")
    accessions = ci.get_accessions_from_vfb(dataset=args.dataset, db=args.db)
    print(f"Found {len(accessions)} accessions")
    
    # Check if any accessions were found
    if not accessions:
        print(f"ERROR: No neuron accessions found for dataset '{args.dataset}' with db '{args.db}'. Cannot proceed with connectivity import.")
        print("Please verify that:")
        print("  1. The dataset name is correct")
        print("  2. The dataset exists in the VFB knowledge base")
        print(f"  3. Neurons in the dataset have '{args.db}' cross-references")
        sys.exit(1)
    
    # Download connectivity file if needed
    connectivity_file = download_connectivity_file(args.connectivity_file)
    
    # Load BANC connectivity data from parquet file
    print(f"Loading BANC connectivity from: {connectivity_file}")
    all_conn_df = pd.read_parquet(connectivity_file)
    print(f"Loaded {len(all_conn_df)} total connectivity edges from file")
    
    # Filter to only include connections within our VFB accessions
    accessions_set = set(accessions)
    conn_df = all_conn_df[
        all_conn_df['pre_root_id'].isin(accessions_set) & 
        all_conn_df['post_root_id'].isin(accessions_set)
    ].copy()
    print(f"Filtered to {len(conn_df)} edges within VFB dataset")
    
    # Apply threshold
    if args.threshold > 0:
        conn_df = conn_df[conn_df['num_synapses'] > args.threshold]
        print(f"After threshold={args.threshold}: {len(conn_df)} edges remain")
    
    # Rename columns to match expected format
    conn_df.rename(columns={
        'pre_root_id': 'source',
        'post_root_id': 'target',
        'num_synapses': 'weight'
    }, inplace=True)
    
    # Generate ROBOT template
    print("Generating ROBOT template...")
    template_df = ci.generate_n_n_template(db=args.db, conn_df=conn_df)
    
    # Save to TSV
    template_df.to_csv(args.output, sep="\t", index=False)
    print(f"ROBOT template written to: {args.output}")


if __name__ == "__main__":
    main()
