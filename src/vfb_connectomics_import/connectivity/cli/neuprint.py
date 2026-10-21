"""ROBOT template TSV for a neuprint connectome's neuron-to-neuron connectivity.

    python -m vfb_connectomics_import.connectivity.cli.neuprint --site male-cns_v1_0 \\
        --output connectome_malecns_n2n.tsv

The neuprint dataset (e.g. male-cns:v1.0) is taken from the Site, so the edges and
the release stamped into the OWL cannot disagree. The token comes from
$NEUPRINT_TOKEN or ~/neuprint_token.txt.

Weights are whole-neuron: all synapses between the two bodies, whatever ROI they
fall in (neuprint's ConnectsTo weight), kept where > --threshold. By default they
are queried from neuprint in batches of source bodies. For a large dataset, pass
the release's published flat-connectome weights instead (body_pre, body_post,
weight), e.g. for male-cns v1.0:
  https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/connectome-weights-male-cns-v1.0-minconf-0.5.feather
and optic-lobe v1.0.1:
  https://storage.googleapis.com/flyem-optic-lobe/v1.0/optic-lobe-v1.0.1-flat-connectome/connectome-weights-2023-10-31-27a052-minconf-0.5-ol.feather
"""
from vfb_connectomics_import.connectivity.cli._common import (
    accessions_for_site, base_parser, load_pair_weights_file, neuprint_token, write_template)
from vfb_connectomics_import.connectivity.core import ConnectomicsImport


def main():
    parser = base_parser("Generate ROBOT template TSV for neuprint connectivity data")
    parser.add_argument("--neuprint_endpoint", default="https://neuprint.janelia.org",
                        help="neuprint server (default: https://neuprint.janelia.org)")
    parser.add_argument("--neuprint_token_file", default=None,
                        help="File holding the neuprint token (default: $NEUPRINT_TOKEN, "
                             "then ~/neuprint_token.txt)")
    parser.add_argument("--connectivity-file", default=None,
                        help="The release's flat-connectome weights (feather/parquet with "
                             "body_pre, body_post, weight; path or URL) instead of querying neuprint")
    args = parser.parse_args()

    ci = ConnectomicsImport()
    prov = ci.site_provenance(args.site)
    if prov.kind != "neuprint":
        parser.error(f"Site {args.site} is a {prov.kind} source, not neuprint")
    print(f"Site {args.site} -> neuprint dataset {prov.neuprint_dataset}")
    accessions = accessions_for_site(ci, args.site, args.dataset)
    if args.connectivity_file:
        print(f"Pair weights from {args.connectivity_file}")
        conn_df = load_pair_weights_file(args.connectivity_file, accessions,
                                         "body_pre", "body_post", "weight", args.threshold)
    else:
        ci.connect_neuprint(args.neuprint_endpoint, prov.neuprint_dataset,
                            neuprint_token(args.neuprint_token_file))
        conn_df = ci.get_adjacencies_neuprint_totals(accessions=accessions, threshold=args.threshold)
    print(f"{len(conn_df)} edges between VFB neurons")
    write_template(ci, args.site, conn_df, args.output, prov)


if __name__ == "__main__":
    main()
