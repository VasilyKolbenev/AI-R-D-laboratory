# ADR-0009: comparison, application and limits as the visual front page

Owner direction, 2026-10-21: the text of the live Anthropic code-review report is acceptable; the visual needs to be more useful and engaging. The owner selected an infographic showing comparison, benefit/application and limitations.

Use a light editorial visual hierarchy: headline and working problem; evidence-linked numeric comparisons with adjacent conditions; application and limits; setup/cost requirements; next check; origins. Percent shares within 0–100 use two rings on the same scale. Other metrics use two values with a shared zero-based bar scale. Never turn a count into a percentage or an absent value into zero. Use the report's audience and use case rather than inventing a measured benefit. The first two limitations and resource items form the visual overview; the full original post/report retains all items.

For the completed Anthropic case, 16→54% is coverage by substantive comments in an author's internal preview comparison. It is not accuracy, defect recall or a causal estimate of production quality. The conditions and evidence limitation stay beside the numbers. Do not combine March preview data with the October internal process as one experiment.

Render from existing structured data without modifying the immutable research output, post text, journal, approval or usage. No new provider call, model formatting pass or hand-written per-report editorial revision. Existing custom legacy visuals remain available. For new structured stories the infographic is the primary PNG/SVG, and the numerical reveal is an optional GIF. Animation reveals the recorded values; labels stay fixed and motion never denotes runtime or actual experiment progress.

The result UI presents the infographic first, with a full-size link and SVG fallback. The technical mechanism player remains in a collapsed disclosure. Retain desktop/mobile/reduced-motion behaviour. This changes derived presentation only, not research facts, the backup schema or scientific acceptance gates.
