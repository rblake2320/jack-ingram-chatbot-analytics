"""NHTSA client: tolerant parsing, cache, retries, circuit breaker, input hardening, HTTP mapping.

Fixtures mirror the documented public response shapes. Live endpoints are not reachable from
CI sandboxes; run ``python -m chatbot.cli smoke-nhtsa <VIN>`` on a networked machine to verify.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from chatbot.integrations.nhtsa import NhtsaClient
from chatbot.resilience import UpstreamError

VIN = "1HGCM82633A004352"
DECODE = {
    "Count": 1,
    "Message": "Results returned successfully",
    "Results": [{"Make": "HONDA", "Model": "Accord", "ModelYear": "2003", "Trim": "EX-V6", "BodyClass": "Coupe",
                 "DriveType": "", "FuelTypePrimary": "Gasoline", "EngineCylinders": "6", "ErrorCode": "0",
                 "ErrorText": "0 - VIN decoded clean.", "Series": "Not Applicable"}],
}  # fmt: skip
RECALLS = {"Count": 1, "results": [{"NHTSACampaignNumber": "12V176000", "Component": "AIR BAGS",
                                    "Summary": "S" * 900, "Consequence": "c", "Remedy": "r", "parkIt": False}]}  # fmt: skip


async def _no_sleep(_seconds: float) -> None:
    return None


def make_client(services, handler) -> tuple[NhtsaClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    client = NhtsaClient(
        http, services.cache, vpic_base="https://vpic.test/api", api_base="https://api.test", sleep=_no_sleep
    )
    return client, seen


def run(coro):
    return asyncio.run(coro)


def test_decode_parses_tolerantly_and_caches(services):
    client, seen = make_client(services, lambda r: httpx.Response(200, json=DECODE))
    first = run(client.decode_vin(VIN.lower()))
    assert first["decoded"] and first["make"] == "HONDA" and first["year"] == "2003"
    assert first["series"] is None and first["drive_type"] is None  # "Not Applicable" / "" -> None
    assert seen[0].url.path == f"/api/vehicles/DecodeVinValues/{VIN}" and seen[0].url.params["format"] == "json"
    run(client.decode_vin(VIN))
    assert len(seen) == 1  # served from the shared cache


def test_invalid_vin_never_hits_network(services):
    client, seen = make_client(services, lambda r: httpx.Response(200, json=DECODE))
    with pytest.raises(ValueError):
        run(client.decode_vin("1HGCM82643A004352"))
    assert seen == []


def test_undecodable_vin_reported(services):
    undecodable = {"Results": [{"ErrorCode": "8", "ErrorText": "No detailed data"}]}
    client, _ = make_client(services, lambda r: httpx.Response(200, json=undecodable))
    assert run(client.decode_vin(VIN))["decoded"] is False


def test_retries_transient_failures(services):
    responses = iter([httpx.Response(503), httpx.Response(502), httpx.Response(200, json=DECODE)])
    client, seen = make_client(services, lambda r: next(responses))
    assert run(client.decode_vin(VIN))["decoded"]
    assert len(seen) == 3


def test_persistent_failure_opens_circuit(services):
    client, seen = make_client(services, lambda r: httpx.Response(500))
    for i in range(5):
        with pytest.raises(UpstreamError) as exc:
            run(client.recalls("Audi", "Q5", 2020 + (i % 2)))
        assert exc.value.kind == "unavailable"
    calls = len(seen)
    with pytest.raises(UpstreamError) as exc:
        run(client.recalls("Audi", "Q7", 2022))
    assert exc.value.kind == "circuit_open" and len(seen) == calls


def test_client_errors_do_not_trip_breaker(services):
    client, _ = make_client(services, lambda r: httpx.Response(404))
    for _ in range(8):
        with pytest.raises(UpstreamError) as exc:
            run(client.recalls("Audi", "Q5", 2021))
        assert exc.value.kind == "rejected"
    assert client.breaker.state == "closed"


def test_malformed_json_and_timeouts(services):
    client, _ = make_client(services, lambda r: httpx.Response(200, content=b"<html>oops"))
    with pytest.raises(UpstreamError) as exc:
        run(client.recalls("Audi", "Q5", 2021))
    assert exc.value.kind == "bad_response"

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    client2, seen = make_client(services, timeout)
    with pytest.raises(UpstreamError) as exc:
        run(client2.recalls("Audi", "Q5", 2022))
    assert exc.value.kind == "timeout" and len(seen) == 3


def test_recalls_accept_either_key_casing_and_clip(services):
    client, _ = make_client(services, lambda r: httpx.Response(200, json=RECALLS))
    result = run(client.recalls("Honda", "Accord", 2003))
    assert result["count"] == 1 and len(result["recalls"][0]["summary"]) <= 600
    upper = {"Count": 1, "Results": RECALLS["results"]}
    client2, _ = make_client(services, lambda r: httpx.Response(200, json=upper))
    assert run(client2.recalls("Honda", "Accord", 2004))["count"] == 1


@pytest.mark.parametrize("model", ["../../admin", "Q5/../../x", "Q5?x=1", "<script>", "a" * 41, ""])
def test_hostile_make_model_rejected_before_network(services, model):
    client, seen = make_client(services, lambda r: httpx.Response(200, json=RECALLS))
    with pytest.raises(ValueError):
        run(client.recalls("Audi", model, 2021))
    with pytest.raises(ValueError):
        run(client.safety_ratings("Audi", model, 2021))
    assert seen == []


def test_safety_ratings_two_step_and_path_encoding(services):
    def handler(request):
        if "/VehicleId/" in request.url.path:
            return httpx.Response(200, json={"Results": [{"VehicleDescription": "2021 Mercedes-Benz C-Class 4DR",
                                                          "OverallRating": "5", "RolloverRating": "4"}]})  # fmt: skip
        return httpx.Response(200, json={"Results": [{"VehicleId": 15000, "VehicleDescription": "x"}]})

    client, seen = make_client(services, handler)
    result = run(client.safety_ratings("Mercedes-Benz", "C-Class 300", 2021))
    assert result["vehicles"][0]["overall"] == "5" and result["vehicles"][0]["rollover"] == "4"
    assert "C-Class%20300" in str(seen[0].url)


def test_disabled_integration(services):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=DECODE)))
    client = NhtsaClient(http, services.cache, vpic_base="https://x", api_base="https://y", enabled=False)
    with pytest.raises(UpstreamError) as exc:
        run(client.decode_vin(VIN))
    assert exc.value.kind == "not_configured"


def test_http_api_maps_errors(client, router):
    router.add("GET", "vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues", DECODE)
    ok = client.get(f"/api/vehicles/vin/{VIN}")
    assert ok.status_code == 200 and ok.json()["model"] == "Accord"
    assert client.get("/api/vehicles/vin/NOTAVIN").status_code == 422
    router.add("GET", "api.nhtsa.gov/recalls", lambda r: httpx.Response(404))
    assert client.get("/api/vehicles/recalls", params={"make": "Audi", "model": "Q5", "year": 2021}).status_code == 503


def test_fallback_vin_answer_uses_nhtsa(client, router):
    router.add("GET", "vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues", DECODE)
    router.add("GET", "api.nhtsa.gov/recalls/recallsByVehicle", RECALLS)
    response = client.post("/api/chat", json={"message": f"what is {VIN}?"}).json()
    assert "2003 HONDA Accord" in response["reply"] and "1 recall" in response["reply"]
