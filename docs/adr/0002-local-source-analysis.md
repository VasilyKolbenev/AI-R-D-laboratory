# ADR-0002: local source-analysis increment

Status: implemented locally on 2026-10-20; does not accept any private-alpha gate.

The product owner requested implementation in this chat: receive selected Telegram Saved Messages, approve research explicitly, retain results as searchable knowledge. The latest instruction authorizes Codex to implement this bounded slice rather than waiting for the older manual Claude handoff. TASK-001 and the 57-item alpha acceptance matrix remain separate, uncompleted work; their contract fixtures and approved UI artifacts are unchanged.

## Decision

Use Python 3.11+ standard library, SQLite and a separate buildless Constellation-inspired UI. Keep the original Constellation prototype and documentation intact. One local Windows owner, one process, loopback binding, no hosting. Runtime data lives under ignored `.lab-data/` and is never served as static files.

The useful workflow is source intake → immutable plan snapshot/hash → explicit human approval → one official CLI invocation → stored report/raw output/usage → owner-selected finding. Telegram receipt never triggers research. Codex uses its existing ChatGPT CLI login, with user configuration/rules, shell, connectors, plugins, hooks and delegation disabled in the research profile. Claude uses normal official CLI authentication and safe mode with a restricted tool list. No OAuth token is extracted or copied. No local model is installed.

Imported originals and origins are immutable; equal material hashes retain distinct origins. A run freezes up to six sources and the exact question/options. Confirmation binds to its stored hash. Atomic SQLite transitions enforce one active run, the rolling 24-hour start cap and idempotent launch. A new research question creates a new run; saving a finding preserves the report and links to that run. Repeated save returns the original finding rather than mutating it.

Telegram Bot API receives only explicit private forwards. Pairing requires a random code shown locally and an exact `/start CODE`. Existing bot webhooks are not removed. The polling offset advances after source commit. Windows DPAPI protects the bot token; the application neither exports it nor reads CLI credential files.

Backup is a transactionally consistent JSON export of four content tables, excluding settings/credentials. Restore is atomic, verifies source and plan hashes, and requires an empty destination. Sources, plans and raw answers remain available independently of browser local storage.

## Limits and unproven claims

This is source analysis, which the architecture already recognizes as distinct from reproducing a scientific experiment. There is no isolated experiment runner, independent measurement/judge, paid-call ledger, Temporal/PostgreSQL, multi-user identity or production sandbox. Reports and linked URLs remain model claims until checked. Search budgets are prompt instructions; wall-clock time, output bytes and one-invocation policy are enforced locally. CLI internals may retry requests. Timeouts, cancellation and interrupted process recovery preserve an unknown outcome without starting another CLI invocation automatically. A forced process stop cannot establish cancellation or refund on the provider side.

CLI feature restrictions are defence in depth, not an OS security boundary; provider-managed policies still apply. Leaving the model field empty explicitly selects the CLI's built-in default; this is recorded in the plan, not a reproducible benchmark version. Claude is detected separately and must not silently fall back to Codex. Full attachment/PDF extraction and unattended discovery are not implemented.

The prior 4–5 week alpha forecast is not reasserted by this increment. Alpha gate statuses change only through their original evidence and acceptance process.

## Verification

Unit/integration tests cover exact approval, duplicate dispatch, parallel approval, rolling limit, unknown-outcome recovery, imports, origin retention, Unicode search, snapshot backup and atomic restore, HTTP CSRF/Host/static isolation, CLI parsers/tool restrictions and Telegram owner pairing/offset/DPAPI. Browser QA uses clearly labelled fixtures and a separate data directory; test content does not enter the user's database. Real model and real Telegram connectivity are reported separately from mocked checks.

References: [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference), [Claude CLI reference](https://code.claude.com/docs/en/cli-reference), [Telegram Bot API](https://core.telegram.org/bots/api).
