"""ROBOT template TSV for neuron-to-neuron connectivity from a VFB-hosted CATMAID server.

    python -m vfb_connectomics_import.connectivity.cli.catmaid --site catmaid_l1em \\
        --output L1EM_CATMAID_import.tsv

The CATMAID server is taken from the Site. A live server has no release, so the
provenance records the Site and the build date.
"""
import sys

# Fail fast on Python versions that are too old for upstream deps (neuprint uses
# structural pattern matching introduced in Python 3.10).
if sys.version_info < (3, 10):
    raise RuntimeError(
        "This script requires Python 3.10+ (found Python %d.%d). "
        "Please upgrade the interpreter in CI or pin 'neuprint-python' to a "
        "compatible version in requirements.txt." % (
            sys.version_info.major, sys.version_info.minor
        )
    )

from vfb_connectomics_import.connectivity.cli._common import (  # noqa: E402
    accessions_for_site, base_parser, write_template)
from vfb_connectomics_import.connectivity.core import ConnectomicsImport  # noqa: E402


def main():
    parser = base_parser("Generate ROBOT template TSV for CATMAID connectivity data",
                         site_required=False)
    # Legacy spelling, still used by the vfb-k8s release pipeline (connectome-catmaid):
    #   --dataset <Site> --catmaid_endpoint <url> --output_file <tsv>
    # Accepted so that pipeline keeps working until it moves to --site / --output.
    parser.add_argument("--catmaid_endpoint", "-c_e", default=None,
                        help="(legacy) CATMAID server; now derived from the Site")
    parser.add_argument("--output_file", default=None, help="(legacy) same as --output")
    args = parser.parse_args()
    if args.site is None and args.dataset:
        print(f"note: --dataset {args.dataset} taken as the Site (legacy form; use --site)")
        args.site, args.dataset = args.dataset, None
    args.output = args.output or args.output_file
    if not args.site or not args.output:
        parser.error("--site and --output are required")

    ci = ConnectomicsImport()
    prov = ci.site_provenance(args.site)
    if prov.kind != "catmaid":
        parser.error(f"Site {args.site} is a {prov.kind} source, not a CATMAID server")
    if args.catmaid_endpoint and args.catmaid_endpoint.rstrip("/") != prov.endpoint.rstrip("/"):
        print(f"WARNING: --catmaid_endpoint {args.catmaid_endpoint} differs from Site "
              f"{args.site}'s server {prov.endpoint}; using the Site's")
    print(f"Site {args.site} -> CATMAID server {prov.endpoint}")
    ci.connect_catmaid(prov.endpoint)

    # A CATMAID Site spans many VFB datasets, so neurons are selected by Site.
    accessions = accessions_for_site(ci, args.site, args.dataset)
    conn_df = ci.get_adjacencies_CATMAID(accessions, threshold=args.threshold)
    write_template(ci, args.site, conn_df, args.output, prov)


if __name__ == "__main__":
    main()
