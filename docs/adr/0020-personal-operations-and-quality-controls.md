# ADR-0020 — personal operational readiness

Use stdlib local components rather than additional model calls or hosted infrastructure.
A per-user Windows logon entry starts an identity-checked single supervisor. It monitors the
existing server, restarts a confirmed closed/terminated server with bounded backoff, respects
intentional stop, and refuses foreign/ambiguous ports. It does not kill a slow paid request,
repeat research, modify Windows sleep/security preferences, or start a second bot poller.

Daily full local backups use SQLite's online snapshot plus immutable publication artifacts
and encrypted DPAPI files. Atomic completion, manifest checks and bounded retention distinguish
valid snapshots from partial copies. Backup/drill status is visible. Restore drills use empty
isolated destinations with networking disabled by construction (no server instantiated).
Restored active publication state is held for review to avoid sending a stale approved item
twice. DPAPI recovery is limited to the same Windows profile; a different profile must rebind.

Quality audits are pure read models of frozen source evidence, comparisons and critic handling.
Synthetic negative controls measure defect detection, not scientific validity. They do not
change the immutable presentation or approval signature of existing queued/published packages.

Three future UI concepts are static self-contained HTML demos with progressive disclosure and
local interactions only. They expose the same functional map and label saved/example data.
No simulated graph, score or button may masquerade as a new measurement or paid execution.
