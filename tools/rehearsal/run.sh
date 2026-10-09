#!/bin/bash
# Full rehearsal: pick a batch, mirror what is served, run the loader against it with
# --archive, then audit. Nothing here touches production.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REHEARSAL_DIR="${REHEARSAL_DIR:-$HOME/Documents/vfb_malecns_rehearsal}"
export PYTHONPATH="$REPO/src"
PY="${PY:-$HOME/Documents/venvs/VFB_connectomics_import/bin/python}"
cd "$REPO"; set -a; . ./.env; set +a
export IMAGE_FIELD_DIR="${IMAGE_FIELD_DIR:-$HOME/Documents/banc_transform_fields}"

echo "### 1. batch";   $PY tools/rehearsal/build_testset.py   || exit 1
echo "### 2. mirror";  $PY tools/rehearsal/mirror_served.py   || exit 1
echo "### 3. baseline: $(find "$REHEARSAL_DIR/live" -type f | wc -l) files, $(du -sh "$REHEARSAL_DIR/live" | cut -f1)"
rm -rf "$REHEARSAL_DIR/archive" "$REHEARSAL_DIR/run.jsonl" "$REHEARSAL_DIR/report.csv"
echo "### 4. run"
$PY -m vfb_connectomics_import.images.loader \
  --connectome "${CONNECTOME:-malecns}" --region both \
  --roots "@$REHEARSAL_DIR/testset.roots" \
  --write-root "$REHEARSAL_DIR/live" --archive "$REHEARSAL_DIR/archive" \
  --ledger "$REHEARSAL_DIR/run.jsonl" --report "$REHEARSAL_DIR/report.csv" \
  --workers "${WORKERS:-4}" --quiet --progress-every 50 2>&1 | tail -30
echo "### 5. after: $(find "$REHEARSAL_DIR/live" -type f | wc -l) files, $(du -sh "$REHEARSAL_DIR/live" | cut -f1)"
echo "### 6. audit"; $PY tools/rehearsal/check.py
