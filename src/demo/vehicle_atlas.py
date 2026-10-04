"""One reviewed component manifest drives both the viewer and chat actions."""

import json
import re
from pathlib import Path

ATLAS = json.loads((Path(__file__).parent / "data/vehicle_atlas.json").read_text(encoding="utf-8"))
COMPONENTS = {row["id"]: row for row in ATLAS["components"]}
SYSTEMS_ATLAS = json.loads(
    (Path(__file__).parent / "data/porsche_9922_systems.json").read_text(encoding="utf-8")
)
ATLASES = {ATLAS["id"]: ATLAS, SYSTEMS_ATLAS["id"]: SYSTEMS_ATLAS}


def valid_context(value):
    return (
        isinstance(value, dict)
        and set(value) <= {"vehicle_id", "component_id"}
        and isinstance(value.get("vehicle_id"), str)
        and value.get("vehicle_id") in ATLASES
        and (
            value.get("component_id") is None
            or (
                isinstance(value.get("component_id"), str)
                and value["component_id"] in {c["id"] for c in ATLASES[value["vehicle_id"]]["components"]}
            )
        )
    )


def answer(message, context):
    text = message.lower()
    atlas = ATLASES[context["vehicle_id"]]
    components = {row["id"]: row for row in atlas["components"]}
    base = {
        "intent": "other",
        "brand": "porsche",
        "source": "public_systems_reconstruction" if atlas is SYSTEMS_ATLAS else "vehicle_visual_reference",
        "usage": {},
        "links": [],
        "citations": [],
        "data_status": "representative_systems_not_stock"
        if atlas is SYSTEMS_ATLAS
        else "visual_reference_not_stock",
        "stock_verified": False,
    }
    if atlas is ATLAS and re.search(r"\b(engine|motor|transmission|suspension|cutaway|brakes?)\b", text):
        return {
            **base,
            "response": "This Carrera 4S asset does not contain a verified engine, transmission, suspension or brake cutaway. I can show its body panels, wheels, glazing, front fascia, trim or simple underbody surface. Which would you like to inspect?",
        }
    action = None
    if re.search(r"\b(reset|restore|assemble)\b", text):
        action = {"operation": "reset"}
        response = "Restoring the full assembled vehicle and its starting view."
    elif re.search(r"\b(tour|walkthrough)\b", text):
        action = {"operation": "tour"}
        response = "Starting a guided tour: exterior, transparent body, component colors, spatial explosion and reassembly. You can stop it at any time."
    elif re.search(r"\b(x.?ray|wireframe|systems|exterior)\b", text):
        value = (
            "xray"
            if re.search(r"x.?ray", text)
            else "wire"
            if "wireframe" in text
            else "systems"
            if "systems" in text
            else "solid"
        )
        action = {"operation": "render", "value": value}
        response = "Changing the display mode. X-ray reveals only supplied geometry; system colors identify visual component groups."
    elif re.search(r"\b(top|side|front|rear)\s+view\b", text):
        value = re.search(r"\b(top|side|front|rear)\s+view\b", text).group(1)
        action = {"operation": "camera", "value": value}
        response = "Moving to the " + value + " camera view."
    elif re.search(r"\bexplode\b", text):
        percent = re.search(r"\b(\d{1,3})\s*%", text)
        amount = min(int(percent.group(1)), 100) / 100 if percent else 1
        action = {"operation": "explode", "value": amount}
        response = f"Animating the spatial exploded view to {amount:.0%}. Parts retain their identity and original scale. This is an illustrative layout, not an assembly procedure."
    elif re.search(r"\bseparate\b", text):
        action = {"operation": "separate"}
        response = f"Separating {len(atlas['components'])} component groups so you can select and inspect them. This shows explanatory geometry, not a mechanical assembly procedure."
    elif re.search(r"\b(peel|hide body|remove body)\b", text):
        action = {"operation": "peel"}
        response = "Hiding the body layer to reveal the remaining geometry. The systems model uses representative reconstructed components; the exterior reference has limited internal coverage."
    else:
        matches = [
            (len(alias), c)
            for c in atlas["components"]
            for alias in c["aliases"]
            if re.search(r"\b" + re.escape(alias) + r"\b", text)
        ]
        component = max(matches, key=lambda match: match[0])[1] if matches else None
        component = component or components.get(context.get("component_id"))
        if component:
            action = {
                "operation": "isolate"
                if "isolat" in text or "only" in text
                else "trace"
                if "trace" in text
                else "hide"
                if "hide" in text or "remove" in text
                else "select",
                "component_id": component["id"],
            }
            response = component["label"] + "\n\n" + component["description"] + "\n\n" + component["question"]
            if atlas is SYSTEMS_ATLAS:
                response += (
                    "\n\nGeometry: " + component["geometry_grade"] + ". Model: MY2026 992.2, non-hybrid."
                )
                base["citations"] = [
                    {"label": source["title"], "url": source["url"], "reviewed_at": source["checked_at"]}
                    for source in atlas["sources"]
                    if source["id"] in component["source_ids"]
                ]
        else:
            response = "Try “show me the front wheels”, “isolate the glass”, “separate the parts” or “reset”. You can also select a component in the model or the parts list."
    return {**base, "response": response, **({"explorer_action": action} if action else {})}
