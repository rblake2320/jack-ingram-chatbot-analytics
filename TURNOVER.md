# Jack Ingram Motors AI Assistant: Project Turnover

Last updated: 2026-11-05 (v2.0.0, FastAPI rewrite). This document describes what the code in
`src/demo/` actually does today. Every "Implemented" item below is exercised by the test suite.

## P0: credential incident (action required by the owner)

Earlier commits contained live credentials in `config.py`, `app.yaml`, `app.json`, the Perplexity and
FireCrawl clients, this file, and `project_dependencies_update.md`:

- Anthropic key starting `sk-ant-api03-V_Px…`
- Perplexity key starting `pplx-1y7Y…`
- FireCrawl key starting `fc-be23…`

v2.0.0 removes every copy from the working tree and loads secrets only from the environment, but **the
keys remain in git history**. They must be revoked in each provider's console. Rewriting history
(`git filter-repo`) is optional once the keys are dead. A personal email address was also exposed through a
committed `.gitconfig` (removed in v2.0.0, still in history).

Guards now in place: `tests/test_repo_hygiene.py` fails CI if any credential-shaped string or hardcoded key
default appears in a tracked file, and the `secret-scan` CI job runs gitleaks on every push and pull request.

## Architecture

```text
Browser (chat UI, booking/lead forms)        Agent console (/agent)    Analytics (/admin)
        |  X-Conversation-Token (HMAC)                 |  Bearer ADMIN_TOKEN       |
        v                                              v                           v
FastAPI  --- middleware: request-id, security headers/CSP, body cap, CSRF guard, rate limits ---
   |
   +-- ChatService: turn lease -> Claude tool loop (claude-opus-5-5) -> deterministic fallback
   |        tools: inventory, compare, offers, NHTSA VIN/recalls/ratings, payment/lease/trade-in,
   |               availability, booking, lead capture, human handoff, service history
   |
   +-- Services: inventory | finance | appointments | leads (+ADF) | handoff | feedback |
   |             service history | analytics | conversations
   |
   +-- SQLite (WAL, BEGIN IMMEDIATE = cross-process write lock)
   |        business rows + hash-chained HMAC ledger + transactional outbox, one transaction
   |
   +-- Outbox worker -> CRM webhook (JSON or ADF 1.0 XML, HMAC-signed, at-least-once)
   +-- Upstreams (optional, cached, retried, circuit-broken): NHTSA, Perplexity, FireCrawl
```

## Implemented

| Area | What it does | Code |
| --- | --- | --- |
| Web app | FastAPI app factory, strict CSP (no inline script/style), JSON-only state-changing APIs | `chatbot/main.py`, `chatbot/middleware.py` |
| Claude | Manual tool loop on the beta Messages API: adaptive thinking, explicit effort, server-side refusal fallback, append-only history, deadline, breaker | `chatbot/agent/llm.py` |
| Fallback | Deterministic responder when Claude is unconfigured or failing; same services, no invented facts | `chatbot/agent/fallback.py` |
| Conversations | Per-conversation signed tokens, server-side transcript, cross-process turn lease | `chatbot/services/conversations.py` |
| Inventory | Validated feed load, search/filter/sort, 2-4 vehicle comparison, price context, offers | `chatbot/services/inventory.py` |
| NHTSA | vPIC VIN decode, recalls by make/model/year, NCAP ratings; cached, retried, breaker | `chatbot/integrations/nhtsa.py` |
| Finance | Loan and lease estimators (Decimal, cent-exact); trade-in heuristic with disclaimer | `chatbot/services/finance.py` |
| Scheduling | Slot grid from business hours, DST-correct, holidays, capacity, per-phone cap, ICS | `chatbot/services/appointments.py` |
| Leads / CRM | Validated, consented, idempotent; ADF 1.0 XML; transactional outbox with HMAC signatures | `chatbot/services/leads.py`, `adf.py`, `outbox.py` |
| Handoff | Queue, claim, agent replies, close; customer polling; agent console page | `chatbot/services/handoff.py`, `/agent` |
| Feedback | Per-message thumbs up/down with comment | `chatbot/services/feedback.py` |
| Service history | VIN + last-name lookup (no enumeration oracle), DMS import endpoint | `chatbot/services/service_history.py` |
| Analytics | Events without raw customer text; dashboard: KPIs, daily trend, topics, heatmap, tools, health | `chatbot/services/analytics.py`, `/admin` |
| Evidence | Hash-chained, HMAC-sealed ledger; record digests; sealed export bundles | `chatbot/ledger.py`, `chatbot/cli.py` |
| Security | Rate limits (shared across workers), admin bearer auth, CSRF guard, body cap, sanitised errors, PII-redacting logs | `chatbot/security.py`, `chatbot/logging_setup.py` |

## Not implemented / known limitations

These are deliberate scope limits or things that could not be verified from the build environment.

- **Live upstreams not verified in this session.** The build sandbox's network policy blocks `api.nhtsa.gov`,
  `vpic.nhtsa.dot.gov`, Perplexity and FireCrawl. Their clients are tested against fixtures modelled on the
  documented response shapes, with tolerant parsing. Verify on a networked machine:
  `python -m chatbot.cli smoke-nhtsa 1HGCM82633A004352`.
- **Claude was not called live.** No API key was available; the tool loop is tested with real SDK response
  types from a scripted client. Run a short live conversation before launch.
- **Sample data.** Inventory, offers and service records are generated SAMPLE data, labelled as such in every
  response. Point `INVENTORY_FEED_PATH` at a DMS export in the same JSON schema.
- **Dealership facts are unverified.** `chatbot/data/dealership.json` uses the June 2025 site captures. They
  contradicted the old hardcoded values (`1000 Eastern Blvd`, `(334) 277-5700`). The assistant adds a
  "please confirm" note until `_meta.verified` is set to `true`.
- **Trade-in values are heuristic,** not KBB/Black Book/J.D. Power. Integrate a licensed valuation API for quotes.
- **CarAPI is not integrated.** The old client pointed at a placeholder domain; NHTSA vPIC covers specs.
- **The old MCP client was removed.** It imported packages that do not exist.
- **Data durability.** SQLite on DigitalOcean App Platform is ephemeral across deploys and not shared between
  instances. Run one instance (workers inside it share the database) and use the CRM webhook as the system of
  record. Moving to managed Postgres is the next infrastructure step.
- **No SMS/email sending.** Notifications go out through the CRM webhook only.
- **Ledger tail truncation** is detectable only against an external anchor (webhook receipts carry each entry's
  `seq`/`hash`; `/api/admin/ledger/head`; sealed exports).

## Configuration

All settings are environment variables (or `src/demo/.env`). See `src/demo/.env.example` for the full list.

| Variable | Required | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | yes in prod | `production` enforces the secret checks below, HSTS, and disables `/docs` |
| `SESSION_SECRET` | prod | HMAC key for conversation tokens (>= 32 chars) |
| `LEDGER_HMAC_KEY` | prod | Ledger seal and record-digest key (>= 32 chars); keep a backup, rotation breaks old seals |
| `ADMIN_TOKEN` | prod | Bearer token for `/api/admin/*`, `/admin`, `/agent` (>= 32 chars) |
| `ANTHROPIC_API_KEY` | no | Enables Claude; without it the fallback responder answers |
| `ANTHROPIC_MODEL` / `ANTHROPIC_EFFORT` | no | Default `claude-opus-5-5` / `medium` |
| `CRM_WEBHOOK_URL` / `WEBHOOK_SIGNING_SECRET` / `CRM_WEBHOOK_FORMAT` | no | CRM delivery (`json` or `adf`) |
| `CLIENT_IP_HEADER` | DO: yes | `do-connecting-ip` on App Platform so rate limits see real clients |
| `CORS_ORIGINS` / `FRAME_ANCESTORS` | no | Cross-origin API access and iframe embedding allow-lists |
| `INVENTORY_FEED_PATH` / `DEALERSHIP_FILE` | no | Replace the bundled sample data |

## Operations

- Deploy: push to `main`; App Platform builds `src/demo/Dockerfile` (spec in `src/demo/app.yaml`).
- Verify the ledger: `python -m chatbot.cli verify-ledger` (exit code 2 on failure) or `GET /api/admin/ledger/verify`.
- Verify business rows against the ledger: `GET /api/admin/records/verify`.
- Export sealed evidence: `python -m chatbot.cli export-ledger var/ledger.jsonl`, then `verify-bundle`.
- Retry failed CRM deliveries: `GET /api/admin/outbox?status=dead`, then `POST /api/admin/outbox/{id}/requeue`.
- Reload inventory after a feed update: `POST /api/admin/inventory/reload`.
- Import service records from the DMS: `POST /api/admin/service-records`.

## Troubleshooting

- **App exits at startup with "Unsafe production configuration"**: a required secret is missing or shorter
  than 32 characters. Set it in the App Platform dashboard.
- **Every reply has `source: fallback`**: `ANTHROPIC_API_KEY` is unset or rejected. `/ready` shows
  `checks.llm` as `unconfigured` or `open` (breaker tripped after auth/5xx errors; it retries after 60 s).
- **`409 conversation_busy`**: the previous message in that conversation is still being processed; the lease
  expires automatically after the agent deadline plus 30 s if a worker died.
- **`ZoneInfoNotFoundError` on Windows**: reinstall requirements; `tzdata` provides the timezone database.
- **`database is locked`**: the database is on a network share. WAL mode needs a local disk.
- **Rate limits hit every user at once behind a proxy**: set `CLIENT_IP_HEADER` to the header your proxy writes.
- **CRM not receiving leads**: check `/api/admin/outbox`. `dead` rows record the last HTTP status; receivers
  must return 2xx and de-duplicate on `X-JIM-Delivery-Id`.

## Testing

`cd src/demo; python -m pytest -q` runs the adversarial suite on Linux and Windows in CI (Python 3.12 and 3.13).
Suite contents and what each one proves are listed in `src/demo/README.md`.
