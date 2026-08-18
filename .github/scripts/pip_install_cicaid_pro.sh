#!/usr/bin/env bash
# Runs a command (typically a pip install) with git credentials configured so it
# can clone the now-private leonarduk/cicaid-pro repo. That repo has been renamed
# twice: leonarduk/cicaid was renamed to leonarduk/cicaid-core (private) and its
# old name reused by a new, unrelated public repo, so old
# github.com/leonarduk/cicaid/releases/... wheel URLs 404
# (leonarduk/allotmint#6754); cicaid-core was then renamed again to cicaid-pro.
# scripts/requirements-dev.txt pins cicaid-devtools under the current name.
#
# The URLs below deliberately name cicaid-pro rather than relying on GitHub's
# rename redirect from cicaid-core: leonarduk/allotmint#6754 is precisely what
# happens when an old name is reused by an unrelated repo, and a stale name in a
# *credential* rewrite would hand a token-bearing URL to whatever now sits there.
#
# NOTE: the CICAID_CORE_TOKEN secret still carries the old name. Renaming a
# repository secret needs a coordinated Settings change plus edits to the caller
# workflows, so it is tracked separately (#550); the secret name is just an
# identifier and carries none of the URL-reuse risk described above.
#
# Fails fast with an actionable message if CICAID_CORE_TOKEN is unset or empty,
# instead of letting the wrapped command fail later with a confusing git auth
# error. The credential rewrite is scoped to exactly this invocation through
# Git's GIT_CONFIG_* environment variables; the token is never written to a
# config file.
#
# Usage: pip_install_cicaid_pro.sh <command...>
# Required env: CICAID_CORE_TOKEN
set -euo pipefail

if [ -z "${CICAID_CORE_TOKEN:-}" ]; then
  echo "::error::CICAID_CORE_TOKEN is empty or unset. Add a fine-grained PAT (Contents: Read-only, scoped to leonarduk/cicaid-pro) as the CICAID_CORE_TOKEN repository secret (Settings > Secrets and variables > Actions) before this workflow can install cicaid-devtools. See leonarduk/allotmint#6754." >&2
  exit 1
fi

export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0="url.https://x-access-token:${CICAID_CORE_TOKEN}@github.com/leonarduk/cicaid-pro.insteadOf"
export GIT_CONFIG_VALUE_0="https://github.com/leonarduk/cicaid-pro"

exec "$@"
