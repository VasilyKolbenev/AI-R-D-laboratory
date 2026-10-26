# ADR-0003: versioned research memory with exact approval context

Status: implemented locally on 2026-10-21. Extends ADR-0002; no private-alpha gate is accepted by this increment.

The owner requested that new AI research use earlier findings, retain interests and corrections, identify contradictions and refresh outdated knowledge. They must see exactly what memory is used before approving a run. Paid research continues only on an explicit command.

## Decision

Keep the existing Python/SQLite application and add a separate memory module. No new service, vector database, local model or GPU is required. The profile stores versioned owner interests, goals, preferences and a review interval. Corrections are independently versioned and can be global or attached to a finding. The fixed product scope remains AI and directly related advanced technology.

Saved findings seed revision 1 without changing the original report. Each revision retains its claim, notes, status, next review date, evidence run and source IDs. Manual correction, retirement and accepted model updates append revisions. History retains old versions and originating reports. A date marks a claim as due for review, not scientifically false. Pending contradictory evidence marks the current revision as disputed.

Local BM25-style ranking with small Russian/English topic aliases recommends up to five findings among twelve candidates. It uses the question and supplied source text. Retired findings are excluded from automatic suggestions; explicit selection and refresh can include them. At most six applicable corrections and a bounded 16,000-character snapshot are included. Truncation is explicit in the same snapshot shown to the owner. This is lexical retrieval, not semantic search; it can miss relevant relationships.

The plan freezes profile/corrections/finding text, IDs, versions, review status, selection reasons and a snapshot hash. Its outer plan hash binds all of that context. Changing selection creates a new plan version and clears consent in the UI. Approval checks generation and current versions in the same SQLite transaction as launch. Changes after planning require a fresh preview and approval. Execution uses the frozen snapshot rather than reading live memory. Neither preview nor a profile edit invokes a model.

The existing research call receives this exact memory and compares new evidence with past claims. It may append a structured `lab_memory_review` block. Parsing admits only selected memory IDs/versions and evidence from supplied source IDs or public URL strings. These references remain model claims, not proof that a URL was read. Malformed proposals do not invalidate a completed report. Proposals never silently rewrite memory. The owner separately accepts or dismisses each proposal, with version checks preventing old proposals from replacing newer edits. Accepting an evidenced update or confirmation appends a revision with the new research evidence and refreshes its review date.

Refreshing a finding creates a new plan with web search, the prior claim and its source material; it still requires explicit approval. There is no scheduled crawling or automatic spending. Scientific memory is untrusted data, distinct from owner preferences, and cannot expand tool permissions.

SQLite migration is additive and idempotent. Historical plan hashes remain intact; a legacy unapproved plan must be rebuilt to obtain a visible memory snapshot. Backup schema 2 includes all memory revisions and reviews while excluding credentials. Legacy schema 1 restores are supported. Restore validates shape, versions and cross-links inside one transaction and requires an empty destination, including owner memory.

## Verification and limits

Unit, HTTP and browser checks use temporary labelled fixtures and a fake executor. They cover frozen prompt equivalence, stale approval rejection, exclusions, Unicode retrieval, owner edits/history, proposal validation/acceptance, date-based refresh and backup migration/rollback. Ordinary research still uses one executor invocation; memory retrieval and owner decisions use none. Real model quality and completeness of contradiction discovery are not established by fixture tests.

This increment does not implement experimental reproduction, an independent scientific judge, semantic embeddings, autonomous monitoring or the original full alpha acceptance matrix.
