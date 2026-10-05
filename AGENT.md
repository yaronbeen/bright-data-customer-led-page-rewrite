# Agent Guide

## Start Here

Read the newest file in `/home/yaron/projects/bright-data-customer-led-page-rewrite/handover/`, review P0 items in `/home/yaron/projects/bright-data-customer-led-page-rewrite/TECH_DEBT.md`, and skim `/home/yaron/projects/bright-data-customer-led-page-rewrite/LEARNINGS.md`. Run the full offline suite before editing behavior.

## Purpose & Context

This Python 3.11+ CLI joins selected public buying-question language, one landing-page snapshot, and operator-approved product facts. It produces deterministic, cited rewrite suggestions without an LLM, automatic publishing, or outcome claims. Current status is offline implementation with live Bright Data behavior unverified against an account.

## Architecture / Design

```text
JSON input/library
      |
      v
core.py: validate -> normalize blocks -> exact matches -> report dict
      |                                      |
      v                                      v
export.py: Markdown + CSV              report.json

optional manifest -> brightdata.py plan/approval/transport -> source library
                              ^
cli.py: safe file I/O, atomic writes, explicit live gates
```

`core.analyze` is pure. `brightdata` is independently bounded and injectable for tests. `cli` alone reads files, environment variables, and the production transport. Never move network or environment access into analysis.

## Decisions Log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-10-05 | Use deterministic literal rules and approved text templates | Keeps every draft checkable and prevents audience claims from becoming product promises. |
| 2026-10-05 | Preserve narrow compatibility with the supplied historical fixture | The independent tests require omitted envelope fields and `retrieved_at`; new integrations use the final schema. |
| 2026-10-05 | Keep Bright Data optional and explicitly gated | Offline replay remains free of credentials/network and paid calls require manifest-bound approval. |
| 2026-10-05 | Consume each approval through an atomic local ledger | Prevents replay and concurrent reuse without storing credentials or URLs. |
| 2026-10-05 | Redact all URL query values in artifacts | Prevents signed URLs, tokens, and identifiers from leaking through plans, receipts, or reports. |
| 2026-10-05 | Treat Customer-Led as a workflow label, not an identity claim | Public-contributor evidence and operator selection do not establish customer status or buying intent. |
| 2026-10-05 | Keep Web Unlocker raw-only and fail closed on envelopes | Official feature examples and REST OpenAPI show conflicting response shapes; no live account check has resolved them. |
| 2026-10-05 | Require the finalized input/library/receipt schema | Removes the undocumented fixture-era bypass and makes replay validation checkable. |
| 2026-10-05 | Supersede fixture-era compatibility | The demo and acceptance paths now use the final envelope; the earlier compatibility decision remains historical only. |
| 2026-10-05 | Preserve completed work in safe failure receipts | Provider, parsing, and record errors stop later jobs while retaining completed sources and explicit `not_attempted` states. |

Append new decisions; do not rewrite old rows.

## Runbook / Operations

```bash
cd /home/yaron/projects/bright-data-customer-led-page-rewrite
python3 -m pytest -q
python3 -m customer_led_page_rewrite analyze fixtures/demo.json --out-dir /tmp/customer-led-page-rewrite-demo
python3 -m customer_led_page_rewrite analyze fixtures/demo.json --out-dir /tmp/check --dry-run
python3 -m customer_led_page_rewrite collect manifest.json --out /tmp/library.json --dry-run
```

Never authorize a real request from a keyword or discovered URL. Confirm exact URLs, target permission, account budget, zones, approval hash, expiry, aggregate retained-source bound, and writable approval ledger first. Approvals are single-use even when a call fails or remains pending. Pending jobs are resumed only with a new approval through an explicit one-shot `resume` command.

## API References

- <https://docs.brightdata.com/scraping-automation/web-unlocker/send-your-first-request>
- <https://docs.brightdata.com/scraping-automation/web-data-apis/web-scraper-api/overview>
- Build contract: `/home/yaron/.claude/data/brightdata-drafts/2026-10-04-five-project-build-contract.md`, §§1-4 and §7.

## Project File Structure

- `/home/yaron/projects/bright-data-customer-led-page-rewrite/customer_led_page_rewrite/core.py`: pure validation and decisions.
- `/home/yaron/projects/bright-data-customer-led-page-rewrite/customer_led_page_rewrite/export.py`: inert deterministic Markdown/CSV.
- `/home/yaron/projects/bright-data-customer-led-page-rewrite/customer_led_page_rewrite/brightdata.py`: provider normalization, planning, collection, resume, transport.
- `/home/yaron/projects/bright-data-customer-led-page-rewrite/customer_led_page_rewrite/security.py`: centralized query-key detection, URL redaction, and URL identity hashes.
- `/home/yaron/projects/bright-data-customer-led-page-rewrite/tests/test_contract_comprehensive.py`: PR01-PR10 and applicable common C01-C20 acceptance matrix.
- `/home/yaron/projects/bright-data-customer-led-page-rewrite/customer_led_page_rewrite/cli.py`: commands and atomic local files.
- `/home/yaron/projects/bright-data-customer-led-page-rewrite/fixtures/`: invented demo and generated expected artifacts.
- `/home/yaron/projects/bright-data-customer-led-page-rewrite/tests/`: original acceptance and security regression tests; do not weaken them.
- `/home/yaron/projects/bright-data-customer-led-page-rewrite/requirements-dev.lock`: pinned build/test dependencies for Python 3.11/3.12 validation.

## References

See `/home/yaron/projects/bright-data-customer-led-page-rewrite/LEARNINGS.md`, `/home/yaron/projects/bright-data-customer-led-page-rewrite/TECH_DEBT.md`, and `/home/yaron/projects/bright-data-customer-led-page-rewrite/handover/`.
