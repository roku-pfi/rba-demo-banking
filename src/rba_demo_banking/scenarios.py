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
            "Germany / Deutsche Telekom. Unseen country for Freeman. "
            "Pick this from a cold seed (weeks since last success) so travel "
            "does not also fire; after a just-completed home login it will."
        ),
        country="DE",
        asn="3320",
        expect="MFA from Freeman + policy (unseen country)",
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
)

SCENARIO_BY_ID: dict[str, Scenario] = {row.id: row for row in SCENARIOS}


def get_scenario(scenario_id: str) -> Scenario | None:
    return SCENARIO_BY_ID.get(scenario_id)
