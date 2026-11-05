"""Service container: builds every component from Settings (and test injections)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx

from .agent.fallback import FallbackResponder
from .agent.llm import ClaudeAgent
from .agent.orchestrator import ChatService
from .agent.prompts import build_system_prompt
from .agent.tools import build_tools
from .cache import Cache
from .config import Settings
from .db import Database
from .integrations.firecrawl import FirecrawlClient
from .integrations.nhtsa import NhtsaClient
from .integrations.perplexity import PerplexityClient
from .knowledge import Knowledge
from .ledger import Ledger
from .ratelimit import RateLimiter
from .security import ConversationTokens, Secrets, resolve_secrets
from .services.analytics import Analytics
from .services.appointments import AppointmentService
from .services.conversations import ConversationStore
from .services.feedback import FeedbackService
from .services.handoff import HandoffService
from .services.inventory import InventoryRepository
from .services.leads import LeadService
from .services.outbox import Outbox
from .services.service_history import ServiceHistoryService

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    secrets: Secrets
    db: Database
    ledger: Ledger
    knowledge: Knowledge
    inventory: InventoryRepository
    cache: Cache
    limiter: RateLimiter
    tokens: ConversationTokens
    http: httpx.AsyncClient
    outbox: Outbox
    leads: LeadService
    appointments: AppointmentService
    handoffs: HandoffService
    feedback: FeedbackService
    service_history: ServiceHistoryService
    analytics: Analytics
    conversations: ConversationStore
    nhtsa: NhtsaClient
    firecrawl: FirecrawlClient
    perplexity: PerplexityClient
    anthropic_client: Any = None
    owns_anthropic_client: bool = False
    agent: ClaudeAgent = field(init=False)
    fallback: FallbackResponder = field(init=False)
    chat: ChatService = field(init=False)
    tasks: list[asyncio.Task] = field(default_factory=list)


def build_services(
    settings: Settings, *, http_transport: httpx.AsyncBaseTransport | None = None, anthropic_client: Any = None
) -> Services:
    secrets = resolve_secrets(settings)
    db = Database(settings.db_path)
    db.initialize()
    ledger = Ledger(secrets.ledger_key)
    knowledge = Knowledge(
        settings.dealership_path,
        timezone=settings.timezone,
        closed_dates=settings.closed_dates,
        observe_default_holidays=settings.observe_default_holidays,
    )
    cache = Cache(db)
    http = httpx.AsyncClient(
        transport=http_transport,
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers={"user-agent": "JackIngramAssistant/2.0"},
        follow_redirects=False,
    )
    outbox = Outbox(
        db,
        http,
        webhook_url=settings.crm_webhook_url,
        fmt=settings.crm_webhook_format,
        signing_key=secrets.webhook_key,
        max_attempts=settings.outbox_max_attempts,
    )
    owns_client = False
    if anthropic_client is None and settings.anthropic_api_key is not None:
        anthropic_client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(), timeout=settings.anthropic_timeout_s, max_retries=1
        )
        owns_client = True

    def secret(value: Any) -> str | None:
        return value.get_secret_value() if value is not None else None

    services = Services(
        settings=settings,
        secrets=secrets,
        db=db,
        ledger=ledger,
        knowledge=knowledge,
        inventory=InventoryRepository(settings.inventory_path),
        cache=cache,
        limiter=RateLimiter(db),
        tokens=ConversationTokens(secrets.session_key),
        http=http,
        outbox=outbox,
        leads=LeadService(db, ledger, outbox, vendor_name=knowledge.name),
        appointments=AppointmentService(
            db,
            ledger,
            outbox,
            knowledge,
            horizon_days=settings.appointment_horizon_days,
            min_lead_minutes=settings.appointment_min_lead_minutes,
            max_active_per_phone=settings.appointment_max_active_per_phone,
        ),
        handoffs=HandoffService(db, ledger, outbox, knowledge),
        feedback=FeedbackService(db, ledger),
        service_history=ServiceHistoryService(db, ledger),
        analytics=Analytics(db, timezone=settings.timezone),
        conversations=ConversationStore(db, history_max_messages=settings.history_max_messages),
        nhtsa=NhtsaClient(
            http,
            cache,
            vpic_base=settings.nhtsa_vpic_base,
            api_base=settings.nhtsa_api_base,
            enabled=settings.nhtsa_enabled,
        ),
        firecrawl=FirecrawlClient(
            http,
            cache,
            api_key=secret(settings.firecrawl_api_key),
            api_url=settings.firecrawl_api_url,
            urls=settings.specials_urls,
        ),
        perplexity=PerplexityClient(
            http,
            cache,
            api_key=secret(settings.perplexity_api_key),
            api_url=settings.perplexity_api_url,
            model=settings.perplexity_model,
        ),
        anthropic_client=anthropic_client,
        owns_anthropic_client=owns_client,
    )
    services.agent = ClaudeAgent(
        anthropic_client,
        model=settings.anthropic_model,
        effort=settings.anthropic_effort,
        max_tokens=settings.anthropic_max_tokens,
        max_iterations=settings.agent_max_iterations,
        deadline_s=settings.agent_deadline_s,
        refusal_fallbacks=settings.anthropic_refusal_fallbacks,
        system_prompt=build_system_prompt(knowledge),
        tools=build_tools(services),
    )
    services.fallback = FallbackResponder(services)
    services.chat = ChatService(services)
    if settings.seed_sample_data and not settings.is_production:
        seeded = services.service_history.seed_if_empty_sync(settings.service_seed_path)
        if seeded:
            log.info("seeded %d sample service records", seeded)
    return services


async def maintenance_loop(services: Services, interval_s: float = 3600.0) -> None:
    while True:
        try:
            s = services
            await s.db.run(s.limiter.purge_sync)
            await s.db.run(s.cache.purge_sync)
            await s.db.run(s.conversations.purge_sync, s.settings.conversation_retention_days)
            await s.db.run(s.analytics.purge_sync, s.settings.analytics_retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:  # fault barrier
            log.exception("maintenance iteration failed")
        await asyncio.sleep(interval_s)


def start_background(services: Services) -> None:
    if not services.settings.background_workers:
        return
    services.tasks.append(asyncio.create_task(services.outbox.run_forever(services.settings.outbox_poll_interval_s)))
    services.tasks.append(asyncio.create_task(maintenance_loop(services)))


async def shutdown(services: Services) -> None:
    for task in services.tasks:
        task.cancel()
    for task in services.tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    await services.http.aclose()
    if services.owns_anthropic_client and services.anthropic_client is not None:
        with contextlib.suppress(Exception):
            await services.anthropic_client.close()
