# Website integration and official location review

The assistant is an installable website widget. The standalone assistant at /
and the host-site presentation at /website-demo are dealership demonstrations.
No changes have been published to Jack Ingram's live website.

## Install through the dealership CMS

Deploy the chat service on an operator-controlled HTTPS hostname. Configure
SESSION_SECRET, protected durable SQLite storage, TRUSTED_HOSTS for that chat
hostname, COOKIE_SECURE=true and an ADMIN_TOKEN for the analytics operator.
The widget's signed session remains in iframe memory and works without cookies.

Replace CHAT_SERVICE_HOST below with that deployed chat hostname, then add this
through Dealer.com or the relevant store site's approved custom-code area:

```html
<script src="https://CHAT_SERVICE_HOST/static/embed.js" defer></script>
```

For a store website, add data-location="nissan" (or audi, mercedes, porsche,
volkswagen, volvo, signature, body-shop). The group site can omit it.
The loader creates a floating launcher, uses Shadow DOM for isolated styles,
and lazily opens an iframe hosted by the chat service.

The existing website CSP must permit the chat hostname in script-src, style-src
and frame-src. The assistant's own /widget response restricts frame-ancestors to
the exact allowed parent. Other routes, including analytics, keep frame-ancestors
'self'. The official site origins are allowed by default; WIDGET_ORIGINS permits
additional exact HTTPS origins, or loopback HTTP origins for tests. Paths, wildcards
and arbitrary HTTP hosts are rejected. A close-only postMessage is accepted only
from the iframe window at the chat origin. Escape and the close button return
focus to the launcher. No transcript or session token is sent to the host page.

POST APIs retain same-origin protections. The iframe sends a signed, hour-limited
X-Chat-Session token. Sessions are separate from standalone cookies; reset/deletion
revokes the previous conversation token. A session deleted during a request cannot
be recreated by the pending widget request.

## Published location information

Reviewed October 4, 2026. Each location in src/demo/data/dealerships.json carries
its source URL, collection timestamp, departments, weekly schedules and official
action links. Hours are shown in Central Time; holiday changes require confirmation.

| Location | Published address | Phone used | Source |
| --- | --- | --- | --- |
| Audi Montgomery | 241 Eastern Blvd, Montgomery, AL 36117 | 334-578-0470 sales; 334-578-0575 service; 334-578-0466 parts | [Audi](https://www.audimontgomery.com/en/) |
| Jack Ingram Mercedes-Benz | 217 Eastern Blvd, Montgomery, AL 36117-2009 | 334-274-4900 | [Mercedes-Benz](https://www.jackingrammercedes.com/) |
| Jack Ingram Nissan | 227 Eastern Blvd, Montgomery, AL 36117 | 334-270-6000 | [Nissan](https://www.jackingramnissan.com/) |
| Jack Ingram Porsche | 245 Eastern Boulevard, Montgomery, AL 36117 | 334-420-9902 | [Porsche](https://jackingrammotors.porsche.com/en) |
| Jack Ingram Volkswagen | 255 Eastern Blvd, Montgomery, AL 36117 | 334-420-7700 | [Volkswagen](https://www.jackingramvolkswagen.com/) |
| Jack Ingram Volvo Cars | 267 Eastern Blvd, Montgomery, AL 36117-2074 | 334-420-7701 | [Volvo](https://www.jackingramvolvocars.com/) |
| Signature Used Cars | 235 N Eastern Blvd, Montgomery, AL 36117 | 334-420-9900 | [Signature](https://www.jackingramsignatureusedcars.com/) |
| Jack Ingram Body Shop | 5648 Eddins Road, Montgomery, AL 36117 | 334-271-0638 | [Body Shop](https://www.jackingrambodyshop.com/) |

The [group website](https://www.jackingram.com/) uses red #c2272c, black and white;
the action color was measured in the rendered official page. The demonstration and
widget use that palette and sans-serif typography.

## Conflicts and maintenance

- The original repository's 1000 Eastern Blvd address and shared generic hours
  have been removed from active responses.
- Audi's visible sales schedule says 08:30–19:00 weekdays / 08:30–18:00 Saturday,
  while its JSON-LD says 08:30–18:00 / 08:30–17:30. The assistant shows the visible
  schedule and the conflict, with a call-to-confirm instruction.
- Volvo's official header, structured data and dynamic phone replacement show
  different numbers. The directory uses its published header number 334-420-7701
  and retains the discrepancy. Unpublished department/weekend hours remain
  “Not published; call”, rather than being inferred closed.
- The Body Shop's old brand menu includes misspelled/stale domains. The assistant
  uses the current brand sites linked by the group directory.
- The collector read eight of nine homepages (group plus eight stores). Porsche's
  robots request returned HTTP 429, so the collector stopped that site's requests.
  Porsche's public homepage and action links were read with the web tool.

Run a bounded refresh into a review directory:

```powershell
.venv/Scripts/python.exe scripts/collect_dealership_sources.py --output work/source-review --baseline work/prior-source-review/collection.json
```

Omit --baseline for a first collection. The collector checks robots, waits between
requests, permits only the nine official hosts, validates redirects and caps bodies
at 4 MB. It produces candidates, provenance and business-fact comparisons; it never
overwrites the approved catalog. Reconcile visible/structured conflicts before
updating the catalog's review date. After 30 days, the assistant asks for a refresh
instead of repeating cached weekly hours. Ads/descriptive copy are excluded from
the JSON-LD fact-change comparison. The group homepage has no JSON-LD business
record, so its fact comparison is unknown and its visible contact information
requires manual review. An unreadable source is unknown, not a detected change.

## Acceptance

| Scenario | Observed result | Evidence |
| --- | --- | --- |
| Store-specific service hours, addresses, contextual follow-up and sources | Worked | test_website.py; website-pytest.txt |
| Cross-origin widget on 127.0.0.1 with iframe on localhost | Worked | IAB desktop and Chrome browser interactions; website-browser.json |
| Typed form submission | Failed initially because iframe sandbox blocked forms; repaired and retested Worked | Browser receipt |
| Chrome mobile viewport, measured 390 × 844 CSS pixels | Worked, no horizontal page overflow | website-widget-mobile.png and browser receipt |
| Signed sessions with no cookies, reset/deletion and stale-token rejection | Worked | website-http.json |
| Approved parent embedding; unapproved parent/admin protection | Worked | HTTP tests and built Linux container |
| Installed on the real dealership website | Blocked | No dealership CMS access or deployed HTTPS chat hostname is configured. The installable snippet above is ready for their site operator. |
| In-chat live stock / booking confirmation / CRM receipt | Blocked | Current /health exposes official inventory links and unconfigured booking/CRM; no authorized feed or receiving credentials are supplied. Official inventory and scheduling-page handoffs are implemented and tested. |

The full review remains in [the initial audit](review-2026-10-04.md).
New website evidence supersedes its initial standalone/reference-data behavior.
Recent technology choices are in [the dated research](recent-technology-2026-10-04.md).
