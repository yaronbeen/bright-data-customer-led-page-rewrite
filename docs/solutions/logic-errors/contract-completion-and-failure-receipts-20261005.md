# Contract Completion And Failure Receipts

## Problem

The initial implementation passed the narrow acceptance suite but lacked full PR01-PR10/common-contract coverage. It retained a fixture-era schema bypass, joined page blocks during answer matching, case-folded approved fact support, scoped claim conflicts too narrowly, and raised provider/parse failures without preserving completed jobs. Source libraries and resume receipts were insufficiently strict.

## Symptoms

- A fact split across two blocks could be reported as present.
- Case-changed evidence could authorize product copy.
- An unreferenced contradictory approved fact did not block its claim key.
- Unavailable audience sources could produce `no_data` instead of `needs_review`.
- HTTP/JSON/record failures lost completed sources and later-job states.
- Malformed libraries or receipts could reach deeper code paths.
- Staleness used truncated integer days.

## Solution

- Migrated the demo and all normal paths to the finalized version-1 envelope and removed legacy conversion.
- Match each page block independently and emit actual `page_answer_refs`/`related_copy_refs`.
- Require one citation quote to equal the normalized fact text exactly, preserving case and punctuation.
- Compute approved `claim_key` conflicts globally.
- Return `failed` or `partial` collection libraries with completed sources, a safe failed job, and all later jobs `not_attempted`.
- Treat provider error records as stopping failures even under HTTP 200.
- Validate collection libraries and pending resume receipts with exact identities, keys, counts, hashes, and job shapes before network.
- Use parsed datetime subtraction and strict `> timedelta(days=30)`.
- Added a pinned development lock and portable/private-path documentation.
- Preserve resume job history and original approved URL hashes while updating a pending job; keep request and record counts cumulative.
- Treat record-ID booleans as invalid, enforce the shared 50,000-character page limit on both live and imported pages, and retain complete matching phrases inside bounded citations.
- Fail closed when optional analysis inputs are malformed, and force `needs_review` when an attached collection receipt has pending, empty, failed, or not-attempted work.

## Prevention

- Keep the PR01-PR10 and C01-C20 mapping executable in `tests/test_contract_comprehensive.py`.
- Never validate evidence by concatenating independently cited blocks.
- Treat receipts/libraries as security-sensitive replay inputs, not trusted internal objects.
- Preserve failure state as structured data so operators can reason about paid work without retrying blindly.
