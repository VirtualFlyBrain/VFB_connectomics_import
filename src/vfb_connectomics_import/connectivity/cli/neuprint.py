"""ROBOT template TSV for a neuprint connectome's neuron-to-neuron connectivity.

    python -m vfb_connectomics_import.connectivity.cli.neuprint --site male-cns_v1_0 \\
        --output connectome_malecns_n2n.tsv

The neuprint dataset (e.g. male-cns:v1.0) is taken from the Site, so the edges and
the release stamped into the OWL cannot disagree. The token comes from
$NEUPRINT_TOKEN or ~/neuprint_token.txt.
"""
from vfb_connectomics_import.connectivity.cli._common import (
    accessions_for_site, base_parser, neuprint_token, write_template)
from vfb_connectomics_import.connectivity.core import ConnectomicsImport


def main():
    parser = base_parser("Generate ROBOT template TSV for neuprint connectivity data")
    parser.add_argument("--neuprint_endpoint", default="https://neuprint.janelia.org",
                        help="neuprint server (default: https://neuprint.janelia.org)")
    parser.add_argument("--neuprint_token_file", default=None,
                        help="File holding the neuprint token (default: $NEUPRINT_TOKEN, "
                             "then ~/neuprint_token.txt)")
    args = parser.parse_args()

    ci = ConnectomicsImport()
    prov = ci.site_provenance(args.site)
    if prov.kind != "neuprint":
        parser.error(f"Site {args.site} is a {prov.kind} source, not neuprint")
    print(f"Site {args.site} -> neuprint dataset {prov.neuprint_dataset}")
    ci.connect_neuprint(args.neuprint_endpoint, prov.neuprint_dataset,
                        neuprint_token(args.neuprint_token_file))

    accessions = accessions_for_site(ci, args.site, args.dataset)
    conn_df = ci.get_adjacencies_neuprint(accessions=accessions, threshold=args.threshold)
    write_template(ci, args.site, conn_df, args.output, prov)


if __name__ == "__main__":
    main()
