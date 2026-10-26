# ADR-0005: exact application request context and scoped evidence lessons

Status: local implementation requested by the owner on 2026-10-21, following one approved Harness² source analysis. Recursion and the proposed 16-run pilot are explicitly deferred. No alpha gate is accepted by this increment.

## Decision

Freeze the exact application-authored research prompt in the plan before approval, together with a context manifest. The manifest identifies prompt/template/application/adapter code, selected source hashes, task and memory revisions, lessons, requested model, CLI executable fingerprint, tool configuration and execution limits. The outer approval hash binds this record. Execution uses these exact prompt bytes. A material local configuration/code change requires rebuilding the plan. Persist a dispatch context before invoking the executor. Expose the record locally with hashes and explicit coverage limits; credentials and process environment values are excluded.

The application cannot see every provider/CLI-internal instruction or future search-result token. It records the application request and configured permissions, plus available result usage and tool events. Requested default model and unreported actual model remain distinguishable. Earlier reports without a recorded exact prompt are marked unavailable; a reconstructed prompt must never be represented as the historical original.

Store lessons separately from full scientific reports and owner corrections. Each lesson has a versioned rule, observed problem, evidence notes/references, applicability conditions, exclusions, limitations and review date. Drafts may be incomplete. Active lessons require explicit supporting references and scope; they remain claims/hypotheses, not proof of general effectiveness. Active lessons can be proposed by local lexical/task retrieval and are frozen in the memory shown before approval. Selected edits, retirement or a freshness transition invalidate stale consent. Owner edits append history. There is no automatic model-generated truth promotion or extra paid call.

Backup schema 4 adds lesson history and dispatch contexts; schemas 1–3 remain supported with original hashes intact. Restore validates histories, evidence references, frozen lessons and context checksums atomically and refuses a nonempty destination. Runtime data stays local and is not served statically.

## Verification boundaries

Fixture tests cover exact prompt-to-executor equality, changed local configuration, context capture before dispatch, lesson inclusion/exclusion/version/freshness, evidence validation, history and backup migration/rollback. Browser checks verify readable evidence/scope and full context inspection. Existing Harness² results remain source analysis, not measured improvements. No recursive executor, benchmark or new model research is authorized by this increment.
