# ADR-0004: applied research tasks frozen with approval

Status: local implementation increment requested on 2026-10-21. Extends ADR-0002/0003; original alpha gates and experiment-plan schema remain unchanged.

The owner requested reusable business tasks, technology applicability, a baseline, evaluation metrics and self-hosted requirements shown together with selected memory before approval. The Harness² material is a concrete candidate for source analysis and design inspiration, not authorization for recursive paid runs or arbitrary third-party code execution.

## Decision

Add a versioned task catalog to the existing Python/SQLite application. A task records its business goal, beneficiary, inputs/output, constraints, current baseline, candidate versions, applicability/advantages/limitations, evaluation dataset/protocol and success criteria. Metrics separate target values from expected values and retain evidence levels/URLs. Self-hosted fields cover availability, license, runtime, CPU/RAM/GPU/VRAM/disk, context/concurrency, dependencies, operations, cost and per-candidate conditions. Unknown values stay explicit. The application does not label estimates or literature claims as its measurements.

Freeze a structured `study_context` in each new run alongside the memory snapshot. Both are included in the plan hash. Editing the selected task requires rebuilding the plan and fresh consent. Archived tasks cannot start new research; their historical snapshots remain intact. Free exploration remains possible with an explicit unconfigured task context. Rebuilding context or memory refreshes both consistently; execution reads only frozen data.

The question and task context inform local lexical memory retrieval. Past findings retain the task and conditions under which they were obtained. A shared topic or task does not establish experimental comparability: source analysis must report differences, missing conditions and uncertainty. The existing executor still performs a single bounded source-analysis call. There is no benchmark runner, local GPU execution, autonomous refinement or automatic model call to fill task fields.

Task revisions are additive database records. Backup schema 3 includes them; schemas 1 and 2 remain readable without rewriting historical plan hashes. Restore validates task histories, snapshots and links atomically and requires an empty destination including tasks/profile.

## Harness² reuse

Use the architectural ideas of explicit harness components, controlled candidate changes and evidence-backed retained lessons. A future Propose–Probe–Compose experiment would require frozen baseline/candidate configurations, shared cases, budget limits and a separate approval. Existing memory revisions and approvals supply the local foundation. No Harness² dependency or third-party executor is installed by this increment.

## Verification boundaries

Fixture unit/HTTP/browser checks cover task versioning, exact context-to-prompt transfer, stale approval rejection, memory selection, honest evidence labels, catalog reuse, self-hosted fields and backup migration/rollback. These checks establish application behavior, not scientific efficacy or hardware performance. The original experimental runner, measurement pipeline and alpha acceptance matrix remain separate work.
