# AGENTS.md — rba-demo-banking

Demo-2 tenant app in namespace `demo`. Status: `../docs/plans/status.md`.
ADR-0023 (opaque), ADR-0024 (separate app), ADR-0025 (ns `demo`), ADR-0026 (this stage).

## Guardrails

- Authenticate **through the IdP**. Never call `decision-service` / Freeman.
- Dummy home only — no score, action, or reasons on this origin.
- Thin `redirect_uri` + `POST /callback/token`. Not OIDC/SAML/SCIM.
- Do not add Redis/Postgres compose here — use `../rba-infra`.
