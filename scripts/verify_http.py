"""Exercise the actual Waitress entry point and a real local Messages API fixture."""

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.demo.claude_client import ClaudeClient, ProviderError  # noqa: E402


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MessagesFixture(BaseHTTPRequestHandler):
    mode = "success"
    received = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).received.append(body)
        if self.mode == "error":
            self.send_response(500)
            payload = {"error": "synthetic private diagnostic"}
        elif self.mode == "truncated":
            self.send_response(200)
            payload = {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "unfinished"}]}
        else:
            self.send_response(200)
            payload = {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "fixture reply"}],
                "usage": {"input_tokens": 4, "output_tokens": 3},
            }
        raw = json.dumps(payload).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--laya-model-path", default="")
    args = parser.parse_args()
    receipts = []
    with tempfile.TemporaryDirectory() as temporary:
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = dict(
            os.environ,
            CHAT_PROVIDER="local",
            ANTHROPIC_API_KEY="",
            ENABLE_LAYA="false",
            HOST="127.0.0.1",
            PORT=str(port),
            SESSION_SECRET="synthetic-session-key-at-least-32-characters",
            ADMIN_TOKEN="synthetic-admin-token-at-least-32-characters",
            CHAT_DATABASE=str(Path(temporary) / "chat.db"),
            COOKIE_SECURE="false",
        )
        if args.laya_model_path:
            env.update(ENABLE_LAYA="true", LAYA_MODEL_PATH=args.laya_model_path)
        with (Path(temporary) / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "src.demo.app"],
                env=env,
                cwd=Path(__file__).resolve().parents[1],
                stdout=log,
                stderr=log,
            )
            try:
                with (
                    httpx.Client(base_url=base, timeout=10, trust_env=False) as a,
                    httpx.Client(base_url=base, timeout=10, trust_env=False) as b,
                ):
                    for _ in range(600 if args.laya_model_path else 100):
                        if process.poll() is not None:
                            raise RuntimeError(
                                "Waitress exited: " + (Path(temporary) / "server.log").read_text()
                            )
                        try:
                            if a.get("/health").status_code == 200:
                                break
                        except httpx.ConnectError:
                            time.sleep(0.1)
                    else:
                        raise RuntimeError("Waitress startup deadline exceeded")
                    assert a.get("/").status_code == a.get("/static/chat.js").status_code == 200
                    ra = a.post("/api/chat", json={"message": "Audi inventory"})
                    rb = b.post("/api/chat", json={"message": "Nissan hours"})
                    assert (
                        ra.json()["links"][0]["kind"] == "inventory"
                        and "Monday–Friday" in rb.json()["response"]
                    )
                    assert ra.json()["conversation_id"] != rb.json()["conversation_id"]
                    if args.laya_model_path:
                        assert a.get("/health").json()["laya"] == "ready_advisory"
                        assert ra.json()["routing_advice"]["status"] == "advisory"
                        receipts.append(
                            {
                                "scenario": "exact local Laya advisory through shipped HTTP",
                                "outcome": "Worked",
                                "routing": ra.json()["routing_advice"],
                            }
                        )
                    receipts.append(
                        {"scenario": "shipped Waitress boot and two sessions", "outcome": "Worked"}
                    )
                    manifest = a.get("/api/vehicle-atlas").json()
                    model = a.get(manifest["asset_url"]).content
                    assert hashlib.sha256(model).hexdigest() == manifest["sha256"]
                    assert len(model) == manifest["bytes"]
                    page = a.get("/vehicle-atlas")
                    assert (
                        page.status_code == 200
                        and "connect-src 'self' blob:" in page.headers["Content-Security-Policy"]
                    )
                    assert a.get("/static/atlas/atlas.js").status_code == 200
                    context = {"vehicle_id": manifest["id"]}
                    action = a.post(
                        "/api/chat", json={"message": "show me the rear wheels", "vehicle_context": context}
                    ).json()
                    assert action["explorer_action"] == {"operation": "select", "component_id": "rear-wheels"}
                    missing = a.post(
                        "/api/chat", json={"message": "show engine", "vehicle_context": context}
                    ).json()
                    assert "does not contain" in missing["response"] and "explorer_action" not in missing
                    shortlist = a.post(
                        "/api/chat", json={"message": "what is the best selling cars you have"}
                    ).json()
                    assert "sales ranking" in shortlist["response"] and len(shortlist["vehicle_cards"]) >= 2
                    family = a.post("/api/chat", json={"message": "I need 7 seats"}).json()
                    assert all(v["seats_max"] >= 7 for v in family["vehicle_cards"])
                    receipts.append(
                        {
                            "scenario": "vehicle asset integrity, exact component actions, honest missing engine and buying follow-up through shipped HTTP",
                            "outcome": "Worked",
                            "sha256": manifest["sha256"],
                            "model_bytes": len(model),
                            "shortlist": [v["id"] for v in family["vehicle_cards"]],
                        }
                    )
                    assert a.post("/api/chat", json={"message": []}).status_code == 400
                    assert a.post("/api/chat", json={"message": "a" * 20000}).status_code == 413
                    assert (
                        a.post(
                            "/api/chat",
                            json={"message": "hi"},
                            headers={"Origin": "https://untrusted.invalid"},
                        ).status_code
                        == 403
                    )
                    receipts.append({"scenario": "invalid body and origin controls", "outcome": "Worked"})
                    auth = {"Authorization": "Bearer " + env["ADMIN_TOKEN"]}
                    assert a.get("/api/analytics").status_code == 401
                    assert a.get("/api/analytics", headers=auth).json()["messages"] == 0
                    a.post("/api/chat", json={"message": "Nissan inventory", "analytics_consent": True})
                    assert a.get("/api/analytics", headers=auth).json()["messages"] == 1
                    a.post("/api/privacy", json={})
                    assert a.get("/api/analytics", headers=auth).json()["messages"] == 0
                    receipts.append(
                        {"scenario": "consent, admin protection and deletion", "outcome": "Worked"}
                    )
                    old = b.post("/api/chat", json={"message": "service"}).json()["conversation_id"]
                    assert b.post("/api/reset", json={}).json()["conversation_id"] != old
                    assert (
                        "No appointment has been reserved"
                        in b.post("/api/chat", json={"message": "Book a Nissan test drive"}).json()[
                            "response"
                        ]
                    )
                    receipts.append({"scenario": "reset and honest booking handoff", "outcome": "Worked"})

                    # Simulate third-party cookies being unavailable; the widget uses its scoped token.
                    with httpx.Client(base_url=base, timeout=10, trust_env=False) as widget_client:
                        page = widget_client.get("/widget", params={"parent": base})
                        token = re.search(r'data-session-token="([^"]+)"', page.text).group(1)
                        widget_client.cookies.clear()
                        headers = {"X-Chat-Session": token, "Origin": base}
                        first = widget_client.post(
                            "/api/chat",
                            headers=headers,
                            json={"message": "Porsche address", "analytics_consent": True},
                        )
                        assert first.status_code == 200 and "245 Eastern" in first.json()["response"]
                        assert not widget_client.cookies
                        second = widget_client.post(
                            "/api/chat", headers=headers, json={"message": "Service hours"}
                        )
                        assert "Porsche" in second.json()["response"]
                        deleted = widget_client.post("/api/privacy", headers=headers, json={})
                        assert deleted.status_code == 200 and deleted.json()["session_token"] != token
                        assert (
                            widget_client.post(
                                "/api/chat", headers=headers, json={"message": "hello"}
                            ).status_code
                            == 401
                        )
                        assert (
                            widget_client.get(
                                "/widget", params={"parent": "https://evil.invalid"}
                            ).status_code
                            == 403
                        )
                    receipts.append(
                        {
                            "scenario": "embedded session without cookies, contextual follow-up, deletion and token revocation",
                            "outcome": "Worked",
                        }
                    )

                    def turn(index):
                        start = time.perf_counter()
                        with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
                            response = client.post("/api/chat", json={"message": "inventory"})
                        assert response.status_code == 200
                        return round((time.perf_counter() - start) * 1000, 2)

                    with ThreadPoolExecutor(8) as pool:
                        timings = sorted(pool.map(turn, range(8)))
                    receipts.append(
                        {
                            "scenario": "8 concurrent local inventory requests",
                            "outcome": "Worked",
                            "successful": 8,
                            "maximum_ms": timings[-1],
                            "median_ms": timings[4],
                        }
                    )
            finally:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        # Real socket contract tests; fixtures are explicitly distinct from vendor inference.
        server = ThreadingHTTPServer(("127.0.0.1", 0), MessagesFixture)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = ClaudeClient(
                "synthetic-key", "fixture-model", api_url=f"http://127.0.0.1:{server.server_port}/v1/messages"
            )
            assert client.send_message("hello", [], {})["response"] == "fixture reply"
            assert MessagesFixture.received[-1]["messages"][-1]["content"] == "hello"
            for mode in ("truncated", "error"):
                MessagesFixture.mode = mode
                try:
                    client.send_message("hello", [], {})
                except ProviderError:
                    pass
                else:
                    raise AssertionError(mode + " incorrectly succeeded")
            receipts.append(
                {
                    "scenario": "real HTTP provider success, truncation and failure fixture",
                    "outcome": "Worked",
                    "vendor_inference": False,
                }
            )
        finally:
            server.shutdown()
            server.server_close()
    report = {"server": "Waitress shipped module", "paid_calls": 0, "receipts": receipts}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
