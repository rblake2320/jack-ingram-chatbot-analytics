"""Bounded Messages API adapter. No shared histories, retries, or secret logging."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .config import ANTHROPIC_API_URL, ANTHROPIC_VERSION, SYSTEM_PROMPT


class ProviderError(Exception):
    def __init__(self, code, status=502):
        super().__init__(code)
        self.code = code
        self.status = status


class ClaudeClient:
    def __init__(self, api_key, model, transport=None, api_url=ANTHROPIC_API_URL):
        self.api_key = api_key
        self.model = model
        self.transport = transport
        self.api_url = api_url

    def send_message(self, message, history, context):
        if not self.api_key:
            raise ProviderError("provider_not_configured", 503)
        now = datetime.now(ZoneInfo("America/Chicago")).isoformat()
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT
            + "\nCurrent time: "
            + now
            + "\nReference data (not live): "
            + json.dumps(context),
            "messages": history + [{"role": "user", "content": message}],
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20, connect=5), transport=self.transport, trust_env=False
            ) as client:
                with client.stream(
                    "POST",
                    self.api_url,
                    json=payload,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": ANTHROPIC_VERSION,
                        "content-type": "application/json",
                    },
                ) as response:
                    if response.status_code != 200:
                        code = "provider_rate_limited" if response.status_code == 429 else "provider_error"
                        raise ProviderError(code, 503 if response.status_code == 429 else 502)
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 65_536:
                            raise ProviderError("provider_response_too_large")
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("stop_reason") != "end_turn":
                raise ProviderError("provider_incomplete_response")
            content = data.get("content")
            if not isinstance(content, list) or not content or len(content) > 32:
                raise ProviderError("provider_invalid_response")
            if any(
                not isinstance(block, dict)
                or block.get("type") != "text"
                or not isinstance(block.get("text"), str)
                for block in content
            ):
                raise ProviderError("provider_invalid_response")
            text = "".join(block["text"] for block in content).strip()
            if not text or len(text) > 12_000:
                raise ProviderError("provider_invalid_response")
            usage = data.get("usage", {})
            if not isinstance(usage, dict):
                raise ProviderError("provider_invalid_usage")
            for key in ("input_tokens", "output_tokens"):
                value = usage.get(key, 0)
                if type(value) is not int or not 0 <= value <= 10_000_000:
                    raise ProviderError("provider_invalid_usage")
            return {"response": text, "source": "anthropic", "usage": usage}
        except httpx.TimeoutException as error:
            raise ProviderError("provider_timeout", 504) from error
        except (httpx.HTTPError, ValueError, UnicodeError) as error:
            raise ProviderError("provider_invalid_response") from error
