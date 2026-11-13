# VisualSpec v1

VisualSpec is a pure read model over saved research and corpus data. It separates
the semantic question, available evidence and chosen display from a preferred
third-party engine. It performs no model call, source fetch, write or render job.

## Data contract

`version: visual-spec-v1` and `selector.version: visual-selector-v1` identify the
contract and deterministic selection rules. `subject`, `input_binding` and
`input_digest` bind it to the exact report/plan/presentation/readiness/sources, or
the corpus snapshot and overview. Wall-clock time is not added. Equal inputs
produce equal plans; changes in inputs produce a new digest.

`primary_block_id` points to a block. `read_order` is task → main figure →
comparison → applicability → evidence. The first task summary may include the
audience and quick takeaway; full requirements and limits follow the figures.
Each block records its semantic `kind`, selection/availability, reason, required
capability, preferred engine, supported renderer, data/source references,
provenance, assumptions and accepted display data. Deferred choices retain their
missing-input reason. Presentation metadata is not written into old approvals.

## Selection rules

| Input | Selected view | Required evidence |
|---|---|---|
| Comparable reported measurements | Comparison bars | Existing readiness `chart_eligible` and `source_bound_pair`, common conditions, finite supported values |
| Saved technology operations | Process flow | Valid bounded `dataflow-v1` nodes/edges; explicit saved-report/illustrative origin |
| Frozen corpus topic/year observations | Trend lines | Matched reproduction, unique years, distinct-paper numerators and positive eligible-paper denominators |
| Explicit typed source-bound relationships | Relationship graph | Deferred until an authoritative edge contract exists; memory context is not contradiction or causation |
| Executable mechanism model | Interactive explainer | Deferred without a formal model, assumptions and concrete renderer |
| Motion essential to explanation | Video | Deferred without a supported state/transition recipe and rendering capability |

Eligible numerical comparison is primary when available, otherwise saved process
flow, otherwise contextual summary. Missing comparison data are disclosed as a
gap, not zeros. A completed agent workflow does not establish scientific validity.

Corpus topic shares may overlap; they are not an exclusive whole suitable for a
pie or 100% stacked chart. Popularity and claim counts do not establish effectiveness.
The existing numerator/denominator/paper drilldown remains the evidence path.

## Engine boundary and UI

Visual Explainer informs the page composition; Infographic is preferred for
qualitative structures, G2 for quantities, G6 for relationships, custom components
for Polo Club-like mechanisms and Manim for optional exported motion.
These names are preferences, not evidence that a package is installed. Current
brief and corpus components use their existing native DOM/SVG adapters.

`GET /api/runs/{id}/research` and `GET /api/corpus` expose `visual_spec` alongside
the original data. No separate mutation endpoint is added. The UI consumes the
accepted block data, preserves defensive rendering checks, and shows the reason
in “Почему этот визуал”. Missing or unknown contract versions fall back
conservatively to existing saved-data views.

## Acceptance examples

- Saved SLEEP: conceptual process flow from the saved description; no quantitative
  advantage, verified formal simulator or new independent evidence is invented.
- Drift Inspector: prevalence trends tied to the immutable snapshot; shares,
  denominators and source articles remain inspectable, with imported unverified
  contribution extractions explicitly separate from the recomputed aggregates.
- No comparison field can bypass eligibility simply by claiming “comparable”.
- Planned, incomplete or malformed inputs cannot display finished research results.
