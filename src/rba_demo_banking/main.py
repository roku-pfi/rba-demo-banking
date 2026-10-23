"""Opaque banking home. Authenticates through the IdP; never calls the PDP."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rba_demo_banking.config import Settings, get_settings
from rba_demo_banking.idp import HttpIdpClient, IdpClient, IdpError
from rba_demo_banking import presenter

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"

def ars(amount: float, *, signed: bool = False) -> str:
    """$ 1.234.567,89 — es-AR grouping, without depending on the OS locale."""
    whole, cents = f"{abs(amount):,.2f}".split(".")
    sign = ("+ " if amount > 0 else "− " if amount < 0 else "") if signed else ("−" if amount < 0 else "")
    return f"{sign}$ {whole.replace(',', '.')},{cents}"


# Demo data: what a customer sees once signed in. Nothing here is real.
BALANCES = (
    {"name": "Caja de ahorro en pesos", "number": "···· 4412", "amount": ars(248_320.15)},
    {"name": "Cuenta ahorro", "number": "···· 9081", "amount": ars(1_502_000.00)},
)
TOTAL = ars(248_320.15 + 1_502_000.00)
MOVEMENTS = (
    {"who": "Supermercado Día", "what": "Compra con débito", "when": "Hoy", "amount": ars(-12_430.00, signed=True), "icon": "S"},
    {"who": "Sofía Paz", "what": "Transferencia recibida", "when": "Ayer", "amount": ars(25_000.00, signed=True), "icon": "SP"},
    {"who": "Edesur", "what": "Pago de servicio", "when": "Ayer", "amount": ars(-18_760.40, signed=True), "icon": "E"},
    {"who": "Sueldo · Kaze Labs", "what": "Acreditación", "when": "1 oct", "amount": ars(1_180_000.00, signed=True), "icon": "K"},
    {"who": "Spotify", "what": "Suscripción", "when": "30 sep", "amount": ars(-4_299.00, signed=True), "icon": "S"},
)
TRANSFER = {"to": "Sofía Paz", "bank": "Roku Bank", "account": "···· 9081", "amount": ars(12_500.00)}


def display_name(email: str) -> str:
    """The greeting's name: the address's local part, capitalised."""
    return email.split("@", 1)[0].replace(".", " ").title()

# Permissions this relying party asks about (ADR-0029). The bank never sees a
# role or a group — the IdP flattens the chain and hands over scope strings.
PERM_ACCOUNT_READ = "account:read"
PERM_TRANSFER_CREATE = "transfer:create"


def login_url(settings: Settings) -> str:
    callback = f"{settings.public_url.rstrip('/')}/callback"
    params = {"client_id": settings.client_id, "redirect_uri": callback}
    # Locally every request comes from a private address, so the bank pins the
    # home country/ASN to make a plain login look usual. In the cloud the IdP
    # geolocates the real address (ADR-0032); pinning would hand every visitor
    # Martín's home.
    if settings.deployment != "cloud":
        params["country"], params["asn"] = settings.home_country, settings.home_asn
    query = urlencode(params)
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
            "secure": settings.cookie_secure,
            "path": "/",
        }

    def _abandon_session(request: Request) -> None:
        token = request.cookies.get(settings.session_cookie)
        if token:
            idp.logout(token)

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
                "name": display_name(session.user.email),
                # A signed-in user without `account:read` sees the shell and no
                # balances — sign-in and visibility are separate grants.
                "balances": BALANCES if PERM_ACCOUNT_READ in permissions else (),
                "total": TOTAL,
                "movements": MOVEMENTS if PERM_ACCOUNT_READ in permissions else (),
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
                    "name": display_name(session.user.email),
                    "permission": permission,
                    "can_transfer": PERM_TRANSFER_CREATE in set(session.permissions),
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
            context={"email": session.user.email, "name": display_name(session.user.email), "transfer": TRANSFER, "sent": False, "can_transfer": True},
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
            context={"email": session.user.email, "name": display_name(session.user.email), "transfer": TRANSFER, "sent": True, "can_transfer": True},
        )

    # ---------------------------------------------------------------- presenter panel (D-1)

    attackers = presenter.Attackers(settings)
    load = presenter.LoadRun()

    def _presenter(request: Request) -> None:
        """Every panel action starts here. Same 404 whether off or not signed in."""
        if not presenter.enabled(settings) or not presenter.authorized(
            settings, request.cookies.get(presenter.COOKIE)
        ):
            raise HTTPException(status_code=404, detail="not found")

    def _panel(request: Request, *, wrong: bool = False, status_code: int = 200):
        if not presenter.enabled(settings):
            raise HTTPException(status_code=404, detail="not found")
        return templates.TemplateResponse(
            request=request,
            name="presenter.html",
            status_code=status_code,
            context={
                "authorized": presenter.authorized(settings, request.cookies.get(presenter.COOKIE)),
                "wrong": wrong,
                "attackers_real": attackers.real,
                "victim": settings.victim_email,
                "load_seconds": settings.load_seconds,
                "load_concurrency": settings.load_concurrency,
            },
        )

    @app.get("/presenter")
    def presenter_panel(request: Request):
        """Not linked from the customer home (ADR-0023)."""
        return _panel(request)

    @app.post("/presenter/login")
    def presenter_login(request: Request, secret: str = Form("")):
        if not presenter.enabled(settings):
            raise HTTPException(status_code=404, detail="not found")
        value = presenter.cookie_value(settings, secret)
        if value is None:
            return _panel(request, wrong=True, status_code=401)
        response = RedirectResponse("/presenter", status_code=303)
        response.set_cookie(presenter.COOKIE, value, **{**_cookie_kwargs(), "path": "/presenter", "samesite": "strict"})
        return response

    @app.post("/presenter/attack/tokyo")
    def presenter_tokyo(request: Request) -> dict:
        _presenter(request)
        return {"regions": attackers.tokyo()}

    @app.post("/presenter/attack/stuffing")
    def presenter_stuffing(request: Request, level: str = "burst") -> dict:
        _presenter(request)
        if level not in presenter.STUFFING:
            raise HTTPException(status_code=400, detail="level: burst | lockout")
        return {"regions": attackers.stuffing(
            presenter.STUFFING[level], then_right=presenter.STUFFING_ENDS_WITH_PASSWORD[level]
        )}

    @app.get("/presenter/travel")
    def presenter_travel(request: Request):
        _presenter(request)
        _abandon_session(request)
        try:
            ticket = presenter.travel_ticket(settings)
        except Exception as exc:
            logger.warning("simulation ticket refused: %s", exc)
            raise HTTPException(status_code=502, detail="el IdP no emitió el ticket") from exc
        response = RedirectResponse(presenter.travel_login_url(settings, ticket), status_code=302)
        response.delete_cookie(settings.session_cookie, path="/")
        return response

    @app.post("/presenter/load")
    def presenter_load_start(request: Request) -> dict:
        _presenter(request)
        return {"load": True, "started": load.start(settings)}

    @app.get("/presenter/load")
    def presenter_load_status(request: Request) -> dict:
        _presenter(request)
        return load.snapshot()

    @app.post("/presenter/reset")
    def presenter_reset(request: Request, mode: str = "failures") -> dict:
        _presenter(request)
        if mode not in ("failures", "profile"):
            raise HTTPException(status_code=400, detail="mode: failures | profile")
        try:
            return {"reset": presenter.reset(settings, mode)}
        except Exception as exc:
            logger.warning("reset failed: %s", exc)
            return {"reset": {"done": False, "users": [], "error": "sin acceso al almacén de perfiles"}}

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
