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
| New country | DE / 3320 | MFA from `supervised_second_opinion` (score stays ~0.00) |
| Teleport | JP / 2516 | MFA from the travel rule (right after home) |
| VPN | US / 13335 | MFA as untrusted network, not teleport |
| Stuffing — burst | AR / 7303 | REAUTHENTICATE from `failed_login_burst` |
| Stuffing — lockout | AR / 7303 | BLOCK from `failed_login_lockout` |

Live script: new country first → home → teleport immediately → VPN → stuffing
burst → stuffing lockout. All four PDP actions appear once. Keep admin Decisions
in a second window.

`new_country` is **not** a Freeman catch, despite the name. Against the seeded
profile Freeman scores it 0.0000 → `ALLOW`: a novel value contributes at most
`log((history + β)/β)` — `+3.025` for the 98-login seed, the same for every
signal — while each familiar signal contributes about `−12` and keeps growing
with history. Two novel signals (`+6`) lose to three familiar ones (`−36`).
The step-up comes from the supervised second opinion (0.9823 against its 0.9028
threshold). Novelty saturates; familiarity accumulates. This is the clearest
demonstration in the demo of why ADR-0027 added a second opinion at all.

The stuffing steps deliberately run from the user's **own** country and ASN
(ADR-0027). From a novel network Freeman already scores CRITICAL and BLOCKs on
novelty alone, so the failed-login band is never reached and the demo proves
nothing. Keeping the context ordinary holds the score at 0.00, and the action
still walks ALLOW → REAUTHENTICATE → BLOCK on the failure count alone — which is
the mechanism being demonstrated. `tests/test_app.py` pins this.

Run them **last**: the failures live in a 24-hour window and keep escalating
later logins. Reset before re-running (see below).

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

## Reset between runs

The stuffing scenarios leave failures in the 24-hour window, so a second
rehearsal starts dirty. The seed is `SET NX`, so deleting the key and
restarting `profile-service` re-seeds it — but an in-flight decision event can
land *after* the reseed and re-pollute the blob. Use the retrying helper:

```bash
bash ../rba-infra/scripts/reset-demo.sh     # k3d; verifies it reached the pristine seed
```

It prints `pristine seed: 98 0 203.0.113.10` when the profile is clean. Do not
skip the check — a silently dirty profile changes every action in the script.

## Guardrails

- Do **not** call `/risk/evaluate` or any PDP URL from this process.
- Do **not** render `risk_score`, `action`, `risk_level`, or reasons on `/`.
- Do **not** put the scenario picker on the customer home.
- Return path is `redirect_uri` + one-time code. No OIDC/SAML/discovery.
- Hosted login stays on the IdP origin.
