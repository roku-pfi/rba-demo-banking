# AGENTS.md — rba-demo-banking

Demo-3 tenant app in namespace `demo`. Status: `../docs/plans/status.md`.
ADR-0023 (opaque), ADR-0024 (separate app), ADR-0025 (ns `demo`), ADR-0026
(presenter controls on the relying party), ADR-0041 (presenter panel). Demo-4 WebAuthn lives on the IdP.

## Guardrails

- Authenticate **through the IdP**. The bank never calls `decision-service` /
  Freeman; only the presenter panel's load test does (stage machinery).
- Dummy home only — no score, action, or reasons on this origin.
- Presenter panel is `/presenter` only — do not link it from `/`.
- Thin `redirect_uri` + `POST /callback/token`. Not OIDC/SAML/SCIM.
- Do not add Redis/Postgres compose here — use `../rba-infra`.
