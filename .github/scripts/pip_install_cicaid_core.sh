#!/usr/bin/env bash
# Runs a command (typically a pip install) with git credentials configured so it
# can clone the now-private leonarduk/cicaid-core repo. leonarduk/cicaid was
# renamed to leonarduk/cicaid-core (private) and its old name reused by a new,
# unrelated public repo, so old github.com/leonarduk/cicaid/releases/... wheel
# URLs 404 (leonarduk/allotmint#6754); scripts/requirements-dev.txt now pins
# cicaid-devtools to the private repo instead.
#
# Fails fast with an actionable message if CICAID_CORE_TOKEN is unset or empty,
# instead of letting the wrapped command fail later with a confusing git auth
# error. The credential rewrite is scoped to exactly this invocation through
# Git's GIT_CONFIG_* environment variables; the token is never written to a
# config file.
#
# Usage: pip_install_cicaid_core.sh <command...>
# Required env: CICAID_CORE_TOKEN
set -euo pipefail

if [ -z "${CICAID_CORE_TOKEN:-}" ]; then
  echo "::error::CICAID_CORE_TOKEN is empty or unset. Add a fine-grained PAT (Contents: Read-only, scoped to leonarduk/cicaid-core) as the CICAID_CORE_TOKEN repository secret (Settings > Secrets and variables > Actions) before this workflow can install cicaid-devtools. See leonarduk/allotmint#6754." >&2
  exit 1
fi

export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0="url.https://x-access-token:${CICAID_CORE_TOKEN}@github.com/leonarduk/cicaid-core.insteadOf"
export GIT_CONFIG_VALUE_0="https://github.com/leonarduk/cicaid-core"

exec "$@"
