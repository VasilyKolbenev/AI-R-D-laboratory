# ADR-0012: explicitly connect a verified Telegram channel

The owner requested channel creation and connection after the v0.10 queue was installed. Channel connection remains separate from research and from approval of an exact publication package.

Expose POST `/api/publication/channel` with exactly one field, `channel`: a strict public `@username` of 5–32 ASCII letters/digits/underscores, or a negative integer channel ID. The existing localhost Host/Origin and CSRF checks apply. No credentials are accepted by this endpoint.

Resolve through `getChat`, require a negative numeric ID and `type=channel`, and reject a mismatched ID or public address. Then inspect `getChatMember` for the already configured bot ID. The returned member must be that same bot, be an administrator, and have `can_post_messages=true`. Private chats, groups, missing rights, unknown bot identity, invalid replies and network failures leave the previous configuration and queue untouched. No `getMe` or credential-file access is needed: the existing Telegram connection already obtained and retained the bot identity.

Commit a changed target and invalidation of old queued approvals in one SQLite transaction. An unbound or previously different target never inherits a publication approval. Reconnecting the same verified identity is idempotent; a display-title change alone does not authorize a different destination or invalidate a package bound to the same numeric channel ID. The scheduler still needs its own enabled schedule and a fresh exact-package approval; connection alone sends no posts and invokes no models.

Verification uses fake Telegram responses and an isolated local HTTP server. Check strict inputs, channel and bot IDs, posting rights, connection failure without mutation, idempotence, channel changes, CSRF enforcement and absence of outbound publications or provider calls. Live owner evaluation and a separately approved scheduled post remain necessary before claiming the end-to-end channel flow is working.
