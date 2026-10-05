# Brand Provenance And Provider Contract Truthfulness

## Problem

The workflow name and documentation could be read as establishing that public contributors were customers with buying intent. Documentation also overstated deterministic drafting by implying every output word came from approved facts, even though headline templates include operator-supplied product/question text. Synthetic banners inspected every indexed source rather than only cited evidence. Web Unlocker documentation was described too definitively despite conflicting official raw-text examples and JSON-envelope OpenAPI modeling.

## Symptoms

- `Customer-Led` sounded like an identity classification rather than a workflow label.
- The README said draft words came only from approved facts while headlines added operator text.
- An uncited synthetic source could label an otherwise real-only report synthetic.
- Mixed cited evidence had no mixed-provenance warning.
- Web Unlocker could appear live-compatible without an authorized smoke test.

## Solution

- State prominently that Customer-Led is a workflow name and does not establish customer identity or buying intent.
- Describe public-contributor language as operator-selected.
- Distinguish headline templates (operator product/question plus approved fact) from FAQ answer drafts (approved facts only).
- Build provenance banners from cited source IDs: all synthetic, mixed, or no synthetic banner.
- Keep Web Unlocker raw-only and reject an apparent envelope with `response_contract_mismatch` until live verification resolves the documentation conflict.
- Pin current scraper adapter names and IDs in executable tests and link directly to official endpoint references.

## Prevention

- Test every brand/identity claim as an assertion over README and generated artifacts.
- Derive report-level provenance only from evidence that is actually cited.
- Separate mock-verified request serialization from live provider compatibility.
- Recheck product names, dataset IDs, and official response examples before release.
