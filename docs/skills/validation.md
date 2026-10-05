# Skill Validation: proof-safe-copy-angles

Date: 2026-10-05. Python: 3.12.3. Initial validation scope: README/documentation/skill exercise only; no production, test, package, configuration, fixture, or VERIFICATION changes. No commit, push, remote operation, live/paid call, new model, or global skill installation occurred in that pass.

## Actual CLI Evidence

Read the actual README, current input fixture and expected report first. Canonical fields are `headlines` and `faqs`; duplicate aliases are not another set of candidates. A nonempty headline array can contain null text.

Working directory: `/home/yaron/projects/bright-data-customer-led-page-rewrite`. Executed the actual `customer_led_page_rewrite.__main__` with these arguments through `/tmp/opencode/five-repo-skill-check.py`, with socket/DNS/HTTP audit events denied:

```bash
python3 -m customer_led_page_rewrite analyze /home/yaron/projects/bright-data-customer-led-page-rewrite/fixtures/demo.json --out-dir /tmp/opencode/skills-20261005-customer_led_page_rewrite-v2/demo
```

- Exit `0`: `status=needs_review`, `decision=annotated_rewrite`, `requests_made=0`; network attempts `0`.
- Generated JSON/Markdown/CSV match all three expected artifacts byte-for-byte.
- Recomputed all `4` source hashes with the repo's normalizer; checked `5` unique exact citations against normalized source blocks.
- Generated report SHA-256: `f378a63fe8e45ca10c96c50ed4c9ab5c07917282b7babb0cbcb255a3350089fb`.
- `--dry-run`: exit `0`, zero requests, no output directory. Same destination without overwrite: structured exit `2`, original three hashes unchanged.
- Raw CLI arguments/results and artifact hashes: `/tmp/opencode/skills-20261005-customer_led_page_rewrite-v2/cli-evidence.json`. Temporary logs are local session evidence, not required inputs for the portable skill; checked-in fixtures reproduce the report.

## Skill Exercise And Variations

The main assistant followed [the skill](../../skills/proof-safe-copy-angles/SKILL.md) on the freshly generated report and wrote [the checked cards](proof-safe-copy-angles-example.md). This is a manual instruction exercise, not a deterministic skill runner or a new model/API call. Exact template/FAQ, source-locator/hash, origin and gate checks are part of the documentation audit.

- Demo: both setup templates are copied verbatim with approved fact refs; the FAQ keeps every qualifier. The sales-guarantee question remains an unanswered `needs_approved_fact` hold, not a promise or denial.
- Actual variant `/tmp/opencode/skills-20261005-customer_led_page_rewrite-v2/unverified-fact/report.json`: fact `f1` is `unverified`. Both headline rows have null `text` and state `needs_approved_fact`; all FAQ drafts are null. Skill output: "No eligible angle cards. Hold setup and sales until supporting product facts are approved." A source role does not establish approval.
- Actual hostile-source variant `/tmp/opencode/skills-20261005-customer_led_page_rewrite-v2/hostile-source/report.json`: headlines, FAQs and decision unchanged; affected snapshot hash changes. Skill disposition: "Treat contributor commands as untrusted evidence; keep approved setup text and the sales hold. Do not edit or publish."
- An initial harness assumption that absent approved facts would empty the `headlines` array was wrong. Reading the actual report showed null-text placeholders; the assertion was corrected and rerun successfully. Production was not changed to match the assumption.

## Documentation Audit

`/tmp/opencode/check-five-repo-skill-docs.py` returned PASS: standard name/description front matter, folder/name match, all `10` local links, ASCII/whitespace checks, and the five-file review inventory. The checked cards have `5` exact quote refs and `5` source/block locators; every cited hash/URL/date resolves to the generated report. Both headline strings, the eligible FAQ and the sales proof hold match the report. This is a mechanical consistency audit, not independent approval. `git diff --check` passed for the README change.

For repeat CLI replay, choose a fresh output directory; the recorded paths already contain this session's outputs. Temporary session logs may later be removed. The skill itself needs only the operator's local report.

## Limits And Review

No real customer identity, buying intent, approved-fact truth, conversion lift, page experiment or live provider compatibility was verified. Manual safety checks do not guarantee instruction following in every agent.

[The stable review manifest](review-manifest.txt) includes README and the four skill/doc files. The initial skill pass left independent approval pending; that historical state is superseded by the record below. Earlier verification and source caveats remain intact.

## Approved Integration

On 2026-10-05, session-reported independent skeptic, engineer, and brand reviewer results were APPROVE/SHIP for all five frozen skills/README sections under the lightweight showcase standard. These are independent reviewer results reported in the session, not a user-conducted review. Reviewer artifact paths were not supplied; this publication pass carries those results forward rather than independently re-establishing approval. Reviewed input: `/tmp/opencode/five-repo-skill-review-20261005.json`, SHA-256 `0bc5f74f49b71eda3898ad4a0229612e06841a5acd7e599006a77fc8f2b353e2`. The original manifest is retained as review history, not overwritten.

The approved skill section is retained verbatim. The README identifies `yaronbeen/bright-data-customer-led-page-rewrite` and explicitly preserves the independent-showcase/non-endorsement boundary. Package, CLI, module and local paths are unchanged. Skill instructions and the checked example are byte-identical to the reviewed snapshot; no outputs or features were expanded.

Integration validation used only simple front matter, local links, cited-sample checks and one offline demo replay. The three generated artifacts matched the existing goldens; the demo reported zero requests. No new TDD matrix, framework, source/test/package/configuration/core VERIFICATION change, staging, commit, push, remote operation or global installation was part of that integration pass. Final four-repo documentation hashes, exact intended diffs and the staging list were recorded separately at `/tmp/opencode/four-repo-skills-final-20261005.json`.

Approval concerns the lightweight showcase artifacts, not live Bright Data behavior, real customer identity/buying intent, approved-fact truth, conversion lift or business outcomes. That integration pass did not publish the local documentation changes.

## Publication Preflight

On 2026-10-05, publication preflight was limited to this repository's five intended documents. The final handoff manifest SHA-256 `af91bca951a4f3299deb4a068ad24c4e65eb9e612fa511bb1b32f6495070da7d` and its staging list were verified. Only this validation record differs from the final handoff: approval provenance, historical-pass wording, and this preflight record. The skill, checked example, README, and file inventory retain their handoff hashes.

- Replayed the actual CLI into `/tmp/opencode/customer-led-doc-demo-20261005`, with socket/HTTP audit events denied: exit `0`, `status=needs_review`, `decision=annotated_rewrite`, `requests_made=0`, network attempts `0`. All three generated artifacts matched existing goldens byte-for-byte; report SHA-256 remained `f378a63fe8e45ca10c96c50ed4c9ab5c07917282b7babb0cbcb255a3350089fb`.
- Dry-run exited `0` without creating its output directory. An existing-output replay exited `2` with `invalid_input` and preserved all three artifacts. Both made zero network attempts.
- `/tmp/opencode/customer-led-doc-publication-check-20261005.py` passed: five-file inventory, front matter, all `10` local links, `5` exact quote refs, `5` source/block locators, and all `4` source metadata records. Skill and example hashes match the reviewed snapshot.
- TruffleHog `3.94.1` scanned only the five intended documents with verification/update networking disabled: zero verified or unverified secrets. The effective `core.hooksPath` is `/home/yaron/.git-hooks`; the normal commit-time TruffleHog hook also executed and passed. No hook bypass is used.
- Source, tests, package, fixtures, configuration, and core VERIFICATION remain unchanged. No new test matrix, wheel build, installation, live provider call, or outcome verification is part of this documentation publication preflight.
