"""Presenter next-login contexts (Demo-3). Not customer chrome (ADR-0023).

Country/ASN match Demo-1 TEST-NET stand-ins and the VPN ASN list in
``rba-features``. The bank only forwards these as IdP query params.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    blurb: str
    country: str
    asn: str
    expect: str
    # Wrong-password attempts to fire against the IdP before handing the
    # presenter the login page (ADR-0027). 0 = an ordinary next-login context.
    failed_attempts: int = 0


# Order is the live script. ``home`` country/ASN may be overridden by Settings.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="home",
        title="Home",
        blurb="Usual Argentina / Telecom Argentina. Seeded profile; expect ALLOW.",
        country="AR",
        asn="7303",
        expect="ALLOW → bank home (no risk UI)",
    ),
    Scenario(
        id="new_country",
        title="New country",
        blurb=(
            "Germany / Deutsche Telekom — unseen country and unseen ASN. "
            "Freeman still scores this near 0.00: a novel value can only ever "
            "contribute log((history + beta) / beta), while familiar ones "
            "(IP, browser, OS) keep accumulating, so two novel signals cannot "
            "outweigh three familiar ones for a well-established user. The "
            "supervised model is what catches it. Pick this from a cold seed "
            "so travel does not also fire; after a home login it will."
        ),
        country="DE",
        asn="3320",
        expect="MFA from the supervised second opinion — not from the score",
    ),
    Scenario(
        id="teleport",
        title="Teleport",
        blurb="Japan / KDDI, immediately after a successful home login. Far, too fast.",
        country="JP",
        asn="2516",
        expect="MFA from the travel rule (impossible_travel)",
    ),
    Scenario(
        id="vpn",
        title="VPN",
        blurb="United States / Cloudflare. VPN ASN skips physics; still untrusted.",
        country="US",
        asn="13335",
        expect="MFA as untrusted network (vpn_or_hosting), not teleport",
    ),
    Scenario(
        id="stuffing_burst",
        title="Credential stuffing — burst",
        blurb=(
            "Fires 4 wrong passwords at demo@example.com, then opens the login "
            "page. Deliberately from the user's OWN country and ASN — a "
            "residential proxy, which is what stuffing actually looks like. "
            "Freeman scores this 0.00: nothing about the context is novel "
            "enough to matter. Only failed_logins_last_24h moves the action."
        ),
        country="AR",
        asn="7303",
        expect="REAUTHENTICATE from failed_login_burst — the score stays 0.00",
        failed_attempts=4,
    ),
    Scenario(
        id="stuffing_lockout",
        title="Credential stuffing — lockout",
        blurb=(
            "Same ordinary context, sustained: 12 wrong passwords. Past the "
            "lockout band the honest answer is to stop serving the account, "
            "not to challenge it. The score is still 0.00 — the model never "
            "saw this coming, and that is the point."
        ),
        country="AR",
        asn="7303",
        expect="BLOCK from failed_login_lockout — no challenge offered",
        failed_attempts=12,
    ),
)

SCENARIO_BY_ID: dict[str, Scenario] = {row.id: row for row in SCENARIOS}


def get_scenario(scenario_id: str) -> Scenario | None:
    return SCENARIO_BY_ID.get(scenario_id)
