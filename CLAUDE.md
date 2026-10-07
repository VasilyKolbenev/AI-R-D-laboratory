# AI R&D Laboratory

The user is the product owner. Claude Code is the implementation developer. Codex is the technical lead and reviewer. The user manually transfers task briefs and review results between them.

## Accepted direction

- Deliver a private alpha, targeting 4–5 weeks from implementation kickoff. This is a target, not measured capacity or a release guarantee.
- Keep all alpha acceptance gates G0–G7. A missing gate changes the forecast; it must not be silently removed.
- Constellation v2 is the approved UI direction. The HTML is a synthetic prototype, not an implemented application backend.
- The planned alpha includes three executable method packs: DecisionStructure, MemoryRetrieval and ToolUseRecovery. The larger technology catalog does not imply executors for every category.

## Read before implementation

1. The specific current task supplied by the user. Initial brief: `deliverables/docs/claude-task-001.html`.
2. `deliverables/docs/implementation-plan.html`, especially scope, invariants, stages, schedule and release gates.
3. `deliverables/docs/architecture.html` and the relevant contracts in `deliverables/architecture/`.
4. `deliverables/architecture/alpha-acceptance.json` for requirement IDs and expected acceptance evidence.
5. `deliverables/ui/03-constellation.html` when implementing UI. Preserve the approved reference artifact.

## Execution and review

Work on the assigned bounded task, respecting existing changes. Before changing shared contracts, explain the reason and record an ADR for technical review. Do not implement the entire roadmap in one task. Later explicit user instructions take precedence over this workflow.

Keep synthetic fixtures separate from measured provider results. Product approvals must bind to an immutable plan version and budget. Provider timeouts with an unknown external outcome must not trigger an automatic paid duplicate. Preserve raw evidence, including failures and partial runs.

TASK-001 uses a deterministic fake provider and must require neither credentials nor paid calls. For later real pilots, use only the budget and scope explicitly authorized by the user. Do not put secrets into source, task reports or operational logs.

Return a concise handoff with changed files, exact reproduction commands, actual test outcomes, known limitations, proposed contract changes and any pending dependency. Do not label a gate accepted based solely on your own implementation report; Codex reviews the code and evidence, and the user evaluates product usefulness. A green unit test does not establish production sandbox isolation, billing reconciliation or full end-to-end readiness.
