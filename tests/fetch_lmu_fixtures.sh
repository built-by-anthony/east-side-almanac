#!/usr/bin/env bash
# Downloads the LMU PDF test fixtures. They are not committed because the reports are
# copyrighted (ShowingTime Plus) and this repo is public. Dated URLs make them reproducible.
set -euo pipefail
cd "$(dirname "$0")"

cities=("Woodbury" "Lake Elmo" "Oakdale" "Maplewood" "Stillwater" "Cottage Grove" "North St. Paul")

for month in 2026-07 2026-08; do
  mkdir -p "fixtures/lmu/$month"
  for c in "${cities[@]}"; do
    curl -sf -o "fixtures/lmu/$month/$c.pdf" \
      "https://maar.stats.10kresearch.com/docs/lmu/$month/x/${c// /%20}"
  done
done
echo "fixtures in tests/fixtures/lmu/"
