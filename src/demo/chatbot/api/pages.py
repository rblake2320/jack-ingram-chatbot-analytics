"""Server-rendered pages: customer chat, admin dashboard, agent console."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..config import PACKAGE_DIR
from .deps import get_services

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    services = get_services(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"dealer": services.knowledge.public_info(), "version": __version__, "is_sample": services.inventory.is_sample},
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin.html", {"version": __version__})


@router.get("/agent", response_class=HTMLResponse)
async def agent_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "agent.html", {"version": __version__})
