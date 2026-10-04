import hashlib
import json
import struct
from pathlib import Path

import pytest

from src.demo.app import create_app
from src.demo.vehicle_atlas import ATLAS


@pytest.fixture
def client(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "atlas-test-session-secret-32-characters",
            "DATABASE": str(tmp_path / "atlas.db"),
            "CHAT_PROVIDER": "local",
            "ENABLE_LAYA": False,
            "RATE_LIMIT": 200,
        }
    ).test_client()


def test_asset_identity_license_and_every_component_is_real():
    asset = (Path(__file__).parents[1] / "static/models/porsche-911-carrera-4s.glb").read_bytes()
    assert hashlib.sha256(asset).hexdigest() == ATLAS["sha256"]
    assert struct.unpack_from("<I", asset, 8)[0] == len(asset) == ATLAS["bytes"]
    metadata = json.loads(asset[20 : 20 + struct.unpack_from("<I", asset, 12)[0]])
    assert metadata["asset"]["extras"]["author"].startswith(ATLAS["author"])
    assert metadata["asset"]["extras"]["license"].startswith("CC-BY-SA-4.0")
    assigned = [m for c in ATLAS["components"] for m in c["mesh_indices"]]
    assigned += [m["index"] for m in ATLAS["ignored_meshes"]]
    assert sorted(assigned) == list(range(len(metadata["meshes"])))
    assert ATLAS["model_year"] is None


def test_combined_showroom_uses_the_licensed_exterior_and_separate_systems(client):
    response = client.get("/api/vehicle-atlas?subject=systems")
    assert response.status_code == 200
    systems = response.json
    visual = systems["visual_reference"]
    exterior = (Path(__file__).parents[1] / "static/models/porsche-911-carrera-4s.glb").read_bytes()
    assert visual["sha256"] == hashlib.sha256(exterior).hexdigest() == ATLAS["sha256"]
    assert visual["bytes"] == len(exterior) and visual["mesh_count"] == ATLAS["mesh_count"]
    assert visual["model_year"] is None and visual["license"] == "CC BY-SA 4.0"
    omitted = {i for component in ATLAS["components"] if component["id"] in {"front-wheels", "rear-wheels", "underbody"} for i in component["mesh_indices"]}
    cutaway = set(visual["cutaway_mesh_indices"])
    assert cutaway and cutaway.isdisjoint(omitted)
    assert cutaway | omitted | {12} == set(range(ATLAS["mesh_count"]))
    page = client.get("/vehicle-atlas?subject=systems").get_data(as_text=True)
    assert "LICENSED EXTERIOR · ILLUSTRATIVE INTERNALS" in page
    assert "Its model year is unknown" in page


def test_atlas_and_decoders_ship_with_scoped_csp(client):
    for path in (
        "/vehicle-atlas",
        "/api/vehicle-atlas",
        "/static/atlas/atlas.js",
        "/static/atlas/draco/draco_decoder.js",
        "/static/atlas/draco/LICENSE.txt",
        "/static/models/NOTICE.txt",
    ):
        assert client.get(path).status_code == 200
    csp = client.get("/vehicle-atlas").headers["Content-Security-Policy"]
    assert "worker-src 'self' blob:" in csp and "img-src 'self' blob:" in csp
    assert "connect-src 'self' blob:" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "blob:" not in client.get("/").headers["Content-Security-Policy"]


def test_assistant_actions_and_missing_engine_are_honest(client):
    context = {"vehicle_id": ATLAS["id"]}
    for message, operation, component in (
        ("show me front wheels", "select", "front-wheels"),
        ("show me the rear wheels", "select", "rear-wheels"),
        ("isolate glass", "isolate", "glass"),
        ("separate parts", "separate", None),
        ("reset", "reset", None),
    ):
        r = client.post("/api/chat", json={"message": message, "vehicle_context": context})
        assert r.status_code == 200 and r.json["explorer_action"]["operation"] == operation
        assert r.json["explorer_action"].get("component_id") == component
    missing = client.post(
        "/api/chat", json={"message": "show me the engine", "vehicle_context": context}
    ).json
    assert "does not contain" in missing["response"] and "explorer_action" not in missing


@pytest.mark.parametrize(
    "message,expected",
    [
        ("x-ray", {"operation": "render", "value": "xray"}),
        ("show systems", {"operation": "render", "value": "systems"}),
        ("wireframe", {"operation": "render", "value": "wire"}),
        ("top view", {"operation": "camera", "value": "top"}),
        ("explode 50%", {"operation": "explode", "value": 0.5}),
        ("start tour", {"operation": "tour"}),
    ],
)
def test_atlas_exploration_commands(client, message, expected):
    reply = client.post(
        "/api/chat", json={"message": message, "vehicle_context": {"vehicle_id": ATLAS["id"]}}
    )
    assert reply.status_code == 200 and reply.json.get("explorer_action") == expected


@pytest.mark.parametrize(
    "context",
    [
        [],
        "glass",
        {},
        {"vehicle_id": "../private"},
        {"vehicle_id": ATLAS["id"], "component_id": []},
        {"vehicle_id": ATLAS["id"], "component_id": "engine"},
        {"vehicle_id": ATLAS["id"], "url": "http://evil.invalid"},
    ],
)
def test_untrusted_vehicle_context_contained(client, context):
    assert (
        client.post("/api/chat", json={"message": "show it", "vehicle_context": context}).status_code == 400
    )
