# rba-demo-banking

Demo-3 **relying party**: a dummy bank that authenticates **through the IdP**,
plus a presenter-only walkthrough at `/walkthrough`. It never calls
`rba-decision-service` / Freeman
([ADR-0024](../docs/decisions/0024-separate-demo-app.md),
[ADR-0025](../docs/decisions/0025-demo-app-separate-namespace.md),
[ADR-0026](../docs/decisions/0026-restage-demo-around-tenant-app.md)).

The home page is **opaque** — balances only, no score / action / reasons, and
no scenario picker ([ADR-0023](../docs/decisions/0023-end-user-login-is-opaque.md)).
Explainability lives in IdP admin Decisions. Walkthrough controls live on a
separate, unlinked URL.

Package version: **0.2.0**. Pins `rba-contracts` ≥ 0.5.0.

> Status: [`../docs/plans/status.md`](../docs/plans/status.md). AI: [`AGENTS.md`](AGENTS.md).

## Request path

```
browser  GET http://localhost:8002/          (compose) or http://demo.localhost:8080/ (k3d)
           → no cookie  → 302 IdP /login?application_id=demo-banking-app&redirect_uri=…/callback&country=AR&asn=7303
IdP      password + PDP + ALLOW/MFA
           → 302 {redirect_uri}?code=…
browser  GET /callback?code=…
app      POST IdP /callback/token  (server-side; not OIDC)
           → httpOnly cookie → 302 /
browser  GET /   dummy balances

presenter  GET /walkthrough
           → GET /walkthrough/start?scenario=home|new_country|teleport|vpn
           → clears cookie → 302 IdP /login?…&country=&asn=
```

## Walkthrough (presenter)

Open `/walkthrough` (not linked from `/`). Each control logs out and starts a
login with a fixed country/ASN:

| Control | Country / ASN | Expect (admin shows why) |
|---|---|---|
| Home | AR / 7303 | ALLOW |
| New country | DE / 3320 | MFA from Freeman (best from a cold seed) |
| Teleport | JP / 2516 | MFA from the travel rule (right after home) |
| VPN | US / 13335 | MFA as untrusted network, not teleport |

Live script: new country first → home → teleport immediately → VPN. Keep admin
Decisions in a second window.

## Local (no cluster)

Data plane + PDP + IdP + profile-service (for the home-profile seed) must be up.
Then:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ../rba-contracts -e ".[dev]"
IDP_PUBLIC_URL=http://localhost:8001 \
IDP_INTERNAL_URL=http://localhost:8001 \
PUBLIC_URL=http://localhost:8002 \
uvicorn rba_demo_banking.main:app --reload --port 8002
```

Open http://localhost:8002 — sign in as `demo@example.com` / `demo-password`.
Presenter kit: http://localhost:8002/walkthrough.

## Cluster

`../rba-infra/scripts/k3d-up.sh` deploys this app in namespace `demo`.
Bank: http://demo.localhost:8080 (`.localhost` resolves to loopback).
Walkthrough: http://demo.localhost:8080/walkthrough.
IdP stays http://localhost:8080.

## Guardrails

- Do **not** call `/risk/evaluate` or any PDP URL from this process.
- Do **not** render `risk_score`, `action`, `risk_level`, or reasons on `/`.
- Do **not** put the scenario picker on the customer home.
- Return path is `redirect_uri` + one-time code. No OIDC/SAML/discovery.
- Hosted login stays on the IdP origin.
