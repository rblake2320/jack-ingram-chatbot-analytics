"""Public REST API (also used by the chat UI's forms)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..resilience import UpstreamError
from ..security import idempotency_key_from
from ..services.appointments import BookingInput, CancelInput
from ..services.common import ServiceError
from ..services.finance import (
    LeaseInput,
    PaymentInput,
    TradeInInput,
    estimate_lease,
    estimate_payment,
    estimate_trade_in,
)
from ..services.inventory import SearchFilters
from ..services.leads import LeadInput, public_lead
from .deps import conversation_from_header, get_services, limited

router = APIRouter(prefix="/api", tags=["public"], dependencies=[limited("api", "rate_limit_api_per_minute")])


def _upstream(exc: UpstreamError) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"{exc.upstream}_unavailable")


@router.get("/dealership")
async def dealership(request: Request) -> dict:
    return get_services(request).knowledge.public_info()


@router.get("/inventory/search")
async def search_inventory(
    request: Request,
    make: str | None = Query(default=None, max_length=40),
    model: str | None = Query(default=None, max_length=40),
    body_style: str | None = Query(default=None, max_length=30),
    condition: Literal["new", "used", "cpo"] | None = None,
    fuel_type: str | None = Query(default=None, max_length=30),
    min_year: int | None = Query(default=None, ge=1980, le=2100),
    max_year: int | None = Query(default=None, ge=1980, le=2100),
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    max_mileage: int | None = Query(default=None, ge=0),
    q: str | None = Query(default=None, max_length=100),
    sort: Literal["price_asc", "price_desc", "year_desc", "mileage_asc", "relevance"] = "relevance",
    limit: int = Query(default=12, ge=1, le=20),
) -> dict:
    filters = SearchFilters(make=make, model=model, body_style=body_style, condition=condition, fuel_type=fuel_type,
                            min_year=min_year, max_year=max_year, min_price=min_price, max_price=max_price,
                            max_mileage=max_mileage, query=q, sort=sort, limit=limit)  # fmt: skip
    return get_services(request).inventory.search(filters)


@router.get("/inventory/{stock_number}")
async def vehicle(stock_number: str, request: Request) -> dict:
    inventory = get_services(request).inventory
    found = inventory.get(stock_number[:20])
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vehicle_not_found")
    return {
        "vehicle": found.model_dump(),
        "price_context": inventory.price_context(found),
        "is_sample": inventory.is_sample,
    }


class CompareIn(BaseModel):
    stock_numbers: list[str] = Field(min_length=2, max_length=4)


@router.post("/inventory/compare")
async def compare(body: CompareIn, request: Request) -> dict:
    try:
        return get_services(request).inventory.compare(body.stock_numbers)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc


@router.get("/offers")
async def offers(request: Request, make: str | None = Query(default=None, max_length=40)) -> dict:
    return get_services(request).inventory.current_offers(make)


@router.get("/vehicles/vin/{vin}")
async def decode_vin(vin: str, request: Request) -> dict:
    try:
        return await get_services(request).nhtsa.decode_vin(vin[:32])
    except UpstreamError as exc:
        raise _upstream(exc) from exc
    except ValueError as exc:
        raise ServiceError(str(exc), code="invalid_vin") from exc


@router.get("/vehicles/recalls")
async def recalls(
    request: Request,
    make: str = Query(max_length=40),
    model: str = Query(max_length=40),
    year: int = Query(ge=1950, le=2100),
) -> dict:
    try:
        return await get_services(request).nhtsa.recalls(make, model, year)
    except UpstreamError as exc:
        raise _upstream(exc) from exc
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc


@router.get("/vehicles/safety-ratings")
async def safety_ratings(
    request: Request,
    make: str = Query(max_length=40),
    model: str = Query(max_length=40),
    year: int = Query(ge=1990, le=2100),
) -> dict:
    try:
        return await get_services(request).nhtsa.safety_ratings(make, model, year)
    except UpstreamError as exc:
        raise _upstream(exc) from exc
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc


@router.post("/finance/payment")
async def payment(body: PaymentInput) -> dict:
    return estimate_payment(body)


@router.post("/finance/lease")
async def lease(body: LeaseInput) -> dict:
    try:
        return estimate_lease(body)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc


@router.post("/trade-in/estimate")
async def trade_in(body: TradeInInput) -> dict:
    try:
        return estimate_trade_in(body)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc


@router.get("/appointments/availability")
async def availability(
    request: Request,
    department: Literal["service", "test_drive"],
    date_from: date | None = None,
    days: int = Query(default=3, ge=1, le=14),
) -> dict:
    return await get_services(request).appointments.availability(department, date_from, days)


@router.post("/appointments", status_code=status.HTTP_201_CREATED)
async def book(body: BookingInput, request: Request) -> dict:
    services = get_services(request)
    conv_id = conversation_from_header(request, required=False)
    record, replayed = await services.appointments.book(
        body, source="web_form", conversation_id=conv_id, idempotency_key=idempotency_key_from(request, "appointment")
    )
    if not replayed:
        await services.analytics.record(
            "appointment.booked", conv_id, department=record["department"], source="web_form"
        )
    return services.appointments.public_view(record) | {"replayed": replayed}


@router.post("/appointments/{code}/cancel", dependencies=[limited("lookup", "rate_limit_lookup_per_hour", 3600)])
async def cancel(code: str, body: CancelInput, request: Request) -> dict:
    services = get_services(request)
    result = await services.db.run(
        services.appointments.cancel_sync, code[:12], phone_last4=body.phone_last4, email=body.email
    )
    if not result["already_cancelled"]:
        await services.analytics.record("appointment.cancelled", None)
    return result


@router.post("/leads", status_code=status.HTTP_201_CREATED)
async def create_lead(body: LeadInput, request: Request) -> dict:
    services = get_services(request)
    conv_id = conversation_from_header(request, required=False)
    record, replayed = await services.leads.create(
        body, source="web_form", conversation_id=conv_id, idempotency_key=idempotency_key_from(request, "lead")
    )
    if not replayed:
        await services.analytics.record("lead.created", conv_id, interest=record["interest"], source="web_form")
    return public_lead(record) | {"replayed": replayed}


class ServiceHistoryIn(BaseModel):
    vin: str = Field(max_length=32)
    last_name: str = Field(min_length=1, max_length=50)


@router.post("/service-history/lookup", dependencies=[limited("lookup", "rate_limit_lookup_per_hour", 3600)])
async def service_history(body: ServiceHistoryIn, request: Request) -> dict:
    services = get_services(request)
    vin_bucket = f"svc-vin:{body.vin.strip().upper()}"
    decision = await services.limiter.hit(vin_bucket, services.settings.rate_limit_lookup_per_hour, 3600)
    if not decision.allowed:
        await services.analytics.record("rate_limited", None, bucket="svc-vin")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited",
                            headers={"Retry-After": str(decision.retry_after_s)})  # fmt: skip
    return await services.db.run(services.service_history.lookup_sync, body.vin, body.last_name)
