# rba-demo-banking

Demo-3 **relying party**: a dummy bank that authenticates **through the IdP**,
plus the presenter panel at `/presenter` (D-1, stage machinery). The bank never
calls `rba-decision-service` / Freeman
([ADR-0024](../docs/decisions/0024-separate-demo-app.md),
[ADR-0025](../docs/decisions/0025-demo-app-separate-namespace.md),
[ADR-0026](../docs/decisions/0026-restage-demo-around-tenant-app.md)).

The home page is **opaque** — balances only, no score / action / reasons, and
no scenario picker ([ADR-0023](../docs/decisions/0023-end-user-login-is-opaque.md)).
Explainability lives in IdP admin Decisions. The presenter panel lives on a
separate, unlinked URL.

Package version: **0.2.0**. Pins `rba-contracts` ≥ 0.5.0.

> Status: [`../docs/plans/status.md`](../docs/plans/status.md). AI: [`AGENTS.md`](AGENTS.md).

## Request path

```
browser  GET http://localhost:8002/          (compose) or http://demo.localhost:8080/ (k3d)
           → no cookie  → 302 IdP /login?client_id=rk_Bk7mQ2xVn9PwR4tL&redirect_uri=…/callback&country=AR&asn=7303
IdP      password + PDP + ALLOW/MFA
           → 302 {redirect_uri}?code=…
browser  GET /callback?code=…
app      POST IdP /callback/token  (server-side; not OIDC)
           → httpOnly cookie → 302 /
browser  GET /   dummy balances
```

## Presenter panel (D-1)

`/presenter`, not linked from `/` and not part of the bank or of RokuSec
([ADR-0035](../docs/decisions/0035-demo-around-personas-and-tenants.md),
[ADR-0041](../docs/decisions/0041-stage-machinery-wiring.md)). Behind
`PRESENTER_SECRET`; locally open without one, in the cloud absent without one.

| Scene | What it does | Expect |
|---|---|---|
| Login desde Tokio | Tokyo Lambda logs in with Martín's real password | MFA; the attacker stops at the passkey |
| Stuffing · ráfaga | 1 wrong password from each of 3 regions | Martín's next login: REAUTHENTICATE |
| Stuffing · sostenido | 4 from each region (12) | Martín's next login: BLOCK |
| Viaje imposible | opens the login with a signed ticket (JP / KDDI) | MFA, marked simulado |
| Carga | 32 clients on the PDP's `/risk/evaluate` for 90 s | PDP replicas scale; p95 in the panel |
| Limpiar fallos / Olvidar perfil | empties Martín's failure window / deletes his profile | — |

The attackers are the Lambdas of `../rba-infra/attacker` when `ATTACKER_URLS` is
set; otherwise local stand-ins that state the region's country/ASN, which only a
local IdP believes. Load and reset are the only places this process talks to the
platform directly (`PDP_URL`, `REDIS_URL`), and they are the panel's, not the bank's.

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

Open http://localhost:8002 — sign in as `martin@correo.example` / `martin-demo`.

`DEPLOYMENT=cloud` (default `local`) marks the session cookie `Secure` and
refuses to start unless `PUBLIC_URL` and `IDP_PUBLIC_URL` are https and
`IDP_INTERNAL_URL` is not localhost. `COOKIE_SECURE` sets the flag on its own.
Presenter panel: http://localhost:8002/presenter.

## Cluster

`../rba-infra/scripts/k3d-up.sh` deploys this app in namespace `demo`.
Bank: http://demo.localhost:8080 (`.localhost` resolves to loopback).
Presenter panel: http://demo.localhost:8080/presenter.
IdP stays http://localhost:8080.

## Reset between runs

The stuffing scenes leave failures in the 24-hour window. "Limpiar fallos" in
the panel empties it and keeps the history. Under load the profile updates
queue, so failures can reach the window a few seconds late; reset after they
land. To go back to the pristine local seed instead:

```bash
bash ../rba-infra/scripts/reset-demo.sh     # k3d; verifies it reached the pristine seed
```

## Guardrails

- Do **not** call `/risk/evaluate` or any PDP URL from the bank's pages. Only the
  presenter panel's load test does (ADR-0041).
- Do **not** render `risk_score`, `action`, `risk_level`, or reasons on `/`.
- Do **not** link the presenter panel from the customer home.
- Return path is `redirect_uri` + one-time code. No OIDC/SAML/discovery.
- Hosted login stays on the IdP origin.
