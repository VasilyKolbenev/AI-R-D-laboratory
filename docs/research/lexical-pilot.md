# Fixed lexical retrieval pilot

Task: retrieve relevant scientific abstracts for a query. Baseline TF-IDF cosine;
candidate BM25. This is a reusable CPU evaluation path for a retrieval component,
not validation of a neural model, QD-Rec, agent-memory policy or final RAG answers.

## Data and scope

Use every document and every test-qrel query in the official BEIR SciFact archive.
The inspected archive has 5,183 documents, 300 evaluated queries and 339 judgments;
the queries file also contains non-test queries which are not evaluated here.
Official archive MD5: `5f7d1de60b170fc8027bb7898e2efca1`.
Observed SHA-256: `536e14446a0ba56ed1398ab1055f39fe852686ecad24a6306c80c490fa8e0165`.
No corpus sampling, parameter tuning on test scores or result cherry-picking.

Data source: https://github.com/beir-cellar/beir
Original SciFact: Wadden et al., EMNLP 2020, https://github.com/allenai/scifact
BEIR conversion: Thakur et al., NeurIPS 2021 Datasets and Benchmarks.
Claims/annotations CC BY 4.0; abstracts from S2ORC under ODC-By 1.0.
https://github.com/allenai/scifact/blob/master/LICENSE.md

## Frozen comparison

Both arms use identical title plus text and Python regex word tokenization,
lowercase, no stopword removal, stemming, chunking or expansion. TF-IDF uses
sublinear term frequency, smoothed IDF and L2 cosine. BM25 uses k1=1.2, b=0.75,
positive Robertson IDF and a raw query-frequency multiplier. Ties sort by raw
document ID. Exact formulas and runtime identity are in the frozen plan.

Primary metric macro nDCG@10; secondary Recall@100 and MRR@10. Unjudged documents
count as nonrelevant, a limitation of this benchmark setting. Screening rule:
BM25 mean nDCG@10 must improve while mean Recall@100 does not fall. There is no
claim that this rule establishes business utility or an absolute quality floor.

One full untimed warmup per arm; then six measured full passes, alternating AB/BA,
one worker and no result cache. Report per-query medians and their p50/p95,
index construction separately, actual query count, all per-query metrics,
win/tie/loss and raw top100 rankings. Deterministic reruns are not independent
quality samples; no fabricated confidence interval is computed.

## Approval and persistence

Fetch plaintext data with `python tools/fetch_scifact.py`; no third-party code or
models are downloaded. Prepare the fixed plan in `/workbench/` → Experiments.
Preparation never executes the benchmark. An unchecked consent control and
explicit start are required. Host/Origin/CSRF and exact plan hashes are enforced.
The engine is bounded to 180 seconds, fixed input sizes and one execution. Memory
512 MiB is an estimate; local energy/ownership cost is unknown. External model
calls and API charges are zero. Runtime, code or data drift requires a new plan.

Immutable plan → approval → intent → result are content-addressed in the existing
research archive. An interrupted intent is not rerun. The large result is capped
at 4 MiB; raw/source/ranking/metric hashes and graph references are checked during
backup. Dataset files are covered by the normal full local backup.

Software tests use only small TEST_ONLY fixtures. They do not count as a SciFact
run. An actual run requires the owner's separate approval; source-review reports
retain their original scope regardless of this pilot's outcome.
