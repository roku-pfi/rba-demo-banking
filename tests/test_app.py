"""Opaque bank home; IdP redirect; never talks to the PDP."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from rba_contracts import CallbackTokenResponse, SessionResponse, SessionToken, UserPublic

from rba_demo_banking.config import Settings
from rba_demo_banking.main import create_app, login_url
from rba_demo_banking.scenarios import SCENARIOS, get_scenario


class StubIdp:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {"good-code": "sess-token"}
        self.sessions: dict[str, str] = {"sess-token": "demo@example.com"}
        self.exchanges: list[str] = []

    def exchange(self, code: str) -> CallbackTokenResponse:
        self.exchanges.append(code)
        token = self.codes[code]
        return CallbackTokenResponse(
            session=SessionToken(
                token=token, expires_at=datetime(2026, 8, 17, tzinfo=timezone.utc)
            ),
            user=UserPublic(
                user_id="usr_demo",
                email="demo@example.com",
                created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                is_admin=False,
            ),
        )

    def get_session(self, token: str) -> SessionResponse:
        email = self.sessions[token]
        return SessionResponse(
            user=UserPublic(
                user_id="usr_demo",
                email=email,
                created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                is_admin=False,
            ),
            expires_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
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
    assert "application_id=demo-banking-app" in location
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
    assert "demo@example.com" in html
    assert "Everyday" in html
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


def test_home_does_not_link_walkthrough() -> None:
    idp = StubIdp()
    client = _client(idp)
    client.get("/callback", params={"code": "good-code"}, follow_redirects=False)
    html = client.get("/", follow_redirects=False).text
    assert "/walkthrough" not in html
    assert "Teleport" not in html
    assert "VPN" not in html


def test_walkthrough_lists_scenarios_and_is_not_the_bank() -> None:
    html = _client().get("/walkthrough").text
    assert "Presenter" in html
    assert "Everyday" not in html
    assert "risk_score" not in html
    assert "REQUIRE_MFA" not in html
    for row in SCENARIOS:
        assert row.title in html
        assert f"/walkthrough/start?scenario={row.id}" in html
        assert f"ASN {row.asn}" in html


def test_walkthrough_start_forwards_country_asn_and_clears_session() -> None:
    idp = StubIdp()
    client = _client(idp)
    client.get("/callback", params={"code": "good-code"}, follow_redirects=False)
    teleport = get_scenario("teleport")
    assert teleport is not None
    resp = client.get(
        "/walkthrough/start",
        params={"scenario": teleport.id},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("http://idp.test/login?")
    assert "country=JP" in location
    assert "asn=2516" in location
    assert "application_id=demo-banking-app" in location
    assert "sess-token" not in idp.sessions
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 302


def test_walkthrough_start_unknown_scenario_stays_on_kit() -> None:
    resp = _client().get(
        "/walkthrough/start",
        params={"scenario": "not-a-script"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/walkthrough"


def test_login_url_uses_scenario_signals() -> None:
    settings = Settings(idp_public_url="http://idp.test", public_url="http://bank.test")
    vpn = get_scenario("vpn")
    assert vpn is not None
    url = login_url(settings, vpn)
    assert "country=US" in url
    assert "asn=13335" in url
    assert "risk" not in url
