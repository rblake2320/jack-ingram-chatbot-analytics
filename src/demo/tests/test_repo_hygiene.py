"""Repository hygiene: no credentials anywhere in tracked files, no hardcoded key defaults in code."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parents[1] / "chatbot"

# Shapes of the three credential types that were previously committed.
SECRET_PATTERNS = [
    re.compile(r"sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"pplx-[A-Za-z0-9]{24,}"),
    re.compile(r"\bfc-[0-9a-f]{32}\b"),
]
BINARY_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".sqlite3", ".pyc"}


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True, timeout=30
        ).stdout.decode()
        files = [REPO_ROOT / name for name in out.split("\0") if name]
    except (OSError, subprocess.SubprocessError):
        files = [p for p in REPO_ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [f for f in files if f.suffix.lower() not in BINARY_SUFFIXES and f.exists()]


def test_no_credentials_in_tracked_files():
    hits = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(REPO_ROOT)}: {pattern.pattern}")
    assert not hits, "credential-shaped strings found:\n" + "\n".join(hits)


def test_no_hardcoded_key_defaults_in_code():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"(api_key|secret|token)\s*:\s*str\s*=\s*\"[^\"]{8,}\"", text, re.IGNORECASE):
            offenders.append(str(path))
        if re.search(r"getenv\([^)]*,\s*\"[^\"]{16,}\"\)", text):
            offenders.append(str(path))
    assert not offenders


def test_env_example_has_no_values_for_secrets():
    example = REPO_ROOT / "src" / "demo" / ".env.example"
    assert example.exists()
    for line in example.read_text(encoding="utf-8").splitlines():
        if re.match(r"^(ANTHROPIC_API_KEY|PERPLEXITY_API_KEY|FIRECRAWL_API_KEY|SESSION_SECRET|LEDGER_HMAC_KEY|"
                    r"ADMIN_TOKEN|WEBHOOK_SIGNING_SECRET)=", line):  # fmt: skip
            assert line.split("=", 1)[1].strip() == "", line
