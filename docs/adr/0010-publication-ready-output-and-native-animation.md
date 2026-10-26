# ADR-0010: clean publication output and native-resolution animation

Owner feedback on 2026-10-21: the GIF is blurry on a laptop; the bot must deliver a ready Telegram post under the agreed rules, without extra text. No new research is requested.

## Publication rules

The applied post keeps the agreed sequence: working problem, audience/use case, mechanism, author results and conditions, limitations, requirements/full cost, practical choice, next step and sources. Russian; maximum 3500 UTF-16 units, aiming at five-minute consumption including visuals. Preserve attribution, comparison conditions, unknowns and applicability boundaries. Do not promise the same benefit in another project.

Remove service completion messages, duplicate summaries, draft wrappers, internal source IDs, pipeline explanations and automatic report documents from successful Telegram delivery. Send one exact post body, a static infographic and an animation, without service captions. The research report, context, costs and journal remain in the knowledge base/web export. Channel publication remains manual; owner-only delivery is unchanged.

The versioned publication_rules contract is visible through the API and in the Telegram approval preview, and is included in the same-call prompt. A structurally incomplete, oversized or compacted post gets one operational notice, not a claim of publication readiness. No paid retry or repair is allowed.

## Blur and media

The old infographic GIF resized 1080px source to 720px and reduced the palette to 128 colours. A tall infographic also makes text small in a constrained animation preview. Keep the full infographic as PNG/SVG. Animate one comparison panel at native 1080px width, retaining its metric, labels, full conditions, limitation and source. Multiple metrics receive separate panels on one padded canvas; never crop conditions or imply a measured runtime. Numerical labels stay fixed while recorded values are revealed.

Export silent H.264 MP4 at CRF14/yuv420p, with faststart, using a pinned project-local FFmpeg binary from imageio-ffmpeg 0.6.0 and a verified SHA-256 sidecar. No global installation, model, network request or source-supplied command is used during export. The encoder is optional; GIF fallback keeps native width and 256 colours. Media remains bounded by the existing 8MiB transport limit. Telegram supports silent H.264 through sendAnimation; capture safe returned dimensions/MIME/size to distinguish the local asset from server-accepted media. Client preview sharpness still needs human evaluation.

## Verification

Check clean exact single-message delivery, no service captions/report attachment, incomplete/failed outcomes, partial-send replay protection, MP4 MIME and redacted media metadata. Verify native dimensions, actual H.264 decode, image quality against the original text frame, GIF fallback and absent/tampered encoder. Use fake Telegram and no providers in tests. Reformat/resend the existing completed Anthropic report once; preserve original research output, approval, usage and journal.

The full suite exposed an existing Windows loopback reset when an early Origin/CSRF 403 closed a socket before the POST body arrived. The two rejection paths now discard a valid declared body up to 64 KiB within a 200ms deadline, without parsing JSON or changing state; access checks are unchanged. Regression tests cover a fragmented body, bounded waiting and absence of mutation.
