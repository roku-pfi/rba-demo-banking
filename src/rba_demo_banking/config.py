"""Runtime settings (env / .env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "rba-demo-banking"
    host: str = "0.0.0.0"
    port: int = 8002

    # C-1. "cloud" refuses to start on a local default (see `_cloud_is_explicit`).
    deployment: Literal["local", "cloud"] = "local"
    # Session cookie `Secure` flag. Forced on in the cloud, where every hop the
    # browser sees is https; off locally, where http://localhost would drop it.
    cookie_secure: bool = False

    # Browser-facing IdP origin (hosted login redirect).
    idp_public_url: str = "http://localhost:8001"
    # Server-side IdP origin (code exchange / session). Compose: same as public.
    idp_internal_url: str = "http://localhost:8001"
    # This app's public origin (registered redirect_uri).
    public_url: str = "http://localhost:8002"

    # The bank's public client id at the IdP (rba_idp.client_ids.SEEDED): what
    # goes in login URLs. The internal application id never leaves the IdP.
    client_id: str = "rk_Bk7mQ2xVn9PwR4tL"
    session_cookie: str = "rba_demo_session"
    idp_timeout_seconds: float = 2.0

    # Default anonymous / home-scenario context (Demo-3 walkthrough varies the rest).
    home_country: str = "AR"
    home_asn: str = "7303"

    # Credential-stuffing walkthrough (ADR-0027): the account the presenter's
    # stand-in attacker hammers, and the address it comes from. TEST-NET-2
    # (RFC 5737) so it is never a real host.
    victim_email: str = "martin@correo.example"
    attacker_ip: str = "198.51.100.66"

    @model_validator(mode="after")
    def _cloud_is_explicit(self) -> "Settings":
        if self.deployment != "cloud":
            return self
        self.cookie_secure = True
        problems = [
            f"{name.upper()} must be an https:// URL (is {getattr(self, name)!r})"
            for name in ("idp_public_url", "public_url")
            if not getattr(self, name).startswith("https://")
            or (urlparse(getattr(self, name)).hostname or "") in LOCAL_HOSTS
        ]
        if (urlparse(self.idp_internal_url).hostname or "") in LOCAL_HOSTS:
            problems.append("IDP_INTERNAL_URL points at localhost")
        if problems:
            raise ValueError("DEPLOYMENT=cloud refuses to start:\n  - " + "\n  - ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
