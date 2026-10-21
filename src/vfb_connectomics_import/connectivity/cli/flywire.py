"""ROBOT template TSV for FlyWire neuron-to-neuron connectivity.

    python -m vfb_connectomics_import.connectivity.cli.flywire --site flywire783 \\
        --output connectome_flywire_fafb.tsv

The CAVE materialization (e.g. 783) is taken from the Site, so the edges and the
release stamped into the OWL cannot disagree.
"""
from vfb_connectomics_import.connectivity.cli._common import (
    accessions_for_site, base_parser, write_template)
from vfb_connectomics_import.connectivity.core import ConnectomicsImport


def main():
    parser = base_parser("Generate ROBOT template TSV for FlyWire connectivity data",
                         default_site="flywire783")
    parser.add_argument("--batchsize", type=int, default=1000,
                        help="Neurons per CAVE connectivity request (default: 1000)")
    args = parser.parse_args()

    ci = ConnectomicsImport()
    prov = ci.site_provenance(args.site)
    if prov.kind != "codex":
        parser.error(f"Site {args.site} is a {prov.kind} source, not a FlyWire materialization")
    print(f"Site {args.site} -> FlyWire materialization {prov.materialization}")

    accessions = accessions_for_site(ci, args.site, args.dataset)
    conn_df = ci.get_adjacencies_flywire(accessions=accessions, materialization=prov.materialization,
                                         threshold=args.threshold, batchsize=args.batchsize)
    write_template(ci, args.site, conn_df, args.output, prov)


if __name__ == "__main__":
    main()
