# Memo correction and live verification — November 17, 2026

**Result: the known memo-generation issues are fixed. All 74 offline tests pass, and fresh OpenAI and Anthropic reviews passed the source-integrity and scoped-content checks below. Both remain Draft for a person's review.**

On the test machine, open `http://127.0.0.1:8502`. This is a local address, not a public deployment. Verification began from base commit `87911f1`; this report documents the changes tested before publication.

## What changed

- New findings publish complete source excerpts instead of model-written factual summaries. Model-provided summaries, quotations, and URLs cannot replace source text.
- Each topic can cite multiple paragraphs and source URLs. Paragraph offsets and every quotation are checked against the captured text. Adjacent qualification paragraphs are retained, including customer-worded prohibitions.
- Scope checks distinguish vendor access from customer IT administration, data geography from DPA/legal/arbitration language, and retention periods from ownership rights.
- Invalid IDs fail closed. Mixed-topic selections retain only relevant excerpts, use partial coverage, and record requested, accepted, and rejected IDs in the scoring audit.
- Historical generated summaries are visibly identified in the app. Existing reviews and audit events were not rewritten.

## Live verification

| Review | Captured pages | Exact evidence instances | State |
| --- | --- | --- | --- |
| #5 — OpenAI business products | 2 successful, neither truncated | 10 | Draft |
| #7 — Anthropic commercial products | 2 successful, neither truncated | 5 | Draft |

All four source hashes and all 15 evidence instances and offsets independently verify. Each new summary is exactly the joined source excerpts. Each review records `created → fetch → fetch → score → draft`, including model/request metadata and selection decisions, with no approval event.

The final OpenAI review preserves all six previously identified distinctions:

| Topic | Verified correction |
| --- | --- |
| Training | Business-product scope and the API-dashboard opt-in qualification remain in the source text. |
| Retention | Qualifying-organization and API-specific zero-retention scope are preserved, alongside the contractual deletion period and exceptions. |
| Assurance | The vendor's actual SOC 2/ISO wording is retained. The memo explicitly says no report was inspected or certification independently verified. |
| Location | Both eligible storage-at-rest regions and separate processing/inference scopes are quoted. |
| Access and sharing | Genuine recipient/personnel need-to-know and confidentiality terms replace customer IT permission descriptions. |
| Sensitive data | Both the required addendum and the prohibition for services not designed to process PHI remain visible. |

OpenAI security evidence also preserves its published encryption statements. The subprocessor excerpt establishes generic permission to use subprocessors; it does not establish a complete subprocessor list.

The final Anthropic review preserves commercial training defaults with feedback/opt-in exceptions, feedback-conversation-specific retention, need-to-know disclosure terms, and confidentiality restrictions/exclusions. Assurance, geography, subprocessors, and security remain unknown in this review. Unknown means these captured sources did not establish the topic; it does not mean the vendor lacks that capability. The model's earlier arbitration selection was replayed against the final scope check and rejected; the fresh review does not cite it as data-location evidence.

Sources: [OpenAI business data](https://openai.com/business-data/), [OpenAI services agreement](https://openai.com/policies/services-agreement/), [Anthropic training policy](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training), [Anthropic commercial terms](https://www.anthropic.com/legal/commercial-terms).

## Tests, audit, and privacy

`python -m pytest -q -p no:cacheprovider`: **74 passed**. `git diff --check` passed.

Coverage includes malicious model prose paired with genuine evidence, topic/scope mistakes, API-only options, storage versus processing, multiple citations, PHI prohibitions, long paragraphs, source hashes and offsets, invalid IDs, partial filtering, unavailable sources, SQLite persistence, immutable completed reviews, approval/rejection gates, review-specific confirmation state, exported decision details, and literal source rendering.

Original reviews #1 and #2, including their source snapshots and events, are byte-for-byte unchanged at the record level from the pre-fix baseline. Earlier test runs remain in the audit history; #5 and #7 are the verification examples for the corrected memo.

The authorized key was loaded into process memory only. Its original file is byte-for-byte unchanged. A private exact-value scan of project/runtime files passed; no key was displayed or copied into the repository. Credentials and runtime artifacts are excluded from Git.

Local artifacts are ignored by Git and exist only on the test machine:

- `.runtime/vendor-review-5-draft.md` and `.runtime/vendor-review-7-draft.md`
- `.runtime/memo-fix-verification-5.json` and `.runtime/memo-fix-verification-7.json`
- `.runtime/memo-fix-content-checks.json` and `.runtime/memo-fix-regression-replay.json`
- `.runtime/reviews.sqlite3`

Source quotations prove what the captured pages say, not independent verification or completeness. Coverage classifications still require a person's judgment. Approval records review of a demo memo, not authorization to use a vendor. Public hosting controls remain outside this memo-fix task.
