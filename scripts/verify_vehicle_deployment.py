"""Check vehicle/advisor receiving behavior on a running installation; synthetic inputs."""

import argparse
import hashlib
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=15, trust_env=False) as client:
        receipts = []
        manifest = client.get("/api/vehicle-atlas").raise_for_status().json()
        model = client.get(manifest["asset_url"]).raise_for_status().content
        assert hashlib.sha256(model).hexdigest() == manifest["sha256"]
        assert len(model) == manifest["bytes"]
        for path in (
            "/vehicle-atlas",
            "/website-demo",
            "/static/atlas/atlas.js",
            "/static/atlas/draco/draco_decoder.js",
            "/static/models/NOTICE.txt",
        ):
            assert client.get(path).status_code == 200
        assert "connect-src 'self' blob:" in client.get("/vehicle-atlas").headers["Content-Security-Policy"]
        receipts.append(
            {
                "scenario": "shipped viewer, decoder and licensed model",
                "outcome": "Worked",
                "asset_sha256": manifest["sha256"],
                "bytes": len(model),
            }
        )
        context = {"vehicle_id": manifest["id"]}
        for message, expected in (
            ("show rear wheels", {"operation": "select", "component_id": "rear-wheels"}),
            ("isolate glass", {"operation": "isolate", "component_id": "glass"}),
            ("separate parts", {"operation": "separate"}),
            ("reset", {"operation": "reset"}),
        ):
            reply = (
                client.post("/api/chat", json={"message": message, "vehicle_context": context})
                .raise_for_status()
                .json()
            )
            assert reply["explorer_action"] == expected
        assert (
            client.post("/api/chat", json={"message": "show engine", "vehicle_context": context})
            .json()
            .get("explorer_action")
            is None
        )
        assert (
            client.post(
                "/api/chat",
                json={
                    "message": "show it",
                    "vehicle_context": {"vehicle_id": manifest["id"], "component_id": []},
                },
            ).status_code
            == 400
        )
        receipts.append(
            {
                "scenario": "component actions, unsupported internals and malformed context",
                "outcome": "Worked",
            }
        )
        original = (
            client.post("/api/chat", json={"message": "what is the best selling cars you have"})
            .raise_for_status()
            .json()
        )
        assert "sales ranking" in original["response"] and len(original["vehicle_cards"]) >= 2
        family = client.post("/api/chat", json={"message": "I need 7 seats"}).raise_for_status().json()
        assert family["vehicle_cards"] and all(v["seats_max"] >= 7 for v in family["vehicle_cards"])
        assert original["stock_verified"] is False and original["dealer_sales_rank"] is None
        chosen = (
            client.post(
                "/api/chat",
                json={
                    "message": "I want the Atlas",
                    "history": [{"role": "user", "content": "compare Rogue and Atlas"}],
                    "location_id": "nissan",
                },
            )
            .raise_for_status()
            .json()
        )
        assert chosen["location_id"] == "volkswagen" and chosen["brand"] == "volkswagen"
        assert any("jackingramvolkswagen.com" in link["url"] for link in chosen["links"])
        receipts.append(
            {
                "scenario": "owner question, seven-seat follow-up and chosen model showroom",
                "outcome": "Worked",
                "shortlist": [v["id"] for v in family["vehicle_cards"]],
            }
        )
        systems = client.get("/api/vehicle-atlas?subject=systems").raise_for_status().json()
        raw = client.get(systems["asset_url"]).raise_for_status().content
        assert hashlib.sha256(raw).hexdigest() == systems["sha256"]
        assert systems["model_year"] == 2026 and systems["hybrid"] is False
        reply = (
            client.post(
                "/api/chat", json={"message": "show engine", "vehicle_context": {"vehicle_id": systems["id"]}}
            )
            .raise_for_status()
            .json()
        )
        assert reply["explorer_action"] == {"operation": "select", "component_id": "engine"}
        assert "473 hp" in reply["response"] and reply["citations"]
        notice = client.get("/api/recalls?vehicle=porsche-911&year=2025").raise_for_status().json()
        assert notice["status"] in ("live", "saved_snapshot") and notice["vin_verified"] is False
        camera = next(c for c in notice["cards"] if c["campaign"] == "25V896000")
        assert camera["component_id"] == "rear-camera" and "year=2025" in camera["explorer_url"]
        assert "free of charge" in camera["remedy"]
        chat_notice = client.post("/api/chat", json={"message": "2025 Porsche 911 recalls", "analytics_consent": False}).raise_for_status().json()
        assert chat_notice["brand"] == "porsche" and chat_notice["recall_cards"]
        receipts.append(
            {
                "scenario": "MY2026 systems asset and engine action; official MY2025 recall-to-camera handoff",
                "outcome": "Worked",
                "components": len(systems["components"]),
                "mesh_count": systems["mesh_count"],
                "sha256": systems["sha256"],
                "recall_status": notice["status"],
                "campaign": camera["campaign"],
            }
        )
    result = {"base_url": args.base_url, "paid_calls": 0, "receipts": receipts}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
