"""Input hygiene shared by every entry point: control-char stripping, phone/email/name rules."""

from __future__ import annotations

import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(\.[A-Za-z0-9\-]{1,63})+$")
_NAME_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '.\-])*$", re.UNICODE)


def clean_text(value: str, *, max_len: int | None = None, multiline: bool = True) -> str:
    """NFC-normalise, drop control/bidi-override characters (valid XML 1.0 + no spoofing)."""
    value = unicodedata.normalize("NFC", value or "")
    value = _CONTROL.sub("", value)
    if not multiline:
        value = re.sub(r"[\r\n\t]+", " ", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]{2,}", " ", value).strip()
    if max_len is not None:
        value = value[:max_len]
    return value


def normalize_us_phone(raw: str) -> str | None:
    """Return E.164 (+1XXXXXXXXXX) for valid NANP numbers, else None."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    if digits[0] in "01" or digits[3] in "01":
        return None
    return "+1" + digits


def format_phone(e164: str | None) -> str | None:
    if not e164 or not e164.startswith("+1") or len(e164) != 12:
        return e164
    d = e164[2:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}"


def normalize_email(raw: str) -> str | None:
    value = (raw or "").strip()
    if len(value) > 254 or not _EMAIL_RE.match(value) or ".." in value:
        return None
    local, _, domain = value.rpartition("@")
    return f"{local}@{domain.lower()}"


def valid_name(value: str, *, max_len: int = 50) -> bool:
    return bool(value) and len(value) <= max_len and bool(_NAME_RE.match(value))


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def mask_phone(e164: str | None) -> str | None:
    return f"***-***-{e164[-4:]}" if e164 and len(e164) >= 4 else e164


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    return (local[0] + "***" if local else "***") + "@" + domain
