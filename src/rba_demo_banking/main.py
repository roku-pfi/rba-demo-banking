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
from rba_demo_banking.scenarios import SCENARIOS, Scenario, get_scenario

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"

BALANCES = (
    {"name": "Everyday", "number": "···· 4412", "amount": "AR$ 248.320,15"},
    {"name": "Savings", "number": "···· 9081", "amount": "AR$ 1.502.000,00"},
)

# Permissions this relying party asks about (ADR-0029). The bank never sees a
# role or a group — the IdP flattens the chain and hands over scope strings.
PERM_ACCOUNT_READ = "account:read"
PERM_TRANSFER_CREATE = "transfer:create"


def _signals(settings: Settings, scenario: Scenario) -> tuple[str, str]:
    if scenario.id == "home":
        return settings.home_country, settings.home_asn
    return scenario.country, scenario.asn


def login_url(settings: Settings, scenario: Scenario | None = None) -> str:
    chosen = scenario or get_scenario("home")
    assert chosen is not None
    country, asn = _signals(settings, chosen)
    callback = f"{settings.public_url.rstrip('/')}/callback"
    query = urlencode(
        {
            "application_id": settings.application_id,
            "redirect_uri": callback,
            "country": country,
            "asn": asn,
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

    app = FastAPI(title=settings.app_name, version="0.2.0")
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

    def _abandon_session(request: Request) -> None:
        token = request.cookies.get(settings.session_cookie)
        if token:
            idp.logout(token)

    def _run_attack(scenario: Scenario) -> None:
        """Fire the scenario's wrong-password burst before the presenter logs in.

        Sequential and small (≤12): this is a demo of a *signal*, not a load
        test, and each attempt has to be recorded before the next real login is
        scored. Best effort — a failure here should spoil the scenario, not the
        walkthrough.
        """
        for _ in range(scenario.failed_attempts):
            try:
                idp.failed_attempt(
                    settings.victim_email,
                    country=scenario.country,
                    asn=scenario.asn,
                )
            except IdpError:
                logger.warning("attack step dropped for scenario=%s", scenario.id)

    def _start_login(request: Request, scenario: Scenario) -> Response:
        _abandon_session(request)
        _run_attack(scenario)
        response = RedirectResponse(login_url(settings, scenario), status_code=302)
        response.delete_cookie(settings.session_cookie, path="/")
        return response

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
        permissions = set(session.permissions)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "email": session.user.email,
                # A signed-in user without `account:read` sees the shell and no
                # balances — sign-in and visibility are separate grants.
                "balances": BALANCES if PERM_ACCOUNT_READ in permissions else (),
                "can_transfer": PERM_TRANSFER_CREATE in permissions,
                # Shown on the page: what the bank was handed, verbatim.
                "permissions": sorted(permissions),
            },
        )

    def _require(request: Request, permission: str):
        """Resolve the session and authorize one operation (RF-21).

        Returns ``(session, None)`` when allowed, ``(None, response)`` when not.
        The bank asks the IdP on every request rather than trusting anything in
        the cookie, so a role revoked mid-session stops working immediately.
        """
        token = request.cookies.get(settings.session_cookie)
        if not token:
            return None, RedirectResponse(login_url(settings), status_code=302)
        try:
            session = idp.get_session(token)
        except IdpError:
            response = RedirectResponse(login_url(settings), status_code=302)
            response.delete_cookie(settings.session_cookie, path="/")
            return None, response
        if permission not in set(session.permissions):
            return None, templates.TemplateResponse(
                request=request,
                name="denied.html",
                status_code=403,
                context={
                    "email": session.user.email,
                    "permission": permission,
                },
            )
        return session, None

    @app.get("/transfer")
    def transfer_form(request: Request):
        session, refused = _require(request, PERM_TRANSFER_CREATE)
        if refused is not None:
            return refused
        return templates.TemplateResponse(
            request=request,
            name="transfer.html",
            context={"email": session.user.email, "sent": None},
        )

    @app.post("/transfer")
    def transfer_submit(request: Request):
        # Checked again on the write path. Hiding the button is presentation;
        # this is the control.
        session, refused = _require(request, PERM_TRANSFER_CREATE)
        if refused is not None:
            return refused
        return templates.TemplateResponse(
            request=request,
            name="transfer.html",
            context={"email": session.user.email, "sent": "AR$ 12.500,00"},
        )

    @app.get("/walkthrough")
    def walkthrough(request: Request):
        """Presenter kit — not linked from the customer home (ADR-0023)."""
        return templates.TemplateResponse(
            request=request,
            name="walkthrough.html",
            context={"scenarios": SCENARIOS},
        )

    @app.get("/walkthrough/start")
    def walkthrough_start(request: Request, scenario: str = "home"):
        chosen = get_scenario(scenario)
        if chosen is None:
            return RedirectResponse("/walkthrough", status_code=302)
        return _start_login(request, chosen)

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
        _abandon_session(request)
        response = RedirectResponse("/", status_code=302)
        response.delete_cookie(settings.session_cookie, path="/")
        return response

    return app


app = create_app()
