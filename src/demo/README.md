# Jack Ingram Motors AI Assistant (v2.0.0)

FastAPI service: customer chat (Claude tool use, with a deterministic fallback), scheduling, lead capture with
CRM delivery, live-agent handoff, NHTSA vehicle data, finance estimators, and an analytics dashboard.
Every business event is written to a hash-chained, HMAC-sealed ledger in the same transaction as the data.

## Run locally (Windows PowerShell)

```powershell
cd src\demo
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env            # optional: add ANTHROPIC_API_KEY, ADMIN_TOKEN, ...
uvicorn chatbot.main:app --reload --port 8080
```

Open `http://localhost:8080` (chat), `http://localhost:8080/admin` (analytics) and `http://localhost:8080/agent`
(live chat console). The admin pages need `ADMIN_TOKEN` set in `.env`. Without `ANTHROPIC_API_KEY` the
deterministic responder answers, so the demo runs offline.

Linux/macOS: `python3.12 -m venv .venv && source .venv/bin/activate`, `cp .env.example .env`, same commands.

Docker:

```powershell
docker build -t jim-assistant src\demo
docker run --rm -p 8080:8080 -e SESSION_SECRET=<32+ chars> -e LEDGER_HMAC_KEY=<32+ chars> `
  -e ADMIN_TOKEN=<32+ chars> -e ENVIRONMENT=production jim-assistant
```

Generate secrets with `python -m chatbot.cli gen-secret`.

## Layout

```text
chatbot/
  main.py            app factory, middleware order, error handlers
  config.py          settings (env only; production refuses weak/missing secrets)
  db.py, ledger.py   SQLite WAL + BEGIN IMMEDIATE; hash chain + HMAC seal; sealed exports
  middleware.py      request ids/access log, CSP + security headers, body cap, CSRF guard
  security.py        conversation tokens, admin bearer auth, client IP, dev-secret bootstrap
  agent/             Claude loop (llm.py), tools (tools.py), fallback, orchestrator, system prompt
  services/          inventory, finance, appointments, leads + ADF, outbox, handoff, feedback,
                     service history, analytics, conversations
  integrations/      NHTSA (vPIC, recalls, NCAP), Perplexity, FireCrawl
  data/              dealership.json (unverified facts), SAMPLE inventory and service records
  templates/, static/  chat UI, admin dashboard, agent console (strict CSP, textContent only)
tests/               adversarial suite (see below)
```

## HTTP API

Customer-facing (rate limited per client IP; state-changing calls must be `application/json`):

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/chat` | `{"message"}`; send `X-Conversation-Token` from the previous reply |
| GET | `/api/chat/messages?after=<id>` | poll for agent/system messages and handoff status |
| POST | `/api/chat/reset` | new conversation token |
| POST | `/api/feedback` | `{"message_id", "rating": 1 or -1, "comment"}` |
| GET | `/api/dealership` | facts plus `verified` flag |
| GET | `/api/inventory/search` | `make, model, body_style, condition, fuel_type, min/max_year, min/max_price, max_mileage, q, sort, limit` |
| GET | `/api/inventory/{stock}` | vehicle plus price context |
| POST | `/api/inventory/compare` | `{"stock_numbers": [2-4]}` |
| GET | `/api/offers` | current offers |
| GET | `/api/vehicles/vin/{vin}` | NHTSA vPIC decode (check digit validated first) |
| GET | `/api/vehicles/recalls`, `/api/vehicles/safety-ratings` | `make, model, year` |
| POST | `/api/finance/payment`, `/api/finance/lease`, `/api/trade-in/estimate` | estimators |
| GET | `/api/appointments/availability` | `department=service or test_drive, date_from, days` |
| POST | `/api/appointments` | optional `Idempotency-Key` header; returns ICS |
| POST | `/api/appointments/{code}/cancel` | `{"phone_last4"}` or `{"email"}` |
| POST | `/api/leads` | optional `Idempotency-Key` header |
| POST | `/api/service-history/lookup` | `{"vin", "last_name"}`; identical response for every miss |

Admin (`Authorization: Bearer $ADMIN_TOKEN`): `/api/admin/analytics/summary`, `/leads`, `/leads.csv`,
`/appointments`, `/handoffs` (+ `/claim`, `/messages`, `/close`), `/ledger/verify`, `/ledger/head`,
`/records/verify`, `/outbox` (+ `/requeue`), `/service-records`, `/inventory/reload`.

Health: `/health` (liveness), `/ready` (database, LLM breaker state, configured integrations), `/api/version`.

## Embedding on the dealership site

Set `FRAME_ANCESTORS=https://www.jackingram.com` and embed `https://<app-host>/` in an iframe. The conversation
token travels in a header (not a cookie), so third-party-cookie blocking does not break the chat. To call the
API directly from the dealership's own pages instead, set `CORS_ORIGINS`.

## CRM delivery

Set `CRM_WEBHOOK_URL` and `WEBHOOK_SIGNING_SECRET`. Leads, bookings, cancellations and handoff requests are
written to an outbox in the same transaction as the record, then delivered at least once with exponential
backoff. `CRM_WEBHOOK_FORMAT=adf` sends ADF 1.0 XML (lead and booking events only). Receivers should:

1. Verify `X-JIM-Signature: t=<unix>,v1=<hex>`, where `v1 = HMAC-SHA256(secret, "<t>.<raw body>")`, and reject
   timestamps older than five minutes.
2. De-duplicate on `X-JIM-Delivery-Id`.
3. Return a 2xx. A 4xx other than 408/409/425/429 marks the delivery dead (re-queue it from the admin API).

## Claude integration

- Model `claude-opus-5-5`, effort `medium` (both configurable), adaptive thinking, 16K max tokens.
- Server-side refusal fallback is on (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`). Set
  `ANTHROPIC_REFUSAL_FALLBACKS=false` to turn it off.
- History is append-only and the system prompt is frozen per process. The current time travels in each user
  turn, so preserved thinking stays valid and the prompt cache stays warm. Requests also send
  `prefix_mismatch_behavior: "drop_block"` (beta `thinking-binding-controls-2026-08-01`) so a changed prefix
  degrades instead of failing.
- Tools that create leads or bookings refuse contact details the customer did not type in the conversation
  (provenance barrier against prompt injection and hallucinated numbers).

## Data durability

SQLite lives in `DATA_DIR`. On DigitalOcean App Platform that disk is ephemeral and per-instance: keep one
instance and treat the CRM as the system of record. Use a persistent local disk elsewhere (WAL mode does not
work on network shares). Export sealed evidence regularly: `python -m chatbot.cli export-ledger <path>`.

## Tests

```powershell
cd src\demo
python -m pytest -q          # 213 tests, ~12 s
python -m ruff check .
```

| Suite | Tests | What it proves |
| --- | ---: | --- |
| `test_ledger.py` | 16 | Chain links; detects payload edits, re-sealing without the key, middle deletion, swaps, wrong key; tail truncation caught via external anchor; idempotent replay and key-reuse conflict; crash rollback; 4-process concurrent appends stay contiguous and valid; sealed export detects tampering and truncation |
| `test_atomic_config.py` | 15 | Atomic writes survive a crash at rename or fsync with no temp debris; exclusive create has exactly one winner among 12 racing threads; production refuses missing/short secrets and insecure webhooks; secrets never appear in repr; CSV/JSON env parsing; dev secrets shared across workers |
| `test_repo_hygiene.py` | 3 | No credential-shaped strings in any tracked file; no hardcoded key defaults; `.env.example` has empty secrets |
| `test_domain.py` | 41 | VIN check digits and bad characters; payment math against known values; tax/trade-in arithmetic; rejects absurd and non-finite input; 300-case payment invariant fuzz; lease math; trade-in monotonic in mileage, age, condition and accident history; inventory filters, compare rules, offer expiry, bad feed rows skipped |
| `test_appointments.py` | 19 | Lead time, Saturday hours, Sunday and Thanksgiving closures, DST offsets and UTC storage, misaligned/past/too-far slots, capacity, per-phone cap, idempotency, cancellation with no code oracle, RFC 5545 ICS, 8-process booking race never exceeds capacity |
| `test_leads_outbox.py` | 25 | Lead validation and sanitisation; atomicity (crash leaves no partial rows); no PII in the ledger; ADF XML injection escaped; masked API output; tampered business rows detected against ledger digests; CSV formula injection blocked; outbox signatures, replay window, retry/backoff to dead-letter, permanent vs transient errors, lease prevents double delivery, crash recovery |
| `test_security_http.py` | 27 | CSP and security headers; iframe allow-list; non-JSON and cross-origin POSTs rejected; declared and chunked oversized bodies rejected; no input echo in errors; rate limits shared, spoofed `X-Forwarded-For` ignored, configured proxy header honoured; admin auth exact-match; generic 500s with request id; tampered tokens cannot read or continue; production hardening |
| `test_chat_flows.py` | 24 | Fallback answers; topic classifier; conversation isolation; turn lease (409) and stale-lease recovery; text sanitisation; prompt-injection text inert; full handoff lifecycle incl. claim theft; feedback rules; analytics never store raw text; service-history lookup is not an oracle; per-VIN throttle against distributed guessing; idempotent DMS import |
| `test_agent_llm.py` | 25 | Request shape matches the current API; tool schemas clean; history append-only with thinking preserved byte for byte; tool loop, parallel calls, invalid/unknown/crashing tools contained; provenance barrier; idempotent tool booking; refusal not persisted; truncated tool calls never executed; final-iteration tool lockout; deadline, transient and auth failures fall back (breaker opens); rejected history stripped and retried once; fallback-boundary sanitising; history trim; completed actions survive a mid-turn crash; usage telemetry |
| `test_nhtsa.py` | 18 | Tolerant parsing and caching; invalid VIN never hits the network; retries; breaker opens on 5xx but not on 4xx; malformed JSON and timeouts; key-casing drift; hostile make/model rejected before any request; two-step ratings with path encoding; HTTP error mapping; fallback VIN answer |

The multi-process tests use the `spawn` start method, so they behave the same on Windows and Linux. CI runs the
suite on Ubuntu and Windows with Python 3.12 and 3.13, plus gitleaks and a Docker smoke test.

## Troubleshooting

See the Troubleshooting section of `TURNOVER.md` at the repository root.
