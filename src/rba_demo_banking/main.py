"""Opaque banking home. Authenticates through the IdP; never calls the PDP."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rba_demo_banking.config import Settings, get_settings
from rba_demo_banking.idp import HttpIdpClient, IdpClient, IdpError

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"

BALANCES = (
    {"name": "Everyday", "number": "···· 4412", "amount": "AR$ 248.320,15"},
    {"name": "Savings", "number": "···· 9081", "amount": "AR$ 1.502.000,00"},
)


def login_url(settings: Settings) -> str:
    callback = f"{settings.public_url.rstrip('/')}/callback"
    query = urlencode(
        {
            "application_id": settings.application_id,
            "redirect_uri": callback,
            "country": settings.home_country,
            "asn": settings.home_asn,
        }
    )
    return f"{settings.idp_public_url.rstrip('/')}/login?{query}"


def create_app(
    settings: Settings | None = None,
    *,
    idp_client: IdpClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    idp = idp_client or HttpIdpClient(settings)
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    app.state.idp = idp
    static = WEB_DIR / "static"
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=str(static)), name="static")

    def _cookie_kwargs() -> dict:
        return {
            "httponly": True,
            "samesite": "lax",
            "path": "/",
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def home(request: Request):
        token = request.cookies.get(settings.session_cookie)
        if not token:
            return RedirectResponse(login_url(settings), status_code=302)
        try:
            session = idp.get_session(token)
        except IdpError:
            response = RedirectResponse(login_url(settings), status_code=302)
            response.delete_cookie(settings.session_cookie, path="/")
            return response
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "email": session.user.email,
                "balances": BALANCES,
            },
        )

    @app.get("/callback")
    def callback(code: str | None = None):
        if not code:
            return RedirectResponse(login_url(settings), status_code=302)
        try:
            exchanged = idp.exchange(code)
        except IdpError:
            return RedirectResponse(login_url(settings), status_code=302)
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            settings.session_cookie,
            exchanged.session.token,
            **_cookie_kwargs(),
        )
        return response

    @app.post("/logout")
    def logout(request: Request) -> Response:
        token = request.cookies.get(settings.session_cookie)
        if token:
            idp.logout(token)
        response = RedirectResponse("/", status_code=302)
        response.delete_cookie(settings.session_cookie, path="/")
        return response

    return app


app = create_app()
