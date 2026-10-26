# AI R&D Laboratory — contributor guidance

Read `AGENTS.md`, `README.md`, and the task supplied by the owner before changing
code. These instructions apply to either coding agent; no second agent or paid
model invocation is required to develop the project.

The current product is a local, single-owner Windows alpha. `laboratory/`
contains the implementation. `deliverables/ui/frontier-instrument/` contains the
live workbench. Earlier architecture and interface proposals in `deliverables/`
are historical design material, not promises about the current runtime.

Preserve immutable plans, approvals, evidence, usage records and publication
packages. Opening the application, running tests, installing dependencies or
preparing a release must never approve a study or publish a Telegram post.
Unknown external outcomes must not trigger automatic paid retries.

Use synthetic `TEST_ONLY` fixtures for tests. A source review is not an executed
technology benchmark. The fixed lexical CPU runner validates only its declared
retrieval task and dataset. Do not infer production isolation or scientific
truth from passing software tests.

Before publishing, run the release checks described in `CONTRIBUTING.md` and
build a clean archive using `tools/build_local_release.py`. Never add runtime
databases, tokens, CLI authentication, owner research or local operation logs.
Report actual checks, remaining limitations, and any change to a public contract.
