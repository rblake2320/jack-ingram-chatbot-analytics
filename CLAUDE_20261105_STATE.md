# CLAUDE Project State Update - November 5, 2026

[IMPORTANT: Never modify or delete existing CLAUDE_*.md files. Always create new ones with timestamps to preserve history]

## Previous states

- CLAUDE_20250610_STATE.md
- CLAUDE_20250610_STATE_2.md

## What changed

- The Flask prototype in `src/demo` did not run: `claude_client.py` had a SyntaxError (`await` outside an async
  function) and the router referenced undefined names. It was replaced by a FastAPI application
  (`src/demo/chatbot`, v2.0.0).
- Hardcoded Anthropic, Perplexity and FireCrawl keys were removed from code, deploy specs and docs. **The keys
  remain in git history and must be revoked.**
- Implemented and tested: Claude tool loop (`claude-opus-5-5`), deterministic fallback, inventory search and
  comparison, NHTSA VIN/recalls/ratings, finance and trade-in estimators, appointment scheduling, lead capture
  with ADF/JSON CRM outbox, live-agent handoff and console, feedback, service history, analytics dashboard,
  tamper-evident ledger, rate limiting, CSRF guard, security headers.
- 213 adversarial tests; CI on Linux and Windows (Python 3.12/3.13), gitleaks, Docker smoke test.
- Root duplicates of `docs/` files and committed shell dotfiles were removed.

## Current status and limitations

See `TURNOVER.md` (authoritative). Highlights:

- Sample inventory/offers/service records; dealership facts unverified.
- Live NHTSA, Perplexity, FireCrawl and Claude calls were not verified from the build sandbox (network policy).
- SQLite is single-instance and ephemeral on App Platform; the CRM webhook is the system of record.

[End State: November 5, 2026]
