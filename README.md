# Jack Ingram Motors chatbot and analytics demo

A website-embeddable dealership assistant covering six brands, Signature Used Cars
and the Body Shop. It compares reviewed vehicle model guides inside chat, includes
an interactive Porsche 911 component explorer, links to the stores' current inventory
and scheduling tools, and produces consent-based usage analytics.
The repository also contains historical proposals; their revenue and conversion
numbers are estimates, not measured results.

## Run on Windows

Python 3.12+:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install --require-hashes -r requirements.lock
Copy-Item .env.example .env
.venv/Scripts/python.exe -m src.demo.app
```

Open <http://127.0.0.1:8080>. Local mode needs no model or API credentials.
Use brand buttons, the message field, and suggested questions. “New chat” resets
this visitor's history. Requests are limited to 2,000 characters and 16 KiB JSON.
Waitress's transport buffer is bounded to 64 KiB.

## Capabilities and evidence

| Capability | Implementation | Acceptance |
| --- | --- | --- |
| Eight official locations, department hours, contact and action links | src/demo/data/dealerships.json; src/demo/api_router.py | test_website.py |
| Website widget with isolated styles and cookie-independent sessions | /static/embed.js; /widget | browser acceptance; no-cookie HTTP test |
| In-chat model comparisons and passenger-capacity follow-ups | src/demo/advisor.py; vehicle_guides.json | test_advisor.py; owner question in actual widget |
| Licensed Porsche 911 visual explorer, picking, separation, peel, focus and chat controls | /vehicle-atlas; frontend/atlas.js | test_atlas.py; Node geometry controls; desktop/mobile/container browser receipts |
| Labeled 2024 sample vehicles; expired offers excluded | src/demo/inventory_db.py | test_expired_offers_and_model_filter |
| Isolated history and reset; stale replies rejected | src/demo/store.py | test_receiving_session_isolation_and_reset; test_reset_wins_inflight |
| Consented metadata, deletion, protected dashboard | src/demo/app.py; /analytics | test_consent_summary_and_forget; browser receipt |
| Current configurable Messages API | src/demo/claude_client.py | synthetic HTTP contract and fault tests |
| Optional local Laya intent suggestions | src/demo/routing.py | scripts/evaluate_laya.py |
| Windows/Linux server and container | python -m src.demo.app | scripts/verify_http.py; CI |

Local responses are deterministic. To enable paid generation, explicitly set
CHAT_PROVIDER=anthropic and supply a **new** ANTHROPIC_API_KEY in .env or a secret store.
ANTHROPIC_MODEL is configurable (default claude-sonnet-5-5, checked against the
[current provider catalog](https://platform.claude.com/docs/en/models/overview)).
Official facts and handoff routes remain local. Sample inventory is available only
when explicitly requested with “sample”. The provider adapter
has bounded timeouts, no retries, and rejects empty, malformed or unfinished replies.
Provider contract tests use synthetic local responses; vendor inference requires
the operator's configured account and spending authorization.

## Privacy and analytics

Analytics is opt-in per message; the checkbox starts unchecked. Events contain
intent, brand, source, latency, token counts and a keyed anonymous browser identifier.
Events exclude messages, contact details, raw IP and user-agent strings.
“Delete my conversation & session analytics” removes this browser session's records.

Conversation text is stored separately in local SQLite to support follow-up questions,
limited to 20 messages and one hour of inactivity. Analytics retention is 90 days.
Expired records are deleted on server activity; the database is not encrypted by this app.
Protect its directory and volume, and configure an appropriate data policy before deployment.
No third-party analytics scripts or external frontend CDNs are loaded.

/analytics requires ADMIN_TOKEN (32+ characters) to retrieve aggregates. Set
SESSION_SECRET (32+ characters) for durable signed cookies. Generate these locally:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy separate generated values into .env without committing it. With no secret,
loopback development uses an ephemeral key and warns that sessions reset on restart.
Public binding requires SESSION_SECRET; use HTTPS and COOKIE_SECURE=true.
Set TRUSTED_HOSTS to the explicit deployment hostname (plus localhost for health probes).
Rate limits are enforced in SQLite against a keyed IP digest, so clearing cookies
does not bypass them. Do not trust forwarded headers without a configured proxy.

## Laya

The supplied [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya)
checkpoint classifies typed intents; it does not generate chat answers. Optional:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-laya.txt
.venv/Scripts/python.exe scripts/evaluate_laya.py --output laya-evaluation.json
```

The evaluation requires already cached checkpoint files; it does not download them.
To display advisory routing alongside deterministic replies, configure ENABLE_LAYA=true
and LAYA_MODEL_PATH to that local checkpoint. CPU inference uses two threads.
Unavailable, busy, oversized and malformed results fall back safely.
On 24 synthetic English dealership requests, SDK 0.3.26 returned 24 valid outputs and
22 correct labels, versus 24 correct baseline labels after repairing plural SUV recognition. The checkpoint warned that its
probabilities were uncalibrated. Keep routing advisory; no authorization or booking
decision uses its probabilities. See [review and receipts](docs/review-2026-10-04.md).

## Verify

```powershell
./scripts/verify.ps1 -Install
```

The verification installs development dependencies, scans source and local Markdown
links, runs regression/fault tests, exercises the actual Waitress server over HTTP,
and audits runtime dependencies. It makes zero paid API calls.
CI runs Windows and Ubuntu acceptance checks and retains HTTP/test/SBOM receipts.
Dependabot proposes dependency updates; it never merges them automatically.

## Container

```powershell
docker build -f src/demo/Dockerfile -t jack-ingram-chatbot .
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env -e HOST=0.0.0.0 -e COOKIE_SECURE=false jack-ingram-chatbot
```

The image runs as an unprivileged user. Supply SESSION_SECRET and a durable,
protected /app/instance volume if retaining data. The deployment template is
src/demo/app.yaml; automatic deployment is disabled. This review did not deploy
the app publicly.

## Receiving integrations

/health reports inventory=official_website_links, booking=unconfigured and crm=unconfigured.
The assistant links to current inventory on the official websites. Returning live
stock or prices inside chat requires an authorized current feed. Actual appointment scheduling
requires a booking API and confirmation receipt; CRM requires an approved destination
and delivery receipt. The demo provides a phone/website handoff and never reports a
reservation, lead delivery, financing approval or current offer.

Credentials previously appeared in public source, docs and deployment manifests.
Current files remove them. **Revoke and rotate the old Anthropic, Perplexity and
Firecrawl keys**; deletion from the current tree does not remove public Git history.

## Project map

- src/demo: Flask application, sourced dealership catalog, installable widget and demonstration page.
- scripts: source gates, Waitress acceptance, optional Laya evaluation.
- docs/review-2026-10-04.md: findings, registered checks and retained results.
- Other documentation: historical plans, not deployment evidence.
- Existing PRs #2/#3: separate repository hygiene/fleet proposals.

Application code uses the MIT license. The unchanged Carrera 4S model and its
presentation adaptations use CC BY-SA 4.0, credited to Karol Miklas; Three.js uses
MIT and Draco uses Apache 2.0. See [asset notices](src/demo/static/models/NOTICE.txt).
Business facts are a dated snapshot; confirm holiday changes with the dealership.

## Website integration and recent technology

Open /website-demo for a dealership presentation, or / for the larger assistant preview.
Install the widget through the dealership's CMS using an external script from your
deployed HTTPS chat service. See [installation and source review](docs/website-integration-2026-10-04.md)
for the concrete snippet, CSP, store selection, data refresh and acceptance results.
See [July–October technology review](docs/recent-technology-2026-10-04.md) for dated
primary sources and adoption decisions.

## Interactive showroom and buying assistant

Open `/vehicle-atlas?subject=systems` for the combined visual experience. It
starts on the licensed, recognizable Carrera 4S exterior (44 displayed surfaces;
model year unverified). Click the car or press X-ray to reveal the separate MY2026
non-hybrid 992.2 systems reconstruction: 77 selectable components, 165 meshes,
45,644 source triangles and a 1.53 MB internal GLB. Explode continuously, switch
system/wireframe modes, choose camera views, isolate parts, trace functional links
or play the guided tour. The two assets are hash verified and visually aligned by
their bounding envelopes. The licensed shell's own wheels and underbody disappear
in cutaway so they do not duplicate the illustrative assemblies. Sources and
evidence grades accompany every internal component. Their geometry is original
and representative; public specifications constrain the envelope, wheelbase,
tires and brake diameters. Neither asset is OEM manufacturing CAD or an exact VIN.

Ask `2025 Porsche 911 recalls` or `2026 Atlas recalls` in the website chat.
Official NHTSA issue, consequence and remedy appear inside the product. Reviewed
Porsche camera and lighting notices open the systems viewer with the notice and
component selected. A MY2025 notice retains MY2025 coverage even when the
illustration is the MY2026 reconstruction. Results require a manufacturer/VIN
check; they do not establish an individual car's recall or repair status. The
live lookup has a bounded cache and dated official-response fallback. A failed
lookup is shown as unavailable, never as zero recalls. Manufacturer do-not-drive
and park-outside flags are preserved. Service links are requests, not reservations.

Open `/vehicle-atlas` for the licensed Carrera 4S model by itself. Select geometry directly
or use its searchable component list. Separate parts, hide body panels, isolate a
component, focus it and restore the vehicle. The connected assistant applies bounded
viewer actions: try “show me the rear wheels” or “isolate the glass”.
The asset contains 45 meshes; 44 are vehicle surfaces in seven reviewed component
groups. A nonphysical source ground plane is preserved in the file and hidden in
the viewer. The model year is unspecified; it is not a VIN-specific listing or a
mechanical cutaway. Missing engine/transmission internals are stated explicitly.

Try “what is the best selling cars you have”, “compare Rogue and Atlas”, then
“I need 7 seats”. The assistant answers inside chat, distinguishes five-seat models
from three-row alternatives, and asks about budget. Manufacturer guides are marked
separately from dealer stock; unpublished sales rankings and counts are never invented.

The commercial and inventory browser on jackingram.com belong to the dealership.
This repository supplies the demo host page, installable chat widget, buying guides,
original systems reconstruction, interactive explorer, recall connections, backend
and private analytics. External website
handoffs are labeled; the demo's primary action now opens our explorer.

The compiled viewer is committed for Python-only startup and container use. To
rebuild it, install Node.js 24, then run `npm ci --ignore-scripts` and `npm run build`.
`npm test` checks component identity and projected part packing. CI rebuilds and
rejects generated-file drift on Windows and Ubuntu. The viewer loads all runtime
assets from its own server, with no frontend CDN. /vehicle-atlas has scoped blob
permissions for embedded texture decoding and Draco workers; other routes retain
their existing policy.

See [showroom acceptance and provenance](docs/vehicle-explorer-2026-10-04.md).
