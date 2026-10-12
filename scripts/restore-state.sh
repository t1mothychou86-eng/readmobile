#!/usr/bin/env bash
# Download only the published metadata state, never any paper links.
set -euo pipefail
state_path="${1:?Usage: restore-state.sh STATE_PATH}"
mkdir -p "$(dirname "$state_path")"
rm -f "$state_path" "$state_path.tmp"
if [[ -n "${SITE_URL:-}" ]] && curl --fail --silent \
    --proto '=https' --connect-timeout 10 --max-time 30 \
    --header 'Cache-Control: no-cache' \
    --output "$state_path.tmp" "${SITE_URL%/}/data/state.json"; then
  mv "$state_path.tmp" "$state_path"
  echo 'Published state restored.'
else
  rm -f "$state_path.tmp"
  echo 'Published state unavailable; starting with empty state.'
fi
