# Reconciliation MCP tool design

Portfolio reconciliation deliberately uses a two-step protocol:

1. `allotmint_reconcile` sends the owner, account type, and original broker CSV to the backend's
   read-only `POST /holdings/reconcile` endpoint. The backend owns broker parsing and ticker,
   currency, and pence/GBP normalization. Its structured response contains the complete diff and
   an opaque `reconciliation_id` bound to that diff.
2. A client must display that diff for human review. Only after approval may it pass the opaque ID
   to `allotmint_apply_reconciliation`, which calls `POST /holdings/reconcile/apply`.

The apply tool accepts no holdings, CSV, owner, account, or replacement values. Consequently an AI
client cannot alter the reviewed payload between preview and apply; the backend must reject an
unknown, expired, already-used, or stale ID. The backend remains responsible for atomic writes and
for checking that stored holdings have not changed since the preview.

The preview is always registered because it is read-only. The apply tool is absent unless
`ALLOTMINT_MCP_WRITE_ENABLED=true`; the default therefore has no portfolio write capability. This
flag is a deployment boundary rather than user approval: enabled clients must still obtain human
approval of each returned diff.

CSV parsing and financial normalization are intentionally not duplicated in this repository. The
AllotMint backend's importer test suite is the source of truth for broker formats, including
Hargreaves Lansdown `.L` ticker normalization and GBX/GBP conversion.
