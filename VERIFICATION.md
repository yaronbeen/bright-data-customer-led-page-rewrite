# Verification

Verification date: 2026-10-05. All commands ran from `/home/yaron/projects/bright-data-customer-led-page-rewrite`. No authenticated or target-network request was made.

## Automated Suite

```text
$ python3 -m pytest -q
........................................................................ [ 46%]
........................................................................ [ 93%]
..........                                                               [100%]
154 passed in 1.85s
```

The unchanged original acceptance file contributes 11 passing cases. `/home/yaron/projects/bright-data-customer-led-page-rewrite/tests/test_security_regressions.py` adds executable coverage for:

- sequential and concurrent approval replay with exactly one recording-transport call;
- secret-free atomic ledger markers;
- page plus dataset and resume aggregate retention preflight with zero requests;
- encoded/vendor query keys, no-query live page policy, and query-value redaction;
- exact approved-parent binding and arbitrary tracker/profile URL exclusion;
- inert single-line Markdown across links, images, headings, emphasis, blockquotes, code, backslashes, tables, HTML, and multiline input;
- CSV formula operators with controls, BOM, zero-width prefixes, and fullwidth compatibility forms;
- exact Web Unlocker request method, URL, JSON body, timeout, and token omission from outputs;
- HTTP 429 `rate_limited` plus numeric `Retry-After` with one call and no retry;
- atomic report collision protection, rollback after an injected commit failure, and exclusive output reservation across paid operations.

`/home/yaron/projects/bright-data-customer-led-page-rewrite/tests/test_brand_regressions.py` adds executable coverage for:

- neutral Customer-Led workflow naming without customer-identity or buying-intent inference;
- truthful headline versus FAQ deterministic-template inputs;
- synthetic, mixed, and real-only banners based only on cited sources;
- fail-closed rejection of an apparent Web Unlocker response envelope;
- exact `Amazon Reviews Scraper API` and `YouTube Comments Scraper API` adapter names;
- pinned Amazon reviews `gd_le8e811kzy4ggddlq` and YouTube comments `gd_lk9q0ew71spt1mxywf` request URLs and bodies;
- direct official documentation links for both scraper endpoints and both conflicting Web Unlocker references.
- detached CSV rows disclose synthetic-only, non-synthetic, mixed-cited, unknown, and uncited provenance without relying on a Markdown banner.
- uncited CSV rows report `contains_synthetic_data=unknown`; `false` is reserved for rows with known citations and no synthetic source.
- credential-shaped provider review/comment IDs are absent from collection JSON, analysis JSON, Markdown, and CSV for Amazon and YouTube; persisted/report-facing provider IDs are deterministic SHA-256-derived opaque identifiers.
- YouTube resume rejects redacted-target receipts before transport, including when the stored target hash and its unkeyed binding are both recomputed; Amazon resume checks every canonical URL hash inside the URL loop.
- malformed hash/binding list entries and non-string JSON job kind/state values produce `BrightDataError(invalid_receipt)` before transport; CLI probes return structured JSON without a traceback.

`/home/yaron/projects/bright-data-customer-led-page-rewrite/tests/test_contract_comprehensive.py` covers PR01-PR10 and the applicable common C01-C20 matrix, including:

- finalized analysis fixtures with no legacy envelope or `retrieved_at` bypass;
- exact-answer suppression, related-copy-only behavior, absent facts, global claim conflicts, operator framing, raw success-claim isolation, missing/duplicate headings, no audience data, and unavailable page/source review states;
- block-local page matching with actual hit citations and exact fact evidence preserving case, punctuation, and qualifiers;
- exact 30-day staleness and project role-count limits;
- safe source-library validation and strict pending resume receipt/job/hash/count validation;
- CLI output reservation before network, live dry-run, module help/version, collision preservation, and private output paths;
- failed/partial receipts, safe current-job error codes, later `not_attempted` jobs, error records under HTTP 200, redirects, NDJSON, overflow, timeout, zero results, and over-return;
- missing approval/key/zone gates, unsafe target rejection, metadata omission, scope/method/evidence/limitation rendering, and network-free pure analysis.
- CLI persistence of safe failed receipts for fail-closed provider errors before exit 3.
- attached incomplete/empty collection libraries cannot be reported as no-data/complete; successful offline imports and fake collected libraries validate and merge explicitly.
- resume preserves prior jobs and approved URL hashes, strict receipt count consistency, long facts remain whole inside evidence excerpts, malformed bool record IDs are excluded, and live/imported Markdown enforce the shared 50,000-character cap.
- latest continuation regressions: strict resumed-source/receipt validation, cumulative resume job history and approved URL hash preservation, resume parse/provider-error receipts, malformed optional input with `--sources`, safe provider ID types, shared page character caps, full evidence-hit citation excerpts, and monotonic socket timeout enforcement.
- multi-input resume tampering is tested at each URL position for both Amazon and YouTube; every altered receipt is rejected before transport.
- attached pending/empty/failed collection libraries force `needs_review` and surface a Markdown warning rather than producing false `no_data` conclusions.

## Additional Commands

The final verification pass produced:

```text
$ python3 -m py_compile customer_led_page_rewrite/*.py
[no output; exit 0]

$ python3 -m customer_led_page_rewrite analyze fixtures/demo.json --out-dir /tmp/customer-led-malformed-receipt-final --overwrite
{"decision": "annotated_rewrite", "requests_made": 0, "status": "needs_review"}

$ cmp fixtures/expected/report.json /tmp/customer-led-malformed-receipt-final/report.json
$ cmp fixtures/expected/rewrite.md /tmp/customer-led-malformed-receipt-final/rewrite.md
$ cmp fixtures/expected/rewrite.csv /tmp/customer-led-malformed-receipt-final/rewrite.csv
[all exit 0; byte-identical]

$ /tmp/customer-led-release-venv/bin/python -m pip install --no-index -r requirements-dev.lock
All six pinned build/test dependencies satisfied exactly.

$ python3 -m pip wheel --no-build-isolation --no-deps --wheel-dir /tmp/customer-led-malformed-receipt-wheels .
Created wheel: bright_data_customer_led_page_rewrite-0.1.0-py3-none-any.whl
SHA-256: 48fb060d70df28b3ddc5f300ce09c6c03d3c58d0c862d755662b2737e6c854c7

$ /tmp/customer-led-malformed-receipt-venv/bin/python -m pip install --no-build-isolation --no-deps --no-index --find-links /tmp/customer-led-malformed-receipt-wheels bright-data-customer-led-page-rewrite==0.1.0
Successfully installed bright-data-customer-led-page-rewrite-0.1.0

$ /tmp/customer-led-malformed-receipt-venv/bin/customer-led-page-rewrite analyze fixtures/demo.json --out-dir /tmp/customer-led-malformed-receipt-installed --overwrite
{"decision": "annotated_rewrite", "requests_made": 0, "status": "needs_review"}
$ cmp fixtures/expected/report.json /tmp/customer-led-malformed-receipt-installed/report.json
$ cmp fixtures/expected/rewrite.md /tmp/customer-led-malformed-receipt-installed/rewrite.md
$ cmp fixtures/expected/rewrite.csv /tmp/customer-led-malformed-receipt-installed/rewrite.csv
[all exit 0; byte-identical]
```

The same source analysis command generated all three artifacts, each byte-identical to its expected fixture. The latest full suite rerun is the 154-test run recorded above.

The latest wheel build left `build/` and `bright_data_customer_led_page_rewrite.egg-info/` in the workspace; they were not removed during this verification. Python 3.11 CI remains unverified locally and must still pass the configured Python 3.11 CI job.

## Security Scope

The approval JSON schema remains unchanged. Direct Python calls to `collect` and `resume` now require `ledger_path`; CLI calls derive `<approval-file>.ledger/`. Plans, receipts, normalized libraries, reports, Markdown, and CSV redact URL query values. The actual approved URL remains only in operator input and the in-memory outbound request.

Live provider response shape, account entitlement, actual billing, DNS behavior, and target permission remain unverified. These tests use injected recording transports and do not imply Bright Data endorsement or production validation.

The Web Unlocker adapter intentionally accepts direct UTF-8 Markdown and rejects an apparent `{status_code, headers, body}` envelope as `response_contract_mismatch`. Official feature examples treat `format: raw` as response text, while the REST OpenAPI models a JSON envelope. This suite proves fail-closed local behavior, not live compatibility with either account/zone response.

## Independent Review Status

- QA: APPROVE on the 150-test review revision, as reported by the user.
- Bright Data brand: APPROVE on the 150-test review revision, as reported by the user.
- Security: APPROVE on the final 154-test revision, including validation of malformed resume receipts, as reported by the user. The four subsequent tests cover malformed receipt value types and structured CLI failure behavior; no production code changed after the 150-test QA/brand review.
- The repository name and public-repository destination `yaronbeen/bright-data-customer-led-page-rewrite` are specified in `/home/yaron/.claude/data/brightdata-drafts/2026-10-04-five-project-build-contract.md`, line 15.

These approvals cover the stated code/review revisions. They do not verify live provider behavior, account entitlement, billing, DNS/target behavior, or production use. No live Bright Data request was made or is part of this publication.
