# Local operation — 0.20.0-alpha.1

The optional Windows logon task runs as the current interactive user, without a saved password,
administrator privileges or a visible terminal. Enable it deliberately in Settings; setup does
not register a task. The release uses the project's managed `.venv` Python runtime and exact
project/data directory. The local supervisor monitors identity-checked health and
starts the server only on a confirmed closed port, with bounded backoff. It never restarts a
slow alive owned process to interrupt research. Unknown or foreign ports are not taken over.

Open-Laboratory.cmd now uses --supervised; Stop-Laboratory.cmd intentionally stops the
server and watcher through a marker. A manual launch clears the marker. Restarting does not
approve/repeat studies. Interrupted external calls remain outcome_unknown, and interrupted
publication remains uncertain. A sleeping/offline/logged-out computer is not an always-on host;
Windows sleep, privacy and security settings are not changed by this installation.

## Full local copies

While the app runs, maintenance creates one full copy per 24 hours, retains the last 14 complete
copies under .lab-backups, and checks a restored copy in an empty temporary folder. Copies use
SQLite's online snapshot, immutable publication files, source/job evidence and encrypted DPAPI
files; operational locks, transient logs and previous backups are excluded. Checksums, package
bindings and database integrity must pass before atomic completion. Mutable jobs/configuration
changes cause a safe abort and a later local attempt, not mixed-time copies or paid repetition.
Copy failures are recorded as errors and defer the next maintenance attempt for 15 minutes,
so a failed large copy is not attempted every minute. Windows path limits still apply; keep
the project in the intended short Desktop folder rather than a deeply nested checkout.
The Settings panel shows actual backup, drill, watcher and TEST_ONLY control status.

DPAPI files stay encrypted and work in the same Windows profile. These copies are on the same
disk; protection against disk loss requires a separate owner-selected destination. No upload
or cloud account is configured. Portable JSON export remains a separate knowledge-only feature.

## Restore deliberately, never overwrite the running laboratory

Stop the application first. From its project folder, inspect snapshots with:

    python -m laboratory.operations status

Restore a chosen snapshot into a new empty folder:

    python -m laboratory.operations restore --backup-id BACKUP_ID --destination C:\Lab-Recovery\.lab-data

Use the actual configured Python path if python is not on PATH. --backup-dir can point to an
existing snapshot collection; --data-dir selects the source data identity. Restore does not
launch a server, decrypt/export plaintext credentials, overwrite live data, or send anything.
Publication is disabled in the restored DB. Queued items are held; publishing/uncertain items
retain the uncertain state and receipts so the no-retry guard survives. Check the actual channel
before allowing a fresh owner-approved publication. CLI backup refuses a running InstanceLock;
use Settings → full copy for an online backup serialized with Telegram configuration.

## Evidence and remaining acceptance

Synthetic control matches test error detectors, not scientific truth. Saved-report audits are
read-only and preserve the existing queued package signature. The controlled local restart and
restore checks do not establish a week of uptime, a future scheduled release, or externally
reproduced technology benchmarks. Record these observations when they actually occur.
