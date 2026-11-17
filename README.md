# Aegis AI Vendor Risk Reviewer

An early, local-only demo that reviews public vendor documents against a fixed rubric, attaches verifiable quotations, drafts a memo, requires a human decision, and records an audit trail. **This is not a completed vendor assessment, legal advice, a security certification, or a public deployment.**

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

## How it works

The two vendor choices refer to commercial/business products. The UI fetches only its preselected public URLs, with timeouts, size limits, no redirects, and no authenticated pages. Failures are recorded and do not prevent a draft containing unknown findings. Source text is treated as untrusted. A model selects focused paragraph IDs for each rubric topic; code checks topic and access scope, resolves exact source offsets, and includes adjacent qualifying paragraphs. New memos publish source excerpts instead of model-written factual summaries. Multiple excerpts can document separate storage and processing conditions. Every excerpt and its source offset are checked against the captured text. Invalid selections become unknown; mixed topic selections retain only relevant evidence and use partial coverage, with exclusions recorded in the audit. Exact matching and topic filters do not prove completeness or independently verify vendor claims; a person must review context and current terms. MET means the topic is documented, not that the vendor is compliant, secure, or approved.

A draft remains Draft until a person confirms review and explicitly approves or rejects it. Confirmation and notes are specific to each review. SQLite stores extracted public page text, hashes, findings, scoring metadata, and time-stamped events on the local machine. Completed reviews reject subsequent source, findings, or decision changes through the application functions. The exported memo includes the recorded outcome, timestamp, and note. An approval is a review of this demo memo, not authorization to use a vendor. Sources may be partial or truncated; the reviewer should inspect them. This is a local audit history, not a tamper-proof ledger. Never load client records.

## Test and limitations

See the [local live-test report](LIVE_TEST_REPORT.md) for the memo corrections, public-source runs, and workflow verification.

Run `python -m pytest -q`. Tests use fictional frozen examples and mocks; passing offline checks does not prove real vendor pages are reachable or model answers are correct. Live API, end-to-end human review, and hosting need separate verification. In particular, this version lacks authentication, durable hosted storage, public abuse controls, and multi-user isolation. Do not deploy it as a public app yet. Pages can block automated requests; redirects, non-HTML responses, and missing content are reported unavailable. The index is not a complete vendor review or financial/security score. Status labels describe documentation against the rubric, not security compliance.

## Public demonstration preparation

Use `streamlit run src/public_app.py` for the anonymous demonstration, not `src/app.py`. The public entry point keeps reviews only in the visitor's Streamlit session and does not connect to the local reviews database. Reviews can be lost on reload, disconnect, or restart; download the Markdown before leaving. It is a demonstration, not an authenticated application, a permanent audit trail, or a place for confidential information.

Each browser session allows three attempts and enforces a 30-second delay. An atomic SQLite counter permits 25 attempts per UTC day per running instance, including failed attempts. These are **best-effort protections only**: new sessions bypass the session limit, and the instance counter can reset on restart or differ across replicas. It is not a dependable spending ceiling. Before any public launch, configure and verify a provider-side hard spending limit and usage alerts appropriate to the OpenAI project, and understand that reusing a key shares the same project budget with other apps. Add durable shared rate limiting and suitable access controls if stronger protection is required. Restrict public exposure until the provider budget and the hosted deployment have been verified.

On Streamlit Community Cloud select `src/public_app.py` as the main file and securely configure `OPENAI_API_KEY` in the app's secrets. Do not commit API keys to GitHub. Use only public sample content. Live vendor pages and AI classifications can be incomplete or incorrect; human verification remains necessary.
