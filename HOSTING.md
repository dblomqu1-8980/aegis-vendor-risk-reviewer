# Free, invite-only Aegis preview

Target: [Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud). No paid hosting service or custom domain is required. Live OpenAI usage is billed separately to the key owner.

Community Cloud [does not guarantee local-file persistence](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data). Reviews and attempt counters can disappear on a recycle/redeploy. Download memos you want to keep. Do not use this preview for client records or as a durable audit system.

## Prepare access

From the repository root, using its Python environment:

```bash
python scripts/create_invite.py owner
```

The command generates a random 32-byte bearer code and saves it privately under `.runtime/invite-setup/owner.txt`. It prints the file location, never the code. The hash-only mapping is saved to `.runtime/invite-setup/invites.json`. Both are ignored by Git. Repeat with a different opaque ID for each person, for example `reviewer-1`. Give each person only their own code through a private channel. Anyone holding that code can use the associated workspace; this is invitation access, not verified identity.

To revoke an invite, remove its entry from the host's `AEGIS_INVITES_JSON` and save the secrets. Sessions are rechecked on their next interaction. Keep the same person ID when replacing a code if you want to preserve their workspace. Do not recycle IDs between people. Revocation cannot retract material already displayed or downloaded.

## Deploy

1. Sign in to [Streamlit Community Cloud](https://share.streamlit.io/) and connect the GitHub account that can read this repository. Review any requested permissions and account terms yourself.
2. Choose **Create app**, repository `dblomqu1-8980/aegis-vendor-risk-reviewer`, branch `main`, and entrypoint `src/app.py`. Choose Python **3.12** in Advanced settings.
3. Configure private Secrets using [.streamlit/secrets.example.toml](.streamlit/secrets.example.toml) as the shape. Set `AEGIS_MODE` to `hosted`. Put the authorized API key only in `OPENAI_API_KEY` in the host's private settings; never in a chat, repository, screenshot, or issue. Set `AEGIS_INVITES_JSON` to the JSON string from the local hash map. Root-level Streamlit secrets become app environment variables. The example contains no real secrets.
4. Initially leave the limits of three attempts per invite and twenty total per UTC day. Save and deploy. Optional `AEGIS_DATA_DIR` selects a server storage directory; the default hosted runtime folder is separate from the legacy local database.
5. Verify the final `.streamlit.app` URL before sharing. Distribute invite codes only to intended reviewers. Do not send automatic email invitations without their approval.

The default is hosted mode. An unconfigured host displays a closed sign-in message and cannot open review data. Never set `AEGIS_MODE=local` on an internet-facing server. Do not upload the local `.env`, `.runtime` directory, old reviews, or a populated `secrets.toml` to GitHub.

## Verify after deployment

- Signed-out and invalid-invite browsers cannot see reviews, sources, memos, audit history, or API action buttons.
- Two different invites cannot see or decide each other's reviews, including overlapping numeric review IDs.
- A live review captures the allowed public sources, renders exact excerpts and links, and remains Draft until confirmed human review. Its download and audit trail reflect the recorded decision.
- Sign-out clears review selection, confirmation, and notes. Expired or removed invites cannot continue making actions.
- A fourth attempt for one invite is blocked before fetching or scoring. Failed attempts count, and cooldown limits rapid repeat clicks.
- No API key, invite code, host secret, or earlier local review appears in Git, screenshots, or app output.

Daily counters use the host's local SQLite control database. They are shared across sessions and survive reconnects while the filesystem exists; they reset if storage is replaced. Input is capped at 120,000 serialized prompt bytes, output at 1,800 tokens, and automatic API retries are disabled. These controls bound requests; they do not enforce a permanent billing limit. Remove the hosted API key to stop live generation completely.

Keep this preview on free hosting. If interest warrants a production service, add durable storage, verified identity, operational monitoring, and a separate project key/budget as a deliberate follow-up.
