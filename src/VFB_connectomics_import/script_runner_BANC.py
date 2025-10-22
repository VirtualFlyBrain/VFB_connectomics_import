import argparse
from connectomics_import import ConnectomicsImport


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate ROBOT template TSV for BANC connectivity data"
    )
    parser.add_argument("--dataset", type=str, required=True, help="VFB dataset name to query")
    parser.add_argument("--db", type=str, default="BANC626", help="Database cross-reference prefix (default: BANC626)")
    parser.add_argument("--threshold", type=int, default=0, help="Minimum synaptic weight threshold (default: 0)")
    parser.add_argument("--output", type=str, required=True, help="Output TSV path for ROBOT template")
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Initialize the connectivity importer
    ci = ConnectomicsImport()
    
    # Get accessions from VFB for the specified dataset
    print(f"Fetching accessions from VFB for dataset: {args.dataset}")
    accessions = ci.get_accessions_from_vfb(dataset=args.dataset, db=args.db)
    print(f"Found {len(accessions)} accessions")
    
    # Get connectivity data from BANC using get_adjacencies_flywire with dataset='banc' and materialization=626
    print(f"Fetching BANC connectivity (threshold={args.threshold})...")
    conn_df = ci.get_adjacencies_flywire(accessions, threshold=args.threshold, dataset='banc', materialization=626)
    print(f"Retrieved {len(conn_df)} connectivity edges")
    
    # Generate ROBOT template
    print("Generating ROBOT template...")
    template_df = ci.generate_n_n_template(db=args.db, conn_df=conn_df)
    
    # Save to TSV
    template_df.to_csv(args.output, sep="\t", index=False)
    print(f"ROBOT template written to: {args.output}")


if __name__ == "__main__":
    main()
