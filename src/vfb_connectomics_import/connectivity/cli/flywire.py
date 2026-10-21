"""ROBOT template TSV for FlyWire neuron-to-neuron connectivity.

    python -m vfb_connectomics_import.connectivity.cli.flywire --site flywire783 \\
        --output connectome_flywire_fafb.owl

The materialization (e.g. 783) is taken from the Site, so the edges and the release
stamped into the OWL cannot disagree.

By default the edges come from the release's published proofread connections
(proofread_connections_783.feather, Zenodo 10676866: one row per proofread pair and
neuropil, cleft score >= 50 — the same release files vfb-region-connectivity uses for
FlyWire region counts and totals), summed per pair and kept where > --threshold. No
CAVE token is needed. `--source cave` queries CAVE through fafbseg instead (needs a
CAVE token).
"""
from vfb_connectomics_import.connectivity.cli._common import (
    accessions_for_site, base_parser, load_pair_weights_file, write_output)
from vfb_connectomics_import.connectivity.core import ConnectomicsImport

# Published pair-level connectivity per FlyWire materialization
RELEASE_FILES = {
    783: "https://zenodo.org/records/10676866/files/proofread_connections_783.feather",
}


def main():
    parser = base_parser("Generate ROBOT template TSV for FlyWire connectivity data",
                         default_site="flywire783")
    parser.add_argument("--source", choices=["release", "cave"], default="release",
                        help="release: the materialization's published proofread connections "
                             "(default); cave: query CAVE via fafbseg")
    parser.add_argument("--connectivity-file", default=None,
                        help="Override the release file (path or URL; columns pre_pt_root_id, "
                             "post_pt_root_id, syn_count)")
    parser.add_argument("--batchsize", type=int, default=1000,
                        help="Neurons per CAVE connectivity request (--source cave; default: 1000)")
    args = parser.parse_args()

    ci = ConnectomicsImport()
    prov = ci.site_provenance(args.site)
    if prov.kind != "codex" or not prov.source.startswith("flywire:"):
        parser.error(f"Site {args.site} is not a FlyWire materialization ({prov.source})")
    print(f"Site {args.site} -> FlyWire materialization {prov.materialization}")

    accessions = accessions_for_site(ci, args.site, args.dataset)
    if args.source == "cave":
        conn_df = ci.get_adjacencies_flywire(accessions=accessions,
                                             materialization=prov.materialization,
                                             threshold=args.threshold, batchsize=args.batchsize)
    else:
        source = args.connectivity_file or RELEASE_FILES.get(prov.materialization)
        if not source:
            parser.error(f"no published connections file known for materialization "
                         f"{prov.materialization}; pass --connectivity-file or --source cave")
        print(f"Pair weights from {source}")
        conn_df = load_pair_weights_file(source, accessions, "pre_pt_root_id",
                                         "post_pt_root_id", "syn_count", args.threshold)
    print(f"{len(conn_df)} edges between VFB neurons")
    write_output(ci, args.site, conn_df, args, prov)


if __name__ == "__main__":
    main()
