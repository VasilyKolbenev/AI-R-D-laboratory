# ADR-0006: Telegram approval and compact research presentation

Status: bounded local implementation requested by the owner on 2026-10-21. No alpha gate is accepted by this increment.

## Decision

Extend the paired owner's private bot conversation from intake to plan preview, explicit button approval and delivery. Forwarding material and preparing or formatting a plan do not invoke an AI provider. Execution continues through the same Laboratory.start_run and Store.approve path used by the local interface: exact immutable plan hash, current task/memory/lesson/context checks, one concurrent run, rolling daily limit and no automatic research retry after uncertain outcomes.

Send the frozen task and selected memory/lessons before the approval message. Callback authorization binds the paired actor, private conversation, bot identity, originating message and unpredictable workflow handle to one plan hash. Incomplete previews cannot authorize execution. Changed or repeated buttons do not create a new research run. Workflow and notification receipts persist locally in operational settings. They are excluded from portable scientific backups, together with bot credentials; restoring a backup never restores active bot buttons. The historical source, plan, approval timestamp, command ID, exact dispatched context and report remain in the scientific records.

For Telegram-approved completed runs, save the full original report and provenance in the knowledge base idempotently before attempting result delivery. Deliver only to the paired owner. Telegram delivery and research execution have separate outcomes: a network error must not trigger another research call. Ambiguous outbound delivery may require an explicit result retrieval; the product does not promise exactly-once Telegram messages.

## Presentation and channel drafts

A research run may return one bounded lab_presentation JSON block alongside the report and memory comparison block. This adds no separate model invocation. Treat all fields as untrusted text, validate shape/length and use only filtered public source URLs. The original provider answer remains unchanged. Reports produced by older versions use a visibly labelled deterministic extract; missing information stays unknown rather than becoming a generated conclusion.

The local result opens with a concise decision, applicability, advantages, limitations, metrics, setup and infrastructure, then the original full report. A compact visual storyboard explains the mechanism. SVG works with the standard library; optional Pillow produces PNG and a schematic GIF for Telegram. Animation is educational, never a fabricated performance measurement; browser playback can be paused and respects reduced-motion preferences.

Generate a Telegram channel post draft locally from the same presentation. The draft contains source references and uncertainty, without the private owner's profile, private chat identifiers or runtime diagnostics. This increment does not publish to a channel or connect a channel account. Export and delivery to the owner's bot are separate from publication.

## Verification boundaries

Use fake Telegram transports and fake research runners for callback authorization, stale/duplicate approval, preview failure, idempotent knowledge saving, post limits, media and recovery tests. Use isolated data and browser contexts for responsive UI and animation/export checks. A live smoke may deliver the previously approved speculative-decoding report to the paired owner; it must not repeat that research. Token and pairing values remain in the existing local secret storage and never enter test fixtures or exported evidence.

This is source analysis, not benchmark execution or a reproduced speedup. CLI-reported token usage does not enforce a percentage of the weekly account limit. The bot works while the local application and computer are running.


## Live intake correction (0.6.1)

The first human-driven Telegram trial exposed split media intake: a caption/source and a separate unread image produced two plans. The owner approved the last image-only plan, so the provider returned an input-unavailable report. Preserve that original answer and actual usage; retire its knowledge revision as a technical failure rather than scientific knowledge. Do not claim the intended technology was researched or refund observed quota.

An unread attachment without meaningful caption text or a URL is now stored with provenance but cannot produce an automatic research plan or approval button, including the direct workflow preparation path and replays. Caption/link plus an unread attachment notice remains valid. The prior meaningful plan remains the latest selectable session. Each final approval message also names its source materials. No image OCR or media-group merge is claimed by this fix. A new version of the text plan and fresh owner approval are required after the update.
