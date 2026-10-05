# Customer-Led Page Rewrite

> **Synthetic demonstration:** all cited source content in this report is invented fixture data.

> **Name and evidence scope:** Customer-Led is a workflow name. It does not establish customer identity or buying intent. The workflow uses public-contributor language selected by an operator.

**Decision:** `annotated_rewrite`  
**Status:** `needs_review`  
**Method:** `deterministic_rules_v1` / `approved_text_templates_v1`

Headline templates combine operator-supplied product/question text with approved fact text. FAQ answer drafts use approved fact text only. They are suggestions for human review, not conversion promises or verified customer consensus.

## Headline Alternatives

1. Harbor: Start with a CSV file; no browser extension is required\.
2. What do I need to get started? Start with a CSV file; no browser extension is required\.

## FAQ Edits

### What do I need to get started?

- Attribution: `observed`
- Selected section: Setup
- Page answer state: `no_matching_answer_in_selected_section`
- Suggested draft: Start with a CSV file; no browser extension is required\.
- Existing copy: “Bring your existing work into Harbor\.”

### Does it guarantee more sales?

- Attribution: `observed`
- Selected section: Results
- Page answer state: `no_matching_answer_in_selected_section`
- Suggested draft: [needs_approved_fact]
- Existing copy: “Designed for small teams\.”

## Proof Needed

- Approve a product fact before answering: Does it guarantee more sales?

## Bounded Scope

- Product: Harbor
- As of: 2026\-10\-04T10:00:00Z
- Source IDs: landing; q1; q2; fact\_note

## Evidence Appendix

- `landing/b0002` “Bring your existing work into Harbor\.” — https://example\.com/harbor; observed 2026\-10\-04T10:00:00Z; SHA-256 `388a67b4a99e0678e82ff810980ebf972a431dbc27ff2f0e41f8c5484965ef85`
- `q1/b0001` “What do I need to get started?” — https://example\.com/review/q1 \(record Q1\); observed 2026\-10\-04T10:00:00Z; SHA-256 `cfe3ef2804bd146424f54cb8861744d4cd44b32bbccf379249c56b95fea02703`
- `fact\_note/b0001` “Start with a CSV file; no browser extension is required\.” — operator note; observed 2026\-10\-04T10:00:00Z; SHA-256 `f5fbde6140530aa5d5df52903973d345f64ec9218850320ccf7f1684d374bd8e`
- `landing/b0004` “Designed for small teams\.” — https://example\.com/harbor; observed 2026\-10\-04T10:00:00Z; SHA-256 `388a67b4a99e0678e82ff810980ebf972a431dbc27ff2f0e41f8c5484965ef85`
- `q2/b0001` “Does it guarantee more sales?” — https://example\.com/review/q2 \(record Q2\); observed 2026\-10\-04T10:00:00Z; SHA-256 `4800b529f4fdf2afab66e2f72694c35c32c3d73d376100d79cf3c77fa00feec5`

## Limitations

Literal phrase rules can miss paraphrases. Public contributors are not assumed to be customers and their language does not establish buying intent. Topic questions and product names are operator-selected. Approved facts are operator attestations, not independently verified claims. Inspect free text for personal or sensitive information before sharing.
