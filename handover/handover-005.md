# Handover 005

## What Was Done

- Continued the release self-audit beyond the prior green suite and added regression tests before fixing newly found issues.
- Preserved cumulative resume receipt history, retained sources, counters, and original approved URL hashes when completing or failing a pending job.
- Added strict receipt-source validation and complete job schema/count/hash checks before snapshot requests.
- Fixed CLI persistence of failed resume receipts, job-level failed exit codes, malformed `--sources` base-input handling, and strict import-library validation.
- Made ambiguous missing-URL, malformed provider error-code, and excluded invalid records partial/failed as appropriate; stopped later jobs truthfully.
- Added an absolute monotonic socket read deadline, known overflow distinction, duplicate live page-source ID rejection, empty-userinfo URL rejection, and shared 50,000-character page bounds for both live and imported pages.
- Removed the remaining `excerpt_id` citation alias and fixed long evidence excerpts so the full matched fact remains in the cited <=240-character quote.
- Added deterministic/environment-independence, successful resume history, import/collection library, failure receipt, socket deadline, provider malformed-data, and source limit regressions.

## Current State

- Current pinned Python 3.12 offline suite: 139 tests passing; final clean-tree run passed in 1.99 seconds.
- Final wheel SHA-256 `4ff8095a6fa97b99eaeb875e20cbc5da7c960c343c83fcbf0f83caf588c3f925`; offline install, CLI help/version, and installed fixture analysis succeeded.
- No authenticated provider request, live paid call, remote creation, commit, push, or publication occurred.
- Python 3.11 is unavailable locally; its CI matrix job remains required.
- Bright Data live behavior and Web Unlocker response compatibility remain unverified.

## Open Issues / Release Gates

- Independent code/QA/security/brand review was attempted again but reviewer dispatch remains blocked by the environment's `subagent_depth` limit. No independent approval is claimed.
- CI must run the pinned suite on both Python 3.11 and 3.12; a real non-root permission-denial check remains useful additional evidence.
- No live smoke test or publication until independent review and separate user authorization.

## Next Steps

1. Retry independent review when reviewer dispatch is available.
2. Keep live calls and publication blocked until independent release approval.

## Decisions Made

- A resumed receipt is cumulative; changing pending to complete/failed must not discard earlier job history or mutate the original approved URL hash.
- Invalid evidence records do not silently turn a partially usable batch into a complete result.
- Page evidence excerpts retain the complete matched phrase even when the surrounding source block exceeds the citation limit.
