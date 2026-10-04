"""Bounded public-page collector. Produces review candidates, never edits the approved catalog."""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

SITES = {
    "group": "https://www.jackingram.com/",
    "audi": "https://www.audimontgomery.com/en/",
    "mercedes": "https://www.jackingrammercedes.com/",
    "nissan": "https://www.jackingramnissan.com/",
    "porsche": "https://jackingrammotors.porsche.com/en",
    "volkswagen": "https://www.jackingramvolkswagen.com/",
    "volvo": "https://www.jackingramvolvocars.com/",
    "signature": "https://www.jackingramsignatureusedcars.com/",
    "body-shop": "https://www.jackingrambodyshop.com/",
}
ALLOWED_HOSTS = {urlsplit(url).hostname for url in SITES.values()}
AGENT = "JackIngramCatalogReview/1.0"


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.links, self.structured = [], [], []
        self.skip, self.href, self.label, self.script, self.ld = 0, None, [], [], False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
            self.ld = tag == "script" and attrs.get("type") == "application/ld+json"
            self.script = []
        if tag == "a":
            self.href, self.label = attrs.get("href"), []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            if self.ld:
                try:
                    self.structured.append(json.loads("".join(self.script)))
                except ValueError:
                    pass
            self.skip, self.ld = max(0, self.skip - 1), False
        if tag == "a" and self.href:
            self.links.append({"text": " ".join(self.label), "href": self.href})
            self.href = None

    def handle_data(self, data):
        if self.ld:
            self.script.append(data)
        if not self.skip and data.strip():
            line = " ".join(data.split())
            self.lines.append(line)
            if self.href:
                self.label.append(line)


def fetch(client, url):
    """Validate every redirect and cap the body, without a generic URL-fetch endpoint."""
    for _ in range(4):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username:
            raise ValueError("destination_not_allowlisted")
        with client.stream("GET", url) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 4_000_000:
                    raise ValueError("page_too_large")
                chunks.append(chunk)
            return url, b"".join(chunks)
    raise ValueError("redirect_limit")


def business_facts(structured):
    """Ignore ads and descriptive copy when proposing changes to business facts."""
    fields = ("name", "telephone", "address", "openingHoursSpecification")

    def extract(row):
        result = {key: row[key] for key in fields if key in row}
        if row.get("department"):
            result["department"] = [extract(dept) for dept in row["department"]]
        return result

    return [extract(row) for row in structured if isinstance(row, dict)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Previous collection.json for fact-change review")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    outcomes = []
    with httpx.Client(timeout=20, trust_env=False, headers={"User-Agent": AGENT}) as client:
        for key, url in SITES.items():
            item = {"id": key, "url": url, "retrieved_at": datetime.now(timezone.utc).isoformat()}
            try:
                _, robots = fetch(client, urljoin(url, "/robots.txt"))
                policy = RobotFileParser()
                policy.parse(robots.decode("utf-8", errors="replace").splitlines())
                if not policy.can_fetch(AGENT, url):
                    raise ValueError("robots_disallowed")
                time.sleep(1)
                resolved, body = fetch(client, url)
                page = Page()
                page.feed(body.decode("utf-8", errors="replace"))
                item.update(status="worked", resolved_url=resolved, sha256=hashlib.sha256(body).hexdigest())
                item.update(links=page.links, structured=page.structured)
                item["facts"] = business_facts(page.structured)
                (args.output / f"{key}.txt").write_text("\n".join(page.lines), encoding="utf-8")
            except (httpx.HTTPError, ValueError) as error:
                item.update(status="blocked", reason=type(error).__name__ + ": " + str(error))
            outcomes.append(item)
            print(key, item["status"])
    (args.output / "collection.json").write_text(json.dumps(outcomes, indent=2), encoding="utf-8")
    if args.baseline:
        previous = {row["id"]: row for row in json.loads(args.baseline.read_text(encoding="utf-8"))}
        changes = compare_facts(outcomes, previous)
        (args.output / "changes.json").write_text(json.dumps(changes, indent=2), encoding="utf-8")


def compare_facts(outcomes, previous):
    return [
        {
            "id": row["id"],
            "status": row["status"],
            "facts_changed": (
                row["facts"] != business_facts(previous.get(row["id"], {}).get("structured", []))
            )
            if row["status"] == "worked" and row.get("facts")
            else None,
        }
        for row in outcomes
    ]


if __name__ == "__main__":
    main()
