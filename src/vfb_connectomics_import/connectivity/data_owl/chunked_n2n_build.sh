#!/bin/bash
# Build a large n2n (neuron-to-neuron) connectivity OWL file from a ROBOT
# template TSV by splitting it into chunks, running `robot template` on each,
# and concatenating the results.
#
# WHY: `robot template` builds the whole ontology in memory. For multi-million
# row n2n tables (e.g. Berg2025 = 15.3M rows) this needs ~15+ GB of heap and
# OOMs on a 16 GB machine ("Not enough memory to allocate buffers to grow
# from 4194304 -> 8388608 elements"). Each ~2M-row chunk peaks at ~4.6 GB and
# runs in ~75s, so the chunked build stays in RAM (no swap) and is lossless.
#
# SAFE TO CONCATENATE because `-input-iri ro.owl` is used ONLY to resolve the
# 'synapsed to' label -> RO_0002120; RO is NOT embedded in the output. Every
# chunk emits the identical Prefix block + `Ontology(<iri>` header + a body of
# Declaration/ObjectPropertyAssertion lines. concat_ofn_chunks.py keeps one
# header, appends all bodies, and closes once. Duplicate declarations across
# chunks are idempotent in OWL.
#
# Usage:
#   chunked_n2n_build.sh <input.tsv> <output.owl> [ontology-iri] [rows-per-chunk]
#
# Provenance (README "Artifact versions"): the output records which source release
# it was built from in its header — a version IRI <base>/<Site>_import.owl and a
# dc:source annotation — which the import dashboard reads back. The connectivity
# CLIs write them next to the template as <input.tsv>.provenance, and this script
# picks that file up automatically. VERSION_IRI / DC_SOURCE in the environment
# override it. Without either the OWL is built unstamped, with a warning.
#
# Example (BANC v888; the CLI wrote BANC_n2n.tsv and BANC_n2n.tsv.provenance):
#   ./chunked_n2n_build.sh BANC_n2n.tsv connectome_BANC_n2n.owl \
#       http://virtualflybrain.org/data/VFB/OWL/BANC_import.owl 2000000
set -euo pipefail

SRC="${1:?input template TSV required}"
FINAL="${2:?output OWL path required}"
ONT_IRI="${3:-http://virtualflybrain.org/data/VFB/OWL/CATMAID_import.owl}"
CHUNK_ROWS="${4:-2000000}"
HEAP="${ROBOT_HEAP:-5g}"

if [ -f "$SRC.provenance" ]; then
  while IFS=$'\t' read -r key value; do
    case "$key" in
      VERSION_IRI) VERSION_IRI="${VERSION_IRI:-$value}" ;;
      DC_SOURCE)   DC_SOURCE="${DC_SOURCE:-$value}" ;;
    esac
  done < "$SRC.provenance"
  echo "provenance from $SRC.provenance"
fi
if [ -z "${VERSION_IRI:-}" ]; then
  echo "WARNING: no $SRC.provenance and no VERSION_IRI — the OWL will not record its" >&2
  echo "         source release, and the dashboard will report it as unversioned." >&2
fi
echo "    version IRI: ${VERSION_IRI:-<none>}"
echo "    dc:source:   ${DC_SOURCE:-<none>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/n2n_build.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

echo "[1/3] splitting $SRC into ${CHUNK_ROWS}-row chunks (workdir: $WORK)..."
head -2 "$SRC" > "$WORK/header.tsv"          # row 1 = column names, row 2 = ROBOT directives
tail -n +3 "$SRC" | split -l "$CHUNK_ROWS" - "$WORK/chunk_"
NCHUNK=$(ls "$WORK"/chunk_* | wc -l | tr -d ' ')
echo "    $NCHUNK chunks"

export ROBOT_JAVA_ARGS="-Xmx${HEAP}"
ANNOTATE=(annotate --ontology-iri "$ONT_IRI")
[ -n "${VERSION_IRI:-}" ] && ANNOTATE+=(--version-iri "$VERSION_IRI")
[ -n "${DC_SOURCE:-}" ] && ANNOTATE+=(--annotation dc:source "$DC_SOURCE")
i=0
for c in "$WORK"/chunk_*; do
  cat "$WORK/header.tsv" "$c" > "$WORK/cur.tsv"
  echo "[2/3] building chunk $i ($(wc -l < "$c" | tr -d ' ') rows)..."
  robot template -input-iri http://purl.obolibrary.org/obo/ro.owl \
    --add-prefix "n2o: http://neo2owl/custom/" \
    --add-prefix "VFB: http://virtualflybrain.org/reports/VFB_" \
    --template "$WORK/cur.tsv" \
    "${ANNOTATE[@]}" \
    convert -f ofn --output "$WORK/out_$(printf '%02d' $i).owl"
  i=$((i+1))
done

echo "[3/3] concatenating $i chunk ontologies into $FINAL ..."
python3 "$SCRIPT_DIR/concat_ofn_chunks.py" "$WORK" "$FINAL"

# sanity check: output axiom count must equal source data rows
SRC_ROWS=$(( $(wc -l < "$SRC") - 2 ))
OUT_AX=$(grep -c ObjectPropertyAssertion "$FINAL")
echo "DONE. source rows=$SRC_ROWS  output axioms=$OUT_AX"
[ "$SRC_ROWS" -eq "$OUT_AX" ] || { echo "ERROR: axiom count mismatch!" >&2; exit 1; }
ls -la "$FINAL"
