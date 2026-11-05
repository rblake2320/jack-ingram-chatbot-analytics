"""Operator CLI.

python -m chatbot.cli verify-ledger
python -m chatbot.cli export-ledger var/ledger-export.jsonl
python -m chatbot.cli verify-bundle var/ledger-export.jsonl
python -m chatbot.cli gen-secret
python -m chatbot.cli smoke-nhtsa 1HGCM82633A004352
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path

from .atomic import atomic_write_bytes
from .config import get_settings
from .db import Database
from .ledger import Ledger
from .security import resolve_secrets


def _ledger() -> tuple[Database, Ledger]:
    settings = get_settings()
    db = Database(settings.db_path)
    db.initialize()
    return db, Ledger(resolve_secrets(settings).ledger_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chatbot.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify-ledger", help="recompute the hash chain and HMAC seals")
    export = sub.add_parser("export-ledger", help="write a sealed JSONL bundle (atomic)")
    export.add_argument("path", type=Path)
    bundle = sub.add_parser("verify-bundle", help="check a sealed export")
    bundle.add_argument("path", type=Path)
    sub.add_parser("gen-secret", help="print a random 48-byte url-safe secret")
    smoke = sub.add_parser("smoke-nhtsa", help="live-call NHTSA vPIC + recalls for a VIN")
    smoke.add_argument("vin")
    args = parser.parse_args(argv)

    if args.command == "gen-secret":
        print(secrets.token_urlsafe(48))
        return 0
    if args.command == "smoke-nhtsa":
        return asyncio.run(_smoke_nhtsa(args.vin))
    db, ledger = _ledger()
    if args.command == "verify-ledger":
        with db.read() as conn:
            report = ledger.verify(conn).as_dict()
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 2
    if args.command == "export-ledger":
        with db.read() as conn:
            data = ledger.export_bundle(conn)
        atomic_write_bytes(args.path, data)
        print(f"wrote {args.path} ({len(data)} bytes)")
        return 0
    if args.command == "verify-bundle":
        ok = ledger.verify_bundle(args.path.read_bytes())
        print("bundle seal OK" if ok else "bundle seal INVALID")
        return 0 if ok else 2
    return 1


async def _smoke_nhtsa(vin: str) -> int:
    import httpx

    from .cache import Cache
    from .integrations.nhtsa import NhtsaClient

    settings = get_settings()
    db = Database(settings.db_path)
    db.initialize()
    async with httpx.AsyncClient(timeout=15) as http:
        client = NhtsaClient(http, Cache(db), vpic_base=settings.nhtsa_vpic_base, api_base=settings.nhtsa_api_base)
        decoded = await client.decode_vin(vin)
        print(json.dumps(decoded, indent=2))
        if decoded.get("decoded"):
            recalls = await client.recalls(decoded["make"], decoded["model"], int(decoded["year"]))
            print(json.dumps({"recall_count": recalls["count"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
