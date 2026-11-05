"""Claude tool loop: request shape, append-only history, tool fault barriers, provenance, failure modes."""

from __future__ import annotations

import json
from datetime import datetime

import anthropic
import pytest

from chatbot.agent.llm import FALLBACK_BETA, REFUSAL_TEXT, THINKING_BINDING_BETA
from chatbot.agent.orchestrator import GENERIC_RETRY

from .conftest import (
    FakeAnthropic,
    api_error,
    chat,
    first_slot,
    message,
    services_of,
    text_block,
    thinking_block,
    tool_use,
)

EXPECTED_TOOLS = [
    "get_dealership_info", "search_inventory", "compare_vehicles", "get_current_offers", "decode_vin", "get_recalls",
    "get_safety_ratings", "estimate_payment", "estimate_lease", "estimate_trade_in", "check_appointment_availability",
    "book_appointment", "capture_lead", "request_human_agent", "lookup_service_history",
]  # fmt: skip


def llm_client(app_factory, script, **overrides):
    fake = FakeAnthropic(script)
    return app_factory(anthropic_client=fake, **overrides), fake


def history(client, token):
    services = services_of(client)
    return services.conversations.history_sync(services.tokens.verify(token))


def tool_results(call):
    return [b for b in call["messages"][-1]["content"] if b.get("type") == "tool_result"]


def events(client, name):
    with services_of(client).db.read() as conn:
        rows = conn.execute("SELECT props FROM analytics_events WHERE event = ?", (name,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def test_request_shape_matches_current_api(app_factory):
    client, fake = llm_client(app_factory, [message([thinking_block(), text_block("Hello! How can I help?")])])
    result = chat(client, "hi")
    assert result["source"] == "llm" and result["reply"] == "Hello! How can I help?"
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    assert call["output_config"] == {"effort": "medium"}
    assert set(call["betas"]) == {THINKING_BINDING_BETA, FALLBACK_BETA} and call["fallbacks"] == "default"
    assert call["cache_control"] == {"type": "ephemeral"} and "tool_choice" not in call
    assert [t["name"] for t in call["tools"]] == EXPECTED_TOOLS
    assert "temperature" not in call and "budget_tokens" not in json.dumps(call)
    user = call["messages"][-1]["content"]
    assert user[0]["text"].startswith("<context>") and user[1]["text"] == "hi"
    system = call["system"][0]["text"]
    assert datetime.now().strftime("%B %d, %Y") not in system  # frozen prompt: no timestamps


def test_tool_definitions_are_clean():
    from chatbot.agent.tools import build_tools

    class Stub:
        firecrawl = type("F", (), {"configured": False})()
        perplexity = type("P", (), {"configured": True})()

    tools = build_tools(Stub())
    names = [t.name for t in tools]
    assert names == [*EXPECTED_TOOLS, "search_web"] and len(set(names)) == len(names)
    for spec in tools:
        definition = spec.definition()
        assert definition["input_schema"]["type"] == "object" and definition["description"]
        assert '"title"' not in json.dumps(definition["input_schema"])


def test_history_is_append_only_and_thinking_preserved(app_factory):
    script = [
        message([thinking_block("sig-A"), text_block("A1")]),
        message([thinking_block("sig-B"), text_block("A2")]),
    ]
    client, fake = llm_client(app_factory, script)
    first = chat(client, "first question")
    chat(client, "second question", token=first["conversation_token"])
    one, two = fake.calls
    assert two["messages"][0] == one["messages"][0]  # identical prefix, byte for byte
    assert two["messages"][1] == {"role": "assistant", "content": [thinking_block("sig-A"), text_block("A1")]}
    assert two["system"] == one["system"] and two["tools"] == one["tools"]
    stored = history(client, first["conversation_token"])
    assert stored[-1]["content"][0] == thinking_block("sig-B") and len(stored) == 4


def test_tool_loop_executes_and_feeds_results(app_factory):
    script = [
        message([thinking_block(), tool_use("search_inventory", {"make": "Audi", "limit": 2})], "tool_use"),
        message([text_block("Here are two Audis.")]),
    ]
    client, fake = llm_client(app_factory, script)
    result = chat(client, "Any Audis?")
    assert result["reply"] == "Here are two Audis."
    results = tool_results(fake.calls[1])
    assert results[0]["tool_use_id"] == "toolu_1" and "is_error" not in results[0]
    payload = json.loads(results[0]["content"])
    assert payload["is_sample"] is True and all(v["make"] == "Audi" for v in payload["vehicles"])
    assert fake.calls[1]["messages"][-2]["content"][1]["type"] == "tool_use"
    assert events(client, "tool.called")[0]["name"] == "search_inventory"


def test_parallel_tool_calls_return_in_one_message(app_factory):
    script = [
        message(
            [
                tool_use("get_dealership_info", {"topic": "hours"}, "toolu_a"),
                tool_use("get_current_offers", {}, "toolu_b"),
            ],
            "tool_use",
        ),
        message([text_block("ok")]),
    ]
    client, fake = llm_client(app_factory, script)
    chat(client, "hours and offers?")
    assert [r["tool_use_id"] for r in tool_results(fake.calls[1])] == ["toolu_a", "toolu_b"]


def test_invalid_and_unknown_tools_become_error_results(app_factory):
    script = [
        message(
            [
                tool_use("estimate_payment", {"price": -5, "apr_percent": 5, "term_months": 60}, "t1"),
                tool_use("hack_the_planet", {"x": 1}, "t2"),
            ],
            "tool_use",
        ),
        message([text_block("Sorry, could you share the price?")]),
    ]
    client, fake = llm_client(app_factory, script)
    assert chat(client, "payment?")["reply"].startswith("Sorry")
    bad, unknown = tool_results(fake.calls[1])
    assert bad["is_error"] and "invalid_arguments" in bad["content"]
    assert unknown["is_error"] and "Unknown tool" in unknown["content"]


def test_crashing_tool_is_contained(app_factory, monkeypatch):
    script = [
        message([tool_use("search_inventory", {})], "tool_use"),
        message([text_block("Inventory is unavailable.")]),
    ]
    client, fake = llm_client(app_factory, script)
    monkeypatch.setattr(services_of(client).inventory, "search", lambda f: 1 / 0)
    assert chat(client, "stock?")["reply"] == "Inventory is unavailable."
    result = tool_results(fake.calls[1])[0]
    assert result["is_error"] and "Internal error" in result["content"] and "ZeroDivision" not in result["content"]


LEAD_ARGS = {"first_name": "Ann", "phone": "334-555-0142", "interest": "buy", "consent_to_contact": True}


def test_provenance_barrier_blocks_invented_contact_details(app_factory):
    script = [message([tool_use("capture_lead", LEAD_ARGS)], "tool_use"), message([text_block("What's your number?")])]
    client, fake = llm_client(app_factory, script)
    chat(client, "Have someone call me about a Q5")  # the customer never typed a phone number
    result = tool_results(fake.calls[1])[0]
    assert result["is_error"] and "Not submitted" in result["content"]
    with services_of(client).db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


def test_lead_created_when_customer_supplied_details(app_factory):
    script = [
        message([tool_use("capture_lead", LEAD_ARGS)], "tool_use"),
        message([text_block("Done! The team will call.")]),
    ]
    client, _ = llm_client(app_factory, script)
    chat(client, "I'm Ann, call me at (334) 555-0142. Yes, you can contact me.")
    with services_of(client).db.read() as conn:
        row = conn.execute("SELECT phone, source FROM leads").fetchone()
    assert row["phone"] == "+13345550142" and row["source"] == "chat"
    assert events(client, "lead.created")[0]["source"] == "chat"


def test_tool_booking_returns_calendar_and_is_idempotent(app_factory, router):
    client, fake = llm_client(app_factory, [])
    slot = first_slot(client)
    args = {"department": "service", "slot_start": slot, "first_name": "Ann", "last_name": "Lee",
            "phone": "334-555-0142", "consent_to_contact": True}  # fmt: skip
    fake.messages.script = [
        message([tool_use("book_appointment", args, "b1")], "tool_use"),
        message([tool_use("book_appointment", args, "b2")], "tool_use"),  # model retries the same call
        message([text_block("You're booked!")]),
    ]
    result = chat(client, "Book it for Ann Lee, 334-555-0142, yes contact me")
    assert result["reply"] == "You're booked!" and result["appointments"][0]["ics"].startswith("BEGIN:VCALENDAR")
    second = json.loads(tool_results(fake.calls[2])[0]["content"])
    assert second["already_booked"] is True
    with services_of(client).db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1


def test_refusal_is_not_persisted(app_factory):
    client, fake = llm_client(app_factory, [message([], "refusal"), message([text_block("Sure, hours are...")])])
    first = chat(client, "something the classifier declines")
    assert first["reply"] == REFUSAL_TEXT
    assert history(client, first["conversation_token"]) == []
    chat(client, "what are your hours?", token=first["conversation_token"])
    assert len(fake.calls[1]["messages"]) == 1  # the refused turn is not replayed


def test_truncated_tool_call_is_never_executed_or_persisted(app_factory):
    client, _ = llm_client(app_factory, [message([tool_use("capture_lead", {"first_name": "A"})], "max_tokens")])
    result = chat(client, "call me")
    assert result["reply"] == GENERIC_RETRY
    stored = json.dumps(history(client, result["conversation_token"]))
    assert "tool_use" not in stored
    assert events(client, "tool.called") == []


def test_final_iteration_disables_tools(app_factory):
    script = [message([tool_use("get_current_offers", {})], "tool_use"), message([text_block("Here are the offers.")])]
    client, fake = llm_client(app_factory, script, agent_max_iterations=2)
    assert chat(client, "offers?")["reply"] == "Here are the offers."
    assert "tool_choice" not in fake.calls[0] and fake.calls[1]["tool_choice"] == {"type": "none"}


def test_misbehaving_tool_call_on_final_iteration_is_dropped(app_factory):
    client, fake = llm_client(
        app_factory, [message([tool_use("get_current_offers", {})], "tool_use")], agent_max_iterations=1
    )
    result = chat(client, "offers?")
    assert result["reply"] == GENERIC_RETRY and fake.calls[0]["tool_choice"] == {"type": "none"}
    assert "tool_use" not in json.dumps(history(client, result["conversation_token"]))


def test_deadline_falls_back(app_factory):
    client, _ = llm_client(app_factory, [5.0], agent_deadline_s=1.5)
    result = chat(client, "What are your hours?")
    assert result["source"] == "fallback" and "Mon-Fri" in result["reply"]
    assert events(client, "error")[0]["type"] == "timeout"


@pytest.mark.parametrize(
    ("error", "kind"),
    [(api_error(anthropic.RateLimitError, 429), "rate_limited"), (api_error(anthropic.InternalServerError, 500), "upstream_error"),
     (anthropic.APIConnectionError(request=__import__("httpx2").Request("POST", "https://x")), "connection")],
)  # fmt: skip
def test_transient_errors_fall_back(app_factory, error, kind):
    client, _ = llm_client(app_factory, [error])
    result = chat(client, "hours?")
    assert result["source"] == "fallback" and result["reply"]
    assert events(client, "error")[0]["type"] == kind


def test_auth_failure_opens_breaker(app_factory):
    client, fake = llm_client(app_factory, [api_error(anthropic.AuthenticationError, 401, "invalid x-api-key")])
    assert chat(client, "hi")["source"] == "fallback"
    assert chat(client, "hi again")["source"] == "fallback"
    assert len(fake.calls) == 1  # breaker open: no hammering a bad key
    assert client.get("/ready").json()["checks"]["llm"] == "open"


def test_rejected_history_is_stripped_and_retried_once(app_factory):
    script = [
        message([thinking_block("sig-old"), text_block("A1")]),
        api_error(anthropic.BadRequestError, 400, "thinking block signature invalid"),
        message([text_block("A2")]),
    ]
    client, fake = llm_client(app_factory, script)
    first = chat(client, "q1")
    second = chat(client, "q2", token=first["conversation_token"])
    assert second["reply"] == "A2"
    assert "thinking" not in json.dumps(fake.calls[2]["messages"])
    assert "thinking" not in json.dumps(history(client, first["conversation_token"]))


def test_persistent_bad_request_falls_back(app_factory):
    client, fake = llm_client(app_factory, [api_error(anthropic.BadRequestError, 400)])
    assert chat(client, "hours?")["source"] == "fallback" and len(fake.calls) == 1


def test_server_side_fallback_blocks_are_sanitised(app_factory):
    fallback_block = {"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-5"},
                      "trigger": {"type": "refusal", "category": "cyber"}}  # fmt: skip
    usage = {"input_tokens": 50, "output_tokens": 10, "iterations": [
        {"type": "fallback_message", "model": "claude-opus-5", "input_tokens": 50, "output_tokens": 10,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}]}  # fmt: skip
    script = [message([thinking_block("pre"), fallback_block, text_block("Answer from fallback")], usage=usage)]
    client, _ = llm_client(app_factory, script)
    result = chat(client, "q")
    assert result["reply"] == "Answer from fallback"
    assistant = history(client, result["conversation_token"])[-1]
    assert assistant["content"] == [text_block("Answer from fallback")]
    assert events(client, "response.sent")[0]["fallback_used"] is True


def test_history_trim_keeps_turn_boundary(app_factory):
    script = [message([thinking_block(f"s{i}"), text_block(f"A{i}")]) for i in range(6)]
    client, _ = llm_client(app_factory, script, history_max_messages=6)
    token = None
    for i in range(6):
        token = chat(client, f"question {i}", token=token)["conversation_token"]
    stored = history(client, token)
    assert len(stored) <= 6 and stored[0]["role"] == "user"
    assert stored[0]["content"][0]["text"].startswith("<context>")
    assert all(b.get("type") != "tool_result" for b in stored[0]["content"])


def test_actions_survive_llm_crash_mid_turn(app_factory):
    client, fake = llm_client(app_factory, [])
    slot = first_slot(client)
    args = {"department": "service", "slot_start": slot, "first_name": "Ann", "last_name": "Lee",
            "phone": "334-555-0142", "consent_to_contact": True}  # fmt: skip
    fake.messages.script = [message([tool_use("book_appointment", args)], "tool_use"),
                            api_error(anthropic.InternalServerError, 500)]  # fmt: skip
    result = chat(client, "Book Ann Lee 334-555-0142, yes contact me")
    assert result["source"] == "llm_partial" and "is booked for" in result["reply"]
    with services_of(client).db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1


def test_usage_recorded(app_factory):
    usage = {"input_tokens": 1234, "output_tokens": 56, "cache_read_input_tokens": 1000}
    client, _ = llm_client(app_factory, [message([text_block("hi")], usage=usage)])
    chat(client, "hello")
    sent = events(client, "response.sent")[0]
    assert sent["input_tokens"] == 1234 and sent["output_tokens"] == 56 and sent["cache_read_tokens"] == 1000
