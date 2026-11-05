"""Crash-safe writes, exclusive creation races, configuration guards, secret handling."""

from __future__ import annotations

import os
import threading

import pytest
from pydantic import ValidationError

from chatbot import atomic
from chatbot.atomic import atomic_create_exclusive, atomic_write_bytes
from chatbot.config import Settings
from chatbot.security import resolve_secrets

GOOD = "g" * 40


def test_atomic_write_replaces_content(tmp_path):
    target = tmp_path / "f.json"
    atomic_write_bytes(target, b"one")
    atomic_write_bytes(target, b"two")
    assert target.read_bytes() == b"two"
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


def test_crash_during_replace_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "f.json"
    atomic_write_bytes(target, b"original")

    def boom(*args, **kwargs):
        raise OSError("simulated power loss at rename")

    monkeypatch.setattr(atomic.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new content that must not appear")
    assert target.read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.json"]


def test_crash_during_temp_write_leaves_nothing(tmp_path, monkeypatch):
    target = tmp_path / "f.json"
    monkeypatch.setattr(atomic.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"x")
    assert list(tmp_path.iterdir()) == []


def test_exclusive_create_has_exactly_one_winner(tmp_path):
    target = tmp_path / "secret.json"
    results: list[bool] = []
    barrier = threading.Barrier(12)

    def worker(n: int) -> None:
        barrier.wait()
        results.append(atomic_create_exclusive(target, f"payload-{n}".encode() * 100))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    content = target.read_bytes()
    assert content in {f"payload-{n}".encode() * 100 for n in range(12)}  # one complete payload, never torn
    assert sorted(p.name for p in tmp_path.iterdir()) == ["secret.json"]


def test_exclusive_create_does_not_overwrite(tmp_path):
    target = tmp_path / "x"
    assert atomic_create_exclusive(target, b"first")
    assert not atomic_create_exclusive(target, b"second")
    assert target.read_bytes() == b"first"


# --- configuration -------------------------------------------------------------------------
def test_no_api_key_defaults():
    s = Settings(_env_file=None)
    assert s.anthropic_api_key is None and s.perplexity_api_key is None and s.firecrawl_api_key is None
    assert s.anthropic_model == "claude-opus-5-5"


def test_production_refuses_missing_secrets():
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, environment="production")
    text = str(exc.value)
    for name in ("SESSION_SECRET", "LEDGER_HMAC_KEY", "ADMIN_TOKEN"):
        assert name in text


def test_production_refuses_short_secrets():
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(
            _env_file=None, environment="production", session_secret="short", ledger_hmac_key=GOOD, admin_token=GOOD
        )


def test_production_webhook_needs_https_and_signing_secret():
    with pytest.raises(ValidationError, match="https"):
        Settings(_env_file=None, environment="production", session_secret=GOOD, ledger_hmac_key=GOOD,
                 admin_token=GOOD, crm_webhook_url="http://crm.example.com/hook", webhook_signing_secret=GOOD)  # fmt: skip
    with pytest.raises(ValidationError, match="WEBHOOK_SIGNING_SECRET"):
        Settings(_env_file=None, environment="production", session_secret=GOOD, ledger_hmac_key=GOOD,
                 admin_token=GOOD, crm_webhook_url="https://crm.example.com/hook")  # fmt: skip


def test_production_valid_config_accepted():
    s = Settings(_env_file=None, environment="production", session_secret=GOOD, ledger_hmac_key=GOOD, admin_token=GOOD)
    assert s.is_production


def test_secrets_never_in_repr():
    s = Settings(_env_file=None, anthropic_api_key="sk-ant-" + "q" * 30, admin_token=GOOD)
    assert "qqqq" not in repr(s) and GOOD not in repr(s) and "qqqq" not in str(s.model_dump())


def test_list_settings_accept_csv_and_json(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("CLOSED_DATES", '["2026-12-24"]')
    s = Settings(_env_file=None)
    assert s.cors_origins == ["https://a.example", "https://b.example"]
    assert str(s.closed_dates[0]) == "2026-12-24"


def test_specials_urls_must_be_https():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, specials_urls=["http://insecure.example/specials"])


def test_dev_secrets_generated_once_and_shared(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path)
    a, b = resolve_secrets(s), resolve_secrets(s)
    assert a.session_key == b.session_key and a.ledger_key == b.ledger_key and len(a.ledger_key) >= 48
    if os.name == "posix":
        assert (tmp_path / ".dev-secrets.json").stat().st_mode & 0o077 == 0


def test_explicit_secrets_win_over_dev_file(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path, ledger_hmac_key=GOOD)
    assert resolve_secrets(s).ledger_key == GOOD.encode()
