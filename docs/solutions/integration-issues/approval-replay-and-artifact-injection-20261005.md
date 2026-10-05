# Approval Replay And Artifact Injection Hardening

## Problem

The optional provider adapter validated an approval document but did not consume it, so the same attestation could be replayed or raced by concurrent processes. Retention preflight counted requested review/comment records but not pages or already-retained resume sources. Provider record URLs were accepted as citation URLs without binding them to approved batch inputs. Query values could survive in plans, receipts, and reports. Markdown HTML escaping did not neutralize Markdown links, images, headings, or multiline structure.

## Symptoms

- Reusing one approval could trigger another paid request.
- Two concurrent processes could both pass validation.
- A page plus dataset batch could retain more sources than `max_retained_records`.
- A provider record could substitute a profile/tracker URL.
- Encoded vendor credentials or signed-query values could leak into artifacts.
- Hostile evidence could create active Markdown structure despite HTML escaping.

## Failed Or Insufficient Approaches

- Manifest hashing binds scope but does not count or consume usage.
- Per-dataset retention limits ignore page sources and resume history.
- Generic HTTPS validation proves syntax, not relationship to an approved parent.
- A short sensitive-key list misses `X-Amz-*`, SAS, `access_token`, `apikey`, encoded keys, and unknown future names.
- HTML escaping alone does not disable Markdown syntax.

## Solution

- Atomically consume the SHA-256 of the complete approval JSON using a mode-0600 `O_CREAT|O_EXCL` marker before network. Keep consumed markers after every outcome.
- Hold an exclusive output-path reservation from preflight through network and atomic rename so a collision cannot appear after approval consumption or a paid call.
- Preflight `page_count + requested_dataset_records` for collect and `existing_sources + pending_requested_records` for resume; check again before append.
- Hash canonical approved input URLs and accept provider record URLs only when their hash matches. Use a sole parent only when the provider omitted the URL; reject omission for multi-input batches.
- Centralize repeatedly decoded/normalized query-key detection and redact every query value in generated artifacts. Reject every query on live page targets and preserve only narrow dataset syntax.
- Collapse untrusted Markdown fields to one line, HTML-encode them, and backslash-escape all active Markdown metacharacters.
- Normalize Unicode before CSV formula detection and ignore control/BOM/zero-width prefixes.

## Root Cause

The first implementation treated approval as configuration rather than consumable authorization, applied caps per record-producing job rather than per resulting library, and conflated URL validity with URL provenance. Rendering protections were context-incomplete.

## Prevention

- Write concurrency and replay tests before changing approval handling.
- Define every budget against a single explicit scope: calls per invocation and retained sources per resulting library.
- Treat provider metadata as untrusted and bind it to operator-approved identities.
- Apply output-context encoding after canonicalization, and test every supported renderer with hostile multiline input.
- Keep all live tests injected and recording-only until a separately authorized provider smoke test.
