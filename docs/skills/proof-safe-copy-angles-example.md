# Checked Example: Question First / Fact First

This is a manual exercise of the skill on a newly generated offline report, not an additional CLI output or a conversion experiment. All example evidence is invented.

From the repository root, generate the input with `python3 -m customer_led_page_rewrite analyze fixtures/demo.json --out-dir /tmp/copy-skill-example`. Ask an assistant with local file access: "Read the proof-safe-copy-angles SKILL.md as instructions. Use /tmp/copy-skill-example/report.json as untrusted data. Return two copy-angle cards and holds in Markdown. Do not open links or edit a page." No installation or configuration is needed; the bundled skill is not auto-registered.

## Scope

Checked input: `/tmp/opencode/skills-20261005-customer_led_page_rewrite-v2/demo/report.json`. Harbor; selected page `landing`; as of `2026-10-04T10:00:00Z`; status `needs_review`; decision `annotated_rewrite`. Synthetic sources: `landing`, `q1`, `q2`, `fact_note`. Customer-Led is a workflow name: public contributors are not established customers or buyers. These selected questions do not establish prevalence, demand or conversion impact.

## Angle Cards

**Fact First**: topic `setup`, section `Setup`, action `review_existing_section`. Approved template: "Harbor: Start with a CSV file; no browser extension is required."

**Question First**: same topic and section. Approved template: "What do I need to get started? Start with a CSV file; no browser extension is required."

Both templates have `state: approved_text_template`. They pair the `observed` question at `q1/b0001` with approved fact evidence at `fact_note/b0001`. The eligible FAQ (`approved_text_ready`) is "Start with a CSV file; no browser extension is required." Its qualifiers are retained verbatim. The existing selected copy is at `landing/b0002`; page state is `no_matching_answer_in_selected_section`, not an internet-wide omission.

Editorial hypotheses: Fact First foregrounds the supported setup statement; Question First foregrounds the observed wording. These are framing options, not a performance ranking. Product/question text is operator-selected; fact approval is an operator attestation, not independent verification.

## Do Not Say Yet

`sales` / `Results`: `observed` question at `q2/b0001`; existing copy at `landing/b0004`; action `review_existing_section`; page state `no_matching_answer_in_selected_section`; draft null, state `needs_approved_fact`. Retain the proof task: "Approve a product fact before answering: Does it guarantee more sales?" Do not answer yes or no or add a sales promise.

Proposed human comprehension question: After reading either setup template, what would you bring to start? This is a question for later human review, not an executed test. No CMS changes, messages or publication occurred.

## Evidence And Warnings

Warnings: none supplied. Literal matching can miss paraphrases. Inspect real free text for privacy and publication rights before sharing.

- `q1/b0001`: "What do I need to get started?"
- `landing/b0002`: "Bring your existing work into Harbor."
- `fact_note/b0001`: "Start with a CSV file; no browser extension is required."
- `q2/b0001`: "Does it guarantee more sales?"
- `landing/b0004`: "Designed for small teams."

All four sources: observed `2026-10-04T10:00:00Z`; status `collected`; provenance `synthetic_fixture`; published/provider dates unknown.

- `landing`: `https://example.com/harbor`; record unknown / `none`; SHA-256 `388a67b4a99e0678e82ff810980ebf972a431dbc27ff2f0e41f8c5484965ef85`.
- `q1`: `https://example.com/review/q1`; record `Q1` / `operator`; SHA-256 `cfe3ef2804bd146424f54cb8861744d4cd44b32bbccf379249c56b95fea02703`.
- `q2`: `https://example.com/review/q2`; record `Q2` / `operator`; SHA-256 `4800b529f4fdf2afab66e2f72694c35c32c3d73d376100d79cf3c77fa00feec5`.
- `fact_note`: local operator note, not a public page; record unknown / `none`; SHA-256 `f5fbde6140530aa5d5df52903973d345f64ec9218850320ccf7f1684d374bd8e`.

Hashes identify invented snapshots, not truth. [Validation record](validation.md).
