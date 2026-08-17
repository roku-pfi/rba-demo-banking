# AGENTS.md — rba-demo-banking

Demo-3 tenant app in namespace `demo`. Status: `../docs/plans/status.md`.
ADR-0023 (opaque), ADR-0024 (separate app), ADR-0025 (ns `demo`), ADR-0026
(walkthrough on the relying party). Demo-4 WebAuthn lives on the IdP.

## Guardrails

- Authenticate **through the IdP**. Never call `decision-service` / Freeman.
- Dummy home only — no score, action, or reasons on this origin.
- Presenter kit is `/walkthrough` only — do not link it from `/`.
- Thin `redirect_uri` + `POST /callback/token`. Not OIDC/SAML/SCIM.
- Do not add Redis/Postgres compose here — use `../rba-infra`.
