"""Bounded buying advice from reviewed model guides, never invented dealer stock."""

import json
import re
from datetime import date
from pathlib import Path

GUIDES = json.loads((Path(__file__).parent / "data/vehicle_guides.json").read_text(encoding="utf-8"))


def names_in(text):
    return [
        v
        for v in GUIDES["vehicles"]
        if any(re.search(r"\b" + re.escape(a) + r"\b", text) for a in v["aliases"])
    ]


def advise(message, history, location_id=None):
    text = message.lower()
    if re.search(r"\b(sample|demonstration)\b", text):
        return None
    trigger = r"\b(compare|comparison|choose|recommend|recommendation|family|seats?|passengers?|popular|best|selling|sells|suvs?|budget|3d|explore)\b"
    previous = " ".join(h.get("content", "").lower() for h in history[-10:] if h.get("role") == "user")
    followup = re.search(r"\b(yes|no|luxury|daily|commute|new|used|electric|hybrid)\b|\$\d", text)
    named_choice = names_in(text) and (
        re.search(trigger, previous) or re.search(r"\b(want|about|tell|considering)\b", text)
    )
    if not (re.search(trigger, text) or (followup and re.search(trigger, previous)) or named_choice):
        return None
    age = (date.today() - date.fromisoformat(GUIDES["reviewed_at"])).days
    if age > 30:
        return {
            "response": "The model guides need a refresh before I can compare specifications. Which model would you like the dealership to confirm?",
            "vehicle_cards": [],
            "stock_verified": False,
            "dealer_sales_rank": None,
            "data_status": "needs_refresh",
            "source": "official_website",
            "citations": [],
        }
    context = previous + " " + text
    selected = names_in(text)
    seats = re.findall(
        r"\b([1-9]|one|two|three|four|five|six|seven|eight|nine)\s*(?:seats?|passengers?|people)\b", context
    )
    words = dict(zip(("one", "two", "three", "four", "five", "six", "seven", "eight", "nine"), range(1, 10)))
    needed = (int(seats[-1]) if seats[-1].isdigit() else words[seats[-1]]) if seats else None
    explorer_request = (
        len(selected) == 1 and selected[0]["id"] == "911" and bool(re.search(r"\b(3d|explore)\b", text))
    )
    if explorer_request:
        needed = None
    if "cross sport" in text:
        return {
            "response": "Atlas Cross Sport is a two-row, five-seat model; the three-row Atlas is a different vehicle. I can compare the three-row Atlas with Rogue, XC90 or Pathfinder here. How many passengers do you need to carry?",
            "vehicle_cards": [],
            "stock_verified": False,
            "dealer_sales_rank": None,
            "source": "official_website",
            "data_status": "model_guide_not_stock",
            "citations": [],
        }
    if not selected:
        if needed and needed > 5:
            selected = [v for v in GUIDES["vehicles"] if (v["seats_max"] or 0) >= needed]
        elif "electric" in text:
            return {
                "response": "These reviewed guides do not cover a fully electric vehicle yet. XC90 mild hybrid and GLC 300 mild hybrid use gasoline; they are not fully electric. Would you like an electric SUV or a plug-in hybrid?",
                "vehicle_cards": [],
                "stock_verified": False,
                "dealer_sales_rank": None,
                "source": "official_website",
                "data_status": "model_guide_not_stock",
                "citations": [],
            }
        elif "luxury" in context:
            selected = [v for v in GUIDES["vehicles"] if v["id"] in ("q5", "glc", "xc90")]
        else:
            selected = [v for v in GUIDES["vehicles"] if v["id"] in ("rogue", "atlas", "q5")]
        if location_id and not needed:
            matching = [v for v in GUIDES["vehicles"] if v["location_id"] == location_id]
            selected = matching or selected
    rank = bool(re.search(r"best.?selling|sells|sales|most popular", text))
    lines = [
        "Jack Ingram's dealer sales ranking is not published in our reviewed sources, so I cannot name its best seller. Here is a shortlist based on your needs:"
        if rank
        else "Explore the Porsche model here:"
        if explorer_request
        else "Here is the reviewed model guide:"
        if len(selected) == 1
        else "Here is how the reviewed models differ:"
    ]
    if needed:
        lines.append(f"For {needed} passengers, check the exact seat configuration before choosing.")
    if not selected:
        lines.append("None of these reviewed models meets that seating requirement.")
    for v in selected:
        lines.append(f"{v['name']} — {v['summary']} {v['tradeoff']}")
    lines.append("These are model guides, not verified dealer stock, sales counts or quoted prices.")
    if "$" in text or "budget" in text:
        lines.append(
            "Your budget needs to include taxes and fees; I cannot promise a fit without a current out-the-door quote."
        )
    lines.append(
        "Open the 3D explorer below, then try “show rear wheels” or “isolate glass”."
        if explorer_request
        else "What is your budget, and are you considering new or used?"
        if needed or len(selected) <= 2
        else "How many passengers do you carry, and what is your budget?"
    )
    cards = [{**v, "data_status": GUIDES["data_status"]} for v in selected]
    citations = [
        {
            "label": v["name"] + " manufacturer guide",
            "url": v["source_url"],
            "reviewed_at": GUIDES["reviewed_at"],
        }
        for v in selected
    ]
    for v in selected:
        if v.get("capacity_source_url"):
            citations.append(
                {
                    "label": v["name"] + " seating specification",
                    "url": v["capacity_source_url"],
                    "reviewed_at": GUIDES["reviewed_at"],
                }
            )
    return {
        "response": "\n\n".join(lines),
        "vehicle_cards": cards,
        "citations": citations,
        "stock_verified": False,
        "dealer_sales_rank": None,
        "data_status": GUIDES["data_status"],
        "source": "official_website",
    }
