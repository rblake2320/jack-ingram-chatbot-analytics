"""Secrets bootstrap, conversation tokens, admin auth and client identification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request, status

from .atomic import atomic_create_exclusive
from .config import Settings

log = logging.getLogger(__name__)

_DEV_SECRETS_FILE = ".dev-secrets.json"


@dataclass(frozen=True)
class Secrets:
    session_key: bytes
    ledger_key: bytes
    webhook_key: bytes | None
    admin_token: str | None


def _load_or_create_dev_secrets(data_dir: Path) -> dict[str, str]:
    """Non-production only: one random secret set per data dir, agreed on by all workers."""
    path = data_dir / _DEV_SECRETS_FILE
    if not path.exists():
        generated = {
            "session_secret": secrets.token_urlsafe(48),
            "ledger_hmac_key": secrets.token_urlsafe(48),
            "webhook_signing_secret": secrets.token_urlsafe(48),
        }
        if atomic_create_exclusive(path, json.dumps(generated).encode("utf-8")):
            log.warning("generated development secrets at %s (never use in production)", path)
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_secrets(settings: Settings) -> Secrets:
    def value(secret: object) -> str | None:
        return secret.get_secret_value() if secret is not None else None  # type: ignore[attr-defined]

    session = value(settings.session_secret)
    ledger = value(settings.ledger_hmac_key)
    webhook = value(settings.webhook_signing_secret)
    if not settings.is_production and (session is None or ledger is None or webhook is None):
        dev = _load_or_create_dev_secrets(settings.data_dir)
        session = session or dev["session_secret"]
        ledger = ledger or dev["ledger_hmac_key"]
        webhook = webhook or dev["webhook_signing_secret"]
    if session is None or ledger is None:  # production guard in Settings makes this unreachable
        raise RuntimeError("SESSION_SECRET and LEDGER_HMAC_KEY are required")
    return Secrets(
        session_key=session.encode("utf-8"),
        ledger_key=ledger.encode("utf-8"),
        webhook_key=webhook.encode("utf-8") if webhook else None,
        admin_token=value(settings.admin_token),
    )


# --- conversation tokens -------------------------------------------------------------------
_CONV_ID_RE = re.compile(r"^c_[A-Za-z0-9_\-]{24,64}$")


class ConversationTokens:
    """Opaque bearer tokens bound to a conversation id: ``v1.<conv_id>.<hmac>``.

    Sent in the ``X-Conversation-Token`` header (not a cookie), so they work inside
    third-party iframes and are immune to CSRF.
    """

    def __init__(self, key: bytes) -> None:
        self._key = hashlib.sha256(b"conversation-token|" + key).digest()

    def _sig(self, conv_id: str) -> str:
        mac = hmac.new(self._key, conv_id.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")

    def issue(self) -> tuple[str, str]:
        conv_id = "c_" + secrets.token_urlsafe(24)
        return conv_id, self.token_for(conv_id)

    def token_for(self, conv_id: str) -> str:
        return f"v1.{conv_id}.{self._sig(conv_id)}"

    def verify(self, token: str | None) -> str | None:
        if not token or len(token) > 200:
            return None
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "v1":
            return None
        conv_id, sig = parts[1], parts[2]
        if not _CONV_ID_RE.match(conv_id):
            return None
        return conv_id if hmac.compare_digest(self._sig(conv_id), sig) else None


# --- client identity -----------------------------------------------------------------------
def client_ip(request: Request, settings: Settings) -> str:
    """Client IP. Honour a proxy header ONLY when explicitly configured (e.g. ``do-connecting-ip``)."""
    if settings.client_ip_header:
        raw = request.headers.get(settings.client_ip_header)
        if raw:
            return raw.split(",")[0].strip()[:64] or "unknown"
    return request.client.host if request.client else "unknown"


# --- admin auth ----------------------------------------------------------------------------
def check_admin(request: Request, admin_token: str | None) -> None:
    if not admin_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin_disabled")
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})
    if not hmac.compare_digest(supplied.strip().encode("utf-8"), admin_token.encode("utf-8")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})


# --- request validation helpers ------------------------------------------------------------
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")


def idempotency_key_from(request: Request, scope: str) -> str | None:
    raw = request.headers.get("idempotency-key")
    if raw is None:
        return None
    if not _IDEMPOTENCY_RE.match(raw):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid_idempotency_key")
    return f"{scope}:http:{raw}"
