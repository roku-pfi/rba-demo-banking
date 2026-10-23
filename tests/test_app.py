"""Opaque bank home; IdP redirect; never talks to the PDP."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from rba_contracts import CallbackTokenResponse, SessionResponse, SessionToken, UserPublic

from rba_demo_banking.config import Settings
from rba_demo_banking.idp import IdpError
from rba_demo_banking.main import create_app, login_url
from rba_demo_banking import presenter


# What the IdP flattens the RBAC chain down to (ADR-0029). The bank never sees
# a role or a group — only these scope strings.
CUSTOMER_PERMISSIONS = ["account:read", "transaction:read", "transfer:create"]
VIEWER_PERMISSIONS = ["account:read", "transaction:read"]


class StubIdp:
    def __init__(self, permissions: list[str] | None = None) -> None:
        self.codes: dict[str, str] = {"good-code": "sess-token"}
        self.sessions: dict[str, str] = {"sess-token": "martin@correo.example"}
        self.exchanges: list[str] = []
        self.permissions = (
            CUSTOMER_PERMISSIONS if permissions is None else permissions
        )

    def exchange(self, code: str) -> CallbackTokenResponse:
        self.exchanges.append(code)
        token = self.codes[code]
        return CallbackTokenResponse(
            session=SessionToken(
                token=token, expires_at=datetime(2026, 8, 17, tzinfo=timezone.utc)
            ),
            user=UserPublic(
                tenant_id="roku-bank",
                user_id="usr_rb_martin",
                email="martin@correo.example",
                created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                is_admin=False,
            ),
        )

    def get_session(self, token: str) -> SessionResponse:
        email = self.sessions[token]
        return SessionResponse(
            user=UserPublic(
                tenant_id="roku-bank",
                user_id="usr_rb_martin",
                email=email,
                created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                is_admin=False,
            ),
            expires_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
            application_id="roku-bank-web",
            permissions=list(self.permissions),
        )

    def logout(self, token: str) -> None:
        self.sessions.pop(token, None)


def _client(idp: StubIdp | None = None) -> TestClient:
    settings = Settings(
        idp_public_url="http://idp.test",
        idp_internal_url="http://idp.test",
        public_url="http://bank.test",
    )
    return TestClient(create_app(settings, idp_client=idp or StubIdp()))


def test_healthz() -> None:
    assert _client().get("/healthz").json() == {"status": "ok"}


def test_anonymous_home_redirects_to_idp() -> None:
    resp = _client().get("/", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("http://idp.test/login?")
    assert "client_id=rk_Bk7mQ2xVn9PwR4tL" in location
    assert "redirect_uri=http%3A%2F%2Fbank.test%2Fcallback" in location
    assert "country=AR" in location
    assert "asn=7303" in location


def test_login_url_never_points_at_the_pdp() -> None:
    url = login_url(
        Settings(idp_public_url="http://idp.test", public_url="http://bank.test")
    )
    assert "8000" not in url
    assert "risk" not in url
    assert "evaluate" not in url


def test_callback_sets_cookie_and_home_is_opaque() -> None:
    idp = StubIdp()
    client = _client(idp)
    resp = client.get("/callback", params={"code": "good-code"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    assert idp.exchanges == ["good-code"]
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 200
    html = home.text
    assert "martin@correo.example" in html
    assert "Caja de ahorro en pesos" in html
    assert "Roku Bank" in html
    for forbidden in (
        "risk_score",
        "REQUIRE_MFA",
        "ALLOW",
        "Freeman",
        "reason",
        "PDP",
    ):
        assert forbidden not in html


def test_logout_clears_cookie() -> None:
    idp = StubIdp()
    client = _client(idp)
    client.get("/callback", params={"code": "good-code"}, follow_redirects=False)
    out = client.post("/logout", follow_redirects=False)
    assert out.status_code == 302
    again = client.get("/", follow_redirects=False)
    assert again.status_code == 302
    assert again.headers["location"].startswith("http://idp.test/login?")


def test_home_does_not_link_the_presenter_panel() -> None:
    idp = StubIdp()
    client = _client(idp)
    client.get("/callback", params={"code": "good-code"}, follow_redirects=False)
    html = client.get("/", follow_redirects=False).text
    assert "/presenter" not in html
    assert "Escenario" not in html


# ------------------------------------------------------ presenter panel (D-1)


CLOUD = {
    "_env_file": None,
    "deployment": "cloud",
    "idp_public_url": "https://auth.example",
    "idp_internal_url": "http://idp:8001",
    "public_url": "https://bank.example",
}


def _panel(**overrides) -> TestClient:
    settings = Settings(
        **{
            "_env_file": None,
            "idp_public_url": "http://idp.test",
            "idp_internal_url": "http://idp.test",
            "public_url": "http://bank.test",
            **overrides,
        }
    )
    # https: in the cloud the panel's cookie is Secure.
    return TestClient(create_app(settings, idp_client=StubIdp()), base_url="https://testserver")


def test_local_panel_without_a_secret_is_open() -> None:
    resp = _panel().get("/presenter")
    assert resp.status_code == 200
    assert "Login desde Tokio" in resp.text
    assert "atacantes locales" in resp.text


def test_cloud_panel_without_a_secret_does_not_exist() -> None:
    client = _panel(**CLOUD)
    assert client.get("/presenter").status_code == 404
    assert client.post("/presenter/attack/tokyo").status_code == 404
    assert client.post("/presenter/login", data={"secret": ""}).status_code == 404


def test_panel_with_a_secret_asks_for_it_first() -> None:
    client = _panel(**CLOUD, presenter_secret="p" * 32)
    gate = client.get("/presenter")
    assert gate.status_code == 200
    assert 'name="secret"' in gate.text and "Login desde Tokio" not in gate.text
    assert client.post("/presenter/attack/tokyo").status_code == 404

    wrong = client.post("/presenter/login", data={"secret": "nope"})
    assert wrong.status_code == 401 and "Clave incorrecta" in wrong.text

    ok = client.post("/presenter/login", data={"secret": "p" * 32}, follow_redirects=False)
    assert ok.status_code == 303
    assert "Login desde Tokio" in client.get("/presenter").text


def test_stuffing_levels_clear_the_pdp_thresholds() -> None:
    # ADR-0045 defaults: step-up at 3 unfamiliar failures, IP block at 10 per IP.
    assert presenter.STUFFING["burst"] * len(presenter.REGIONS) >= 3
    assert presenter.STUFFING["burst"] < 10
    assert presenter.STUFFING["lockout"] >= 10


def test_stuffing_runs_every_region_with_wrong_passwords(monkeypatch) -> None:
    seen: list[tuple[str, list[str]]] = []

    def fake_run(self, region, passwords):
        seen.append((region.id, passwords))
        return {"region": region.id, "attempts": []}

    monkeypatch.setattr(presenter.Attackers, "run", fake_run)
    resp = _panel().post("/presenter/attack/stuffing", params={"level": "lockout"})
    assert resp.status_code == 200
    assert sorted(r for r, _ in seen) == sorted(r.id for r in presenter.REGIONS)
    for _, passwords in seen:
        # Past the IP block, then the real password: refused all the same.
        assert len(passwords) == presenter.STUFFING["lockout"] + 1
        assert passwords[-1] == "martin-demo"
        assert "martin-demo" not in passwords[:-1]


def test_stuffing_rejects_an_unknown_level() -> None:
    assert _panel().post("/presenter/attack/stuffing", params={"level": "x"}).status_code == 400


def test_tokyo_uses_the_real_password_from_tokyo(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(
        presenter.Attackers, "run", lambda self, region, pw: seen.append((region.id, pw)) or {"attempts": []}
    )
    _panel().post("/presenter/attack/tokyo")
    assert seen == [("ap-northeast-1", ["martin-demo"])]


def test_attacker_urls_parse() -> None:
    urls = presenter.parse_attacker_urls(
        "ap-northeast-1=https://a.lambda-url.ap-northeast-1.on.aws/, sa-east-1=https://c/"
    )
    assert urls == {
        "ap-northeast-1": "https://a.lambda-url.ap-northeast-1.on.aws/",
        "sa-east-1": "https://c/",
    }


def test_lambda_attack_sends_the_secret_and_the_bank_client(monkeypatch) -> None:
    calls = []

    class Resp:
        status_code = 200

        def json(self):
            return {"egress_ip": "13.112.0.1", "attempts": [{"outcome": "MFA_REQUIRED"}]}

    def fake_post(url, json, headers, timeout):
        calls.append((url, json, headers))
        return Resp()

    monkeypatch.setattr(presenter.httpx, "post", fake_post)
    settings = Settings(_env_file=None, attacker_urls="ap-northeast-1=https://tokyo/", attacker_secret="s3")
    out = presenter.Attackers(settings).tokyo()[0]
    assert out["real"] and out["egress_ip"] == "13.112.0.1"
    url, body, headers = calls[0]
    assert url == "https://tokyo/"
    assert headers == {"X-RokuSec-Attacker-Secret": "s3"}
    assert body["client_id"] == settings.client_id and body["passwords"] == ["martin-demo"]


def test_travel_with_a_secret_carries_a_ticket_not_a_country(monkeypatch) -> None:
    monkeypatch.setattr(presenter, "travel_ticket", lambda settings: "signed.ticket")
    resp = _panel(**CLOUD, presenter_secret="p" * 32, simulation_secret="x" * 32)
    resp.post("/presenter/login", data={"secret": "p" * 32})
    out = resp.get("/presenter/travel", follow_redirects=False)
    assert out.status_code == 302
    location = out.headers["location"]
    assert location.startswith("https://auth.example/login?")
    assert "simulation_ticket=signed.ticket" in location
    assert "country=" not in location


def test_local_travel_states_the_country() -> None:
    url = presenter.travel_login_url(
        Settings(_env_file=None, idp_public_url="http://idp.test", public_url="http://bank.test"), None
    )
    assert "country=JP" in url and "asn=2516" in url


class FakeRedis:
    def __init__(self, data: dict[str, str]) -> None:
        self.data = data

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def delete(self, key):
        return 1 if self.data.pop(key, None) is not None else 0

    def scan_iter(self, match):
        import fnmatch

        return [k for k in list(self.data) if fnmatch.fnmatch(k, match)]


def _fake_redis(monkeypatch, data):
    import json as _json
    import redis

    store = FakeRedis({k: _json.dumps(v) for k, v in data.items()})
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, *a, **k: store))
    return store


def test_reset_failures_keeps_the_history(monkeypatch) -> None:
    import json as _json

    store = _fake_redis(
        monkeypatch,
        {
            "rba:profile:usr_rb_martin": {"login_count": 40, "failed_login_ts": [1.0, 2.0]},
            "rba:guard:roku-bank:ip:13.231.210.211:blocked": 1,
        },
    )
    out = presenter.reset(Settings(_env_file=None, redis_url="redis://x"), "failures")
    assert out["users"] == ["usr_rb_martin"]
    assert not any(k.startswith("rba:guard:") for k in store.data)
    blob = _json.loads(store.data["rba:profile:usr_rb_martin"])
    assert blob == {"login_count": 40, "failed_login_ts": []}


def test_reset_profile_forgets_it(monkeypatch) -> None:
    store = _fake_redis(monkeypatch, {"rba:profile:usr_kz_martin": {"login_count": 3}})
    out = presenter.reset(Settings(_env_file=None, redis_url="redis://x"), "profile")
    assert out["users"] == ["usr_kz_martin"]
    assert store.data == {}


def test_reset_without_a_store_says_so() -> None:
    out = presenter.reset(Settings(_env_file=None), "failures")
    assert out["done"] is False


def test_load_snapshot_before_any_run() -> None:
    snap = presenter.LoadRun().snapshot()
    assert snap["running"] is False and snap["sent"] == 0 and snap["p95_ms"] is None


# ------------------------------------------------------ RBAC enforcement (RF-21)


def _signed_in(idp: StubIdp) -> TestClient:
    """A client holding a live session cookie for `idp`."""
    client = _client(idp)
    client.get("/callback?code=good-code", follow_redirects=False)
    return client


def test_customer_sees_balances_and_the_transfer_action() -> None:
    html = _signed_in(StubIdp()).get("/").text
    assert "Caja de ahorro en pesos" in html
    assert 'href="/transfer"' in html


def test_viewer_sees_balances_but_no_transfer_action() -> None:
    """Same application, same login, one permission short."""
    html = _signed_in(StubIdp(VIEWER_PERMISSIONS)).get("/").text
    assert "Caja de ahorro en pesos" in html
    assert 'href="/transfer"' not in html
    assert "solo consulta" in html


def test_viewer_is_refused_the_transfer_page() -> None:
    resp = _signed_in(StubIdp(VIEWER_PERMISSIONS)).get("/transfer")
    assert resp.status_code == 403
    assert "transfer:create" in resp.text


def test_viewer_is_refused_the_transfer_post() -> None:
    """The control is on the write path, not on whether the button was drawn.

    Hiding the affordance is presentation; a viewer who posts the form directly
    must still be refused.
    """
    resp = _signed_in(StubIdp(VIEWER_PERMISSIONS)).post("/transfer")
    assert resp.status_code == 403
    assert "Transferencia enviada" not in resp.text


def test_customer_can_complete_a_transfer() -> None:
    resp = _signed_in(StubIdp()).post("/transfer")
    assert resp.status_code == 200
    assert "Transferencia enviada" in resp.text


def test_account_read_gates_the_balances() -> None:
    """Signing in and being allowed to see money are separate grants."""
    html = _signed_in(StubIdp(["transaction:read"])).get("/").text
    assert "Caja de ahorro" not in html
    assert "No tenés cuentas visibles" in html


def test_transfer_without_a_session_redirects_to_login() -> None:
    resp = _client().get("/transfer", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("http://idp.test/login?")


def test_brand_styles_and_fonts_are_served() -> None:
    """The bank has its own identity (B-3), nothing shared with RokuSec, and
    serves it itself. A 404 here is silent, so it is asserted."""
    client = _client()
    css = client.get("/static/bank.css")
    assert css.status_code == 200
    assert "Plus Jakarta Sans" in css.text
    assert "fonts.googleapis.com" not in css.text
    for path in ("/static/fonts/plus-jakarta-sans-latin-700-normal.woff2", "/static/brand/roku-bank-mark.svg"):
        served = client.get(path)
        assert served.status_code == 200, path
    assert client.get("/static/fonts/plus-jakarta-sans-latin-700-normal.woff2").content[:4] == b"wOF2"


def test_money_is_formatted_for_argentina() -> None:
    from rba_demo_banking.main import ars

    assert ars(1_750_320.15) == "$ 1.750.320,15"
    assert ars(-12_430, signed=True) == "− $ 12.430,00"
    assert ars(25_000, signed=True) == "+ $ 25.000,00"


# ------------------------------------------------------------- C-1: cloud settings


def test_cloud_marks_the_session_cookie_secure() -> None:
    settings = Settings(
        _env_file=None,
        deployment="cloud",
        idp_public_url="https://d1fg623tjiucw7.cloudfront.net",
        idp_internal_url="http://idp.rba.svc.cluster.local:8001",
        public_url="https://d3m6kfm1gma0g6.cloudfront.net",
    )
    assert settings.cookie_secure is True
    client = TestClient(create_app(settings, idp_client=StubIdp()), base_url="https://testserver")
    resp = client.get("/callback", params={"code": "good-code"}, follow_redirects=False)
    cookie = resp.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie


def test_local_cookie_is_not_secure() -> None:
    resp = _client().get("/callback", params={"code": "good-code"}, follow_redirects=False)
    assert "secure" not in resp.headers["set-cookie"].lower()


@pytest.mark.parametrize(
    "override",
    [
        {"public_url": "http://d3m6kfm1gma0g6.cloudfront.net"},
        {"idp_public_url": "http://localhost:8001"},
        {"idp_internal_url": "http://localhost:8001"},
    ],
)
def test_cloud_refuses_local_urls(override: dict) -> None:
    base = {
        "deployment": "cloud",
        "idp_public_url": "https://d1fg623tjiucw7.cloudfront.net",
        "idp_internal_url": "http://idp:8001",
        "public_url": "https://d3m6kfm1gma0g6.cloudfront.net",
    }
    with pytest.raises(ValidationError, match="DEPLOYMENT=cloud"):
        Settings(_env_file=None, **{**base, **override})


def test_cloud_login_link_does_not_pin_the_home_location() -> None:
    settings = Settings(
        _env_file=None,
        deployment="cloud",
        idp_public_url="https://d1fg623tjiucw7.cloudfront.net",
        idp_internal_url="http://idp:8001",
        public_url="https://d3m6kfm1gma0g6.cloudfront.net",
    )
    url = login_url(settings)
    assert "country=" not in url and "asn=" not in url
