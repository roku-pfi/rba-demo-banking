# rba-demo-banking

Demo-2 **relying party**: a dummy bank that authenticates **through the IdP**.
It never calls `rba-decision-service` / Freeman
([ADR-0024](../docs/decisions/0024-separate-demo-app.md),
[ADR-0025](../docs/decisions/0025-demo-app-separate-namespace.md),
[ADR-0026](../docs/decisions/0026-restage-demo-around-tenant-app.md)).

The home page is **opaque** — balances only, no score / action / reasons
([ADR-0023](../docs/decisions/0023-end-user-login-is-opaque.md)). Explainability
lives in IdP admin Decisions.

Package version: **0.1.0**. Pins `rba-contracts` ≥ 0.5.0.

> Status: [`../docs/plans/status.md`](../docs/plans/status.md). AI: [`AGENTS.md`](AGENTS.md).

## Request path

```
browser  GET http://localhost:8002/          (compose) or http://demo.localhost:8080/ (k3d)
           → no cookie  → 302 IdP /login?application_id=demo-banking-app&redirect_uri=…/callback
IdP      password + PDP + ALLOW/MFA
           → 302 {redirect_uri}?code=…
browser  GET /callback?code=…
app      POST IdP /callback/token  (server-side; not OIDC)
           → httpOnly cookie → 302 /
browser  GET /   dummy balances
```

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

## Cluster

`../rba-infra/scripts/k3d-up.sh` deploys this app in namespace `demo`.
Bank: http://demo.localhost:8080 (`.localhost` resolves to loopback).
IdP stays http://localhost:8080.

## Guardrails

- Do **not** call `/risk/evaluate` or any PDP URL from this process.
- Do **not** render `risk_score`, `action`, `risk_level`, or reasons.
- Return path is `redirect_uri` + one-time code. No OIDC/SAML/discovery.
- Hosted login stays on the IdP origin.
