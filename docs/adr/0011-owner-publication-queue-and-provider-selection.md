# ADR-0011: per-material executor and a separate publication approval

The owner explicitly requested Codex/Claude selection in Telegram, approval of a completed post with an enqueue button, and scheduled publication. The channel will be connected separately. On 2026-10-21 the owner chose to select days/time later; defaults must remain disabled with an empty schedule and no channel. New research and automatic paid retries are outside this task.

## Separate permissions

Research approval binds to the immutable task, memory, executor, context and budget. Changing executor creates a fresh planned run, invalidates the old approval, resets an executor-specific model override, and does not invoke a provider or change global defaults.

Publication is a different permission. The owner sees the exact text, PNG and MP4 before the enqueue control is issued. The control binds to the preview message, owner/bot identity and frozen package. A Telegram research approval never publishes to a channel. A later channel connection cannot silently grant a previously targetless approval permission to post into a new destination.

## Durable publishing

Keep operational queue/config separate from portable research backup and from delivery-to-owner states. Persist a package digest, generated media and receipts. Changed content or media must be reviewed again. Missing channel/schedule blocks dispatch but allows collection of owner-approved content. The channel-connection operation is deliberately not exposed in this step.

Publish at configured Moscow slots using existing bot transport. Empty queues do not initiate research; missed slots do not cause a catch-up burst. Persist sending intent before the first network request and confirmed message IDs after each accepted element. An interrupted or ambiguous send becomes uncertain and does not auto-repeat. No claim of absolute exactly-once delivery is made.

Keep the accepted delivery format: one post text, PNG and silent MP4, no service captions in the public payload. The separate enqueue control is an owner-only operational message. Do not introduce a new rich-message transport as part of this change.

## Scope and validation

Expose scheduling and queue state in local settings, with empty scheduling defaults. Validate weekday/time and reject channel changes through the schedule endpoint. The app must clearly state when channel/slots are missing and that laptop-based dispatch requires the app to remain running.

Use deterministic fake providers, fake Telegram and a controlled clock for tests. Verify stale/foreign/replayed callbacks, executor changes, exact package binding, missing configuration, schedule/clock boundaries, queue reservation, restart and partial delivery. Validate against the completed Anthropic report without launching new research or publishing to a channel.

## Branding

The owner reopened the name/logo decision and now wants a personal brand with their name and an expressive mark. The former name and monogram remain historical drafts; remove them as active memory guidance. Branding must not change an already approved publication package silently.
