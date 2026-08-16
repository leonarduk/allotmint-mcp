#!/usr/bin/env bash
set -euo pipefail

tag=${1:?Usage: extract-changelog.sh TAG [CHANGELOG] [OUTPUT]}
changelog=${2:-CHANGELOG.md}
output=${3:-release-notes.md}
version=${tag#v}
heading="## [$version]"

awk -v heading="$heading" '
  $0 == heading || index($0, heading " - ") == 1 { found = 1; next }
  found && /^## \[/ { exit }
  found { print }
  END { if (!found) exit 1 }
' "$changelog" > "$output" || {
  rm -f "$output"
  echo "No changelog entry found for $tag (expected a '$heading' heading)" >&2
  exit 1
}

if ! grep -q '[^[:space:]]' "$output"; then
  rm -f "$output"
  echo "The changelog entry for $tag is empty" >&2
  exit 1
fi
