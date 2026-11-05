"""Admin API (Bearer ADMIN_TOKEN): analytics, records, handoff console, ledger, outbox."""

from __future__ import annotations

import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services.appointments import appointment_record
from ..services.common import ServiceError
from ..services.leads import lead_record
from ..services.service_history import ServiceRecordIn
from .deps import get_services, limited, require_admin

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[limited("admin", "rate_limit_admin_per_minute"), Depends(require_admin)],
)


@router.get("/analytics/summary")
async def analytics_summary(request: Request, days: int = Query(default=30, ge=1, le=400)) -> dict:
    services = get_services(request)
    summary = await services.db.run(services.analytics.summary_sync, days)
    summary["integrations"] = services.settings.integration_status()
    summary["inventory"] = {"vehicles": len(services.inventory.vehicles), "is_sample": services.inventory.is_sample}
    return summary


@router.get("/leads")
async def leads(
    request: Request, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)
) -> dict:
    services = get_services(request)
    return {"leads": await services.db.run(services.leads.list_sync, limit=limit, offset=offset)}


_CSV_FIELDS = ["id", "created_at", "source", "first_name", "last_name", "phone", "email", "interest", "comments",
               "preferred_contact", "status"]  # fmt: skip


def _csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text  # block CSV formula injection


@router.get("/leads.csv")
async def leads_csv(request: Request) -> Response:
    services = get_services(request)
    rows = await services.db.run(services.leads.list_sync, limit=5000)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_FIELDS)
    for row in rows:
        writer.writerow([_csv_safe(row.get(f)) for f in _CSV_FIELDS])
    return Response(buffer.getvalue(), media_type="text/csv",
                    headers={"content-disposition": 'attachment; filename="leads.csv"'})  # fmt: skip


@router.get("/appointments")
async def appointments(request: Request, start: str | None = None, end: str | None = None) -> dict:
    services = get_services(request)
    return {"appointments": await services.db.run(services.appointments.list_sync, start=start, end=end)}


@router.get("/handoffs")
async def handoffs(
    request: Request, status_filter: Literal["queued", "claimed", "closed"] | None = Query(None, alias="status")
) -> dict:
    services = get_services(request)
    return {"handoffs": await services.db.run(services.handoffs.list_sync, status_filter)}


@router.get("/handoffs/{handoff_id}")
async def handoff_detail(handoff_id: str, request: Request, after: int = Query(default=0, ge=0)) -> dict:
    services = get_services(request)
    handoff = await services.db.run(services.handoffs.get_sync, handoff_id)
    transcript = await services.db.run(
        services.conversations.messages_after_sync, handoff["conversation_id"], after, 500
    )
    return {"handoff": handoff, "messages": transcript}


class ClaimIn(BaseModel):
    agent_name: str = Field(min_length=1, max_length=60)


class AgentMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


@router.post("/handoffs/{handoff_id}/claim")
async def claim(handoff_id: str, body: ClaimIn, request: Request) -> dict:
    services = get_services(request)
    return await services.db.run(services.handoffs.claim_sync, handoff_id, body.agent_name)


@router.post("/handoffs/{handoff_id}/messages")
async def agent_message(handoff_id: str, body: AgentMessageIn, request: Request) -> dict:
    services = get_services(request)
    return {"message_id": await services.db.run(services.handoffs.agent_message_sync, handoff_id, body.content)}


@router.post("/handoffs/{handoff_id}/close")
async def close(handoff_id: str, request: Request) -> dict:
    services = get_services(request)
    return await services.db.run(services.handoffs.close_sync, handoff_id)


@router.get("/ledger/verify")
async def ledger_verify(request: Request) -> dict:
    services = get_services(request)

    def run() -> dict:
        with services.db.read() as conn:
            return services.ledger.verify(conn).as_dict()

    return await services.db.run(run)


@router.get("/ledger/head")
async def ledger_head(request: Request) -> dict:
    services = get_services(request)

    def run() -> dict:
        with services.db.read() as conn:
            seq, digest = services.ledger.head(conn)
        return {"head_seq": seq, "head_hash": digest}

    return await services.db.run(run)


@router.get("/records/verify")
async def records_verify(request: Request) -> dict:
    """Re-derive each lead/appointment digest and compare it with its ledger entry."""
    services = get_services(request)

    def run() -> dict:
        problems, checked = [], 0
        with services.db.read() as conn:
            for table, builder, key in (
                ("leads", lead_record, "lead_id"),
                ("appointments", appointment_record, "appointment_id"),
            ):
                for row in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608 - fixed table names
                    checked += 1
                    entry = conn.execute("SELECT payload FROM ledger WHERE seq = ?", (row["ledger_seq"],)).fetchone()
                    payload = json.loads(entry["payload"]) if entry else {}
                    if payload.get(key) != row["id"] or payload.get("record_digest") != services.ledger.record_digest(
                        builder(row)
                    ):
                        problems.append({"table": table, "id": row["id"], "ledger_seq": row["ledger_seq"]})
        return {"ok": not problems, "checked": checked, "mismatches": problems[:50]}

    return await services.db.run(run)


@router.get("/outbox")
async def outbox(
    request: Request, status_filter: Literal["pending", "delivered", "dead"] | None = Query(None, alias="status")
) -> dict:
    services = get_services(request)
    return {
        "enabled": services.outbox.enabled,
        "stats": await services.db.run(services.outbox.stats_sync),
        "items": await services.db.run(services.outbox.list_sync, status_filter),
    }


@router.post("/outbox/{delivery_id}/requeue")
async def requeue(delivery_id: str, request: Request) -> dict:
    services = get_services(request)
    if not await services.db.run(services.outbox.requeue_sync, delivery_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_dead_or_missing")
    return {"requeued": delivery_id}


class ServiceImportIn(BaseModel):
    records: list[ServiceRecordIn] = Field(min_length=1, max_length=2000)
    source: str = Field(default="dms", max_length=40)


@router.post("/service-records")
async def import_service_records(body: ServiceImportIn, request: Request) -> dict:
    services = get_services(request)
    return await services.db.run(services.service_history.import_sync, body.records, source=body.source)


@router.post("/inventory/reload")
async def reload_inventory(request: Request) -> dict:
    services = get_services(request)
    try:
        return await services.db.run(services.inventory.load)
    except (OSError, ValueError) as exc:
        raise ServiceError(f"inventory feed could not be loaded: {type(exc).__name__}", status=500) from exc
