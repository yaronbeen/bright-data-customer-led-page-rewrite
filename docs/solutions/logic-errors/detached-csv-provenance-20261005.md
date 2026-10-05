# Detached CSV Provenance

## Problem

The Markdown report disclosed synthetic data, but its standalone CSV omitted provenance. A recipient could detach the CSV and mistake invented fixture evidence for collected source evidence.

## Solution

- Add `provenance_state` and `contains_synthetic_data` columns to every CSV row.
- Derive them from only that row's cited source IDs.
- Distinguish `synthetic`, `non_synthetic`, `mixed`, `unknown`, and `uncited`; never infer row provenance from uncited sources elsewhere in the report.
- Regenerate the CSV fixture and test synthetic-only, non-synthetic-only, mixed, uncited, and uncited-synthetic cases.

## Prevention

Treat each exported file as an independent publication artifact. Report-level disclaimers do not travel with detached CSV/JSON files; place relevant provenance beside the rows that carry evidence.
