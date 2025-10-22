import argparse
import json
import os

from BANC_import import BANCImporter, generate_curation_tsv_from_ids


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download skeleton/mesh/NRRD for BANC root IDs and/or generate a curation TSV"
    )
    parser.add_argument("--ids", type=str, required=False, help="Comma-separated list of BANC root IDs")
    parser.add_argument("--ids-file", type=str, required=False, help="Path to a file (txt/csv/json) with root IDs")
    parser.add_argument("--out-dir", type=str, required=True, help="Base output folder (per-root subfolders will be created)")
    parser.add_argument("--dataset", type=str, default="banc", help="FlyWire dataset name (default: banc)")
    parser.add_argument("--transform-source", type=str, default=None, help="navis.xform_brain source (optional)")
    parser.add_argument("--transform-target", type=str, default=None, help="navis.xform_brain target (optional)")
    parser.add_argument("--transform-via", type=str, default=None, help="navis.xform_brain via (optional)")
    parser.add_argument("--redo", action="store_true", help="Recreate artifacts even if files exist")
    parser.add_argument("--no-nrrd", action="store_true", help="Skip NRRD voxelization")
    parser.add_argument("--curation-tsv", type=str, help="Path to write a simple curation TSV for provided IDs")
    return parser.parse_args()


def read_ids(ids_arg: str | None, ids_file: str | None):
    ids = []
    if ids_arg:
        ids.extend([int(x) for x in ids_arg.split(",") if x.strip()])
    if ids_file:
        if ids_file.lower().endswith(".json"):
            with open(ids_file) as f:
                data = json.load(f)
            if isinstance(data, dict) and "ids" in data:
                ids.extend([int(x) for x in data["ids"]])
            elif isinstance(data, list):
                ids.extend([int(x) for x in data])
        else:
            with open(ids_file) as f:
                for line in f:
                    line = line.strip().split(",")[0]
                    if line:
                        ids.append(int(line))
    return sorted(list(set(ids)))


def main():
    args = parse_args()
    ids = read_ids(args.ids, args.ids_file)
    if not ids:
        raise SystemExit("No root IDs provided via --ids or --ids-file")

    os.makedirs(args.out_dir, exist_ok=True)

    importer = BANCImporter(
        dataset=args.dataset,
        transform_source=args.transform_source,
        transform_target=args.transform_target,
        transform_via=args.transform_via,
    )

    summary_df = importer.process_batch(
        ids,
        out_dir=args.out_dir,
        redo=args.redo,
        voxelize_nrrd=not args.no_nrrd,
    )

    # Curation TSV if requested
    if args.curation_tsv:
        curation_df = generate_curation_tsv_from_ids(ids)
        curation_df.to_csv(args.curation_tsv, sep="\t", index=False)

    # Also write a JSONL summary next to outputs
    summary_path = os.path.join(args.out_dir, "banc_import_summary.tsv")
    summary_df.to_csv(summary_path, sep="\t", index=False)
    print(f"Wrote summary: {summary_path}")


if __name__ == "__main__":
    main()
