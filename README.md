# Aegis AI Vendor Risk Reviewer

An interactive demo that reviews public vendor documents against a fixed rubric, attaches verifiable quotations, drafts a memo, requires a human decision, and records an audit trail. It supports a trusted local session or a small hosted preview with individual invite codes. **This is not a completed vendor assessment, legal advice, or a security certification.**

## Quick start

Use Python 3.11 or 3.12. Public pages and extracted text are sent to OpenAI; API usage incurs charges. Do not include client data, private URLs, or credentials in the demo.

```bash
git clone https://github.com/dblomqu1-8980/aegis-vendor-risk-reviewer.git
cd aegis-vendor-risk-reviewer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Privately configure OPENAI_API_KEY in .env. Never commit or share it.
streamlit run src/app.py
```

Existing Policy Q&A credentials may be used if authorized; configure them privately, not in GitHub. The `.env` and runtime database are ignored. On Windows activate with `.venv\Scripts\activate`.

The example `.env` explicitly selects local mode. Use that mode only on a trusted localhost server; bind to `127.0.0.1` for a demo on your own machine. Without explicit local mode the app defaults to hosted mode and refuses access until invite hashes are configured.

## Free hosted preview

See [HOSTING.md](HOSTING.md) for Streamlit Community Cloud setup. Hosting is free; live OpenAI API requests still incur usage charges. This repository does not contain a deployed app URL or credentials.

Hosted mode requires a separate random invite code for each person. It checks the invite on every interaction and expires sessions after one hour. Each invite opens its own database, separate from other invitees and the original local history. Anyone holding an invite can use that invite's workspace; give each person a different code and keep codes private.

Live review attempts are reserved atomically before fetching pages or calling the API: by default three per invite and twenty across the demo per UTC day, with a thirty-second per-invite cooldown. Failed attempts count. Hosted scoring uses a fixed model, bounded input/output, and no automatic API retries. These are request limits, not a guaranteed dollar spending cap.

**Free-host review history and usage counters may reset when the host recycles its filesystem. Download your memo to keep it.** This preview does not provide durable audit storage or strong proof of a reviewer's identity. Keep confidential information out of the app.

## How it works

The two vendor choices refer to commercial/business products. The UI fetches only its preselected public URLs, with timeouts, size limits, no redirects, and no authenticated pages. Failures are recorded and do not prevent a draft containing unknown findings. Source text is treated as untrusted. A model selects focused paragraph IDs for each rubric topic; code checks topic and access scope, resolves exact source offsets, and includes adjacent qualifying paragraphs. New memos publish source excerpts instead of model-written factual summaries. Multiple excerpts can document separate storage and processing conditions. Every excerpt and its source offset are checked against the captured text. Invalid selections become unknown; mixed topic selections retain only relevant evidence and use partial coverage, with exclusions recorded in the audit. Exact matching and topic filters do not prove completeness or independently verify vendor claims; a person must review context and current terms. MET means the topic is documented, not that the vendor is compliant, secure, or approved.

A draft remains Draft until a person confirms review and explicitly approves or rejects it. Confirmation and notes are specific to each review. SQLite stores extracted public page text, hashes, findings, scoring metadata, and time-stamped events on the local machine. Completed reviews reject subsequent source, findings, or decision changes through the application functions. The exported memo includes the recorded outcome, timestamp, and note. An approval is a review of this demo memo, not authorization to use a vendor. Sources may be partial or truncated; the reviewer should inspect them. This is a local audit history, not a tamper-proof ledger. Never load client records.

## Test and limitations

See the [local live-test report](LIVE_TEST_REPORT.md) for the memo corrections, public-source runs, and workflow verification.

Run `python -m pytest -q`. Tests use fictional frozen examples and mocks; passing offline checks does not prove real vendor pages are reachable or model answers are correct. The live-test report covers the earlier local evidence runs; the hosted preview needs its own final smoke test after account and secret setup. Pages can block automated requests; redirects, non-HTML responses, and missing content are reported unavailable. The index is not a complete vendor review or financial/security score. Status labels describe documentation against the rubric, not security compliance. An invite-only preview is appropriate for a small demonstration, not unrestricted public use or client work.
