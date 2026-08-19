#!/usr/bin/env bash
# Runs a command (typically a pip install) with git credentials configured so it
# can clone the now-private leonarduk/cicaid-pro repo. That package used to live
# at leonarduk/cicaid, and that old name was reused by a new, unrelated public
# repo, so old github.com/leonarduk/cicaid/releases/... wheel URLs 404
# (leonarduk/allotmint#6754). scripts/requirements-dev.txt pins cicaid-devtools
# under the current name.
#
# The URLs below deliberately name cicaid-pro rather than relying on any of
# GitHub's rename redirects: leonarduk/allotmint#6754 is precisely what happens
# when an old name is reused by an unrelated repo, and a stale name in a
# *credential* rewrite would hand a token-bearing URL to whatever now sits there.
#
# Fails fast with an actionable message if CICAID_PRO_TOKEN is unset or empty,
# instead of letting the wrapped command fail later with a confusing git auth
# error. The credential rewrite is scoped to exactly this invocation through
# Git's GIT_CONFIG_* environment variables; the token is never written to a
# config file.
#
# Usage: pip_install_cicaid_pro.sh <command...>
# Required env: CICAID_PRO_TOKEN
set -euo pipefail

if [ -z "${CICAID_PRO_TOKEN:-}" ]; then
  echo "::error::CICAID_PRO_TOKEN is empty or unset. Add a fine-grained PAT (Contents: Read-only, scoped to leonarduk/cicaid-pro) as the CICAID_PRO_TOKEN repository secret (Settings > Secrets and variables > Actions) before this workflow can install cicaid-devtools. See leonarduk/allotmint#6754." >&2
  exit 1
fi

export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0="url.https://x-access-token:${CICAID_PRO_TOKEN}@github.com/leonarduk/cicaid-pro.insteadOf"
export GIT_CONFIG_VALUE_0="https://github.com/leonarduk/cicaid-pro"

exec "$@"
