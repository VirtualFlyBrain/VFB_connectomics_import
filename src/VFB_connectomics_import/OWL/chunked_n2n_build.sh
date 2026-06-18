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
# Example (Berg2025 male CNS):
#   ./chunked_n2n_build.sh Berg2025_n_2_n.tsv connectome_malecns_1_0_n2n.owl \
#       http://virtualflybrain.org/data/VFB/OWL/CATMAID_import.owl 2000000
set -euo pipefail

SRC="${1:?input template TSV required}"
FINAL="${2:?output OWL path required}"
ONT_IRI="${3:-http://virtualflybrain.org/data/VFB/OWL/CATMAID_import.owl}"
CHUNK_ROWS="${4:-2000000}"
HEAP="${ROBOT_HEAP:-5g}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/n2n_build.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

echo "[1/3] splitting $SRC into ${CHUNK_ROWS}-row chunks (workdir: $WORK)..."
head -2 "$SRC" > "$WORK/header.tsv"          # row 1 = column names, row 2 = ROBOT directives
tail -n +3 "$SRC" | split -l "$CHUNK_ROWS" - "$WORK/chunk_"
NCHUNK=$(ls "$WORK"/chunk_* | wc -l | tr -d ' ')
echo "    $NCHUNK chunks"

export ROBOT_JAVA_ARGS="-Xmx${HEAP}"
i=0
for c in "$WORK"/chunk_*; do
  cat "$WORK/header.tsv" "$c" > "$WORK/cur.tsv"
  echo "[2/3] building chunk $i ($(wc -l < "$c" | tr -d ' ') rows)..."
  robot template -input-iri http://purl.obolibrary.org/obo/ro.owl \
    --add-prefix "n2o: http://neo2owl/custom/" \
    --add-prefix "VFB: http://virtualflybrain.org/reports/VFB_" \
    --template "$WORK/cur.tsv" \
    annotate --ontology-iri "$ONT_IRI" \
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
