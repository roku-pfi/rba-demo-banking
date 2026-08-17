"""Runtime settings (env / .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "rba-demo-banking"
    host: str = "0.0.0.0"
    port: int = 8002

    # Browser-facing IdP origin (hosted login redirect).
    idp_public_url: str = "http://localhost:8001"
    # Server-side IdP origin (code exchange / session). Compose: same as public.
    idp_internal_url: str = "http://localhost:8001"
    # This app's public origin (registered redirect_uri).
    public_url: str = "http://localhost:8002"

    application_id: str = "demo-banking-app"
    session_cookie: str = "rba_demo_session"
    idp_timeout_seconds: float = 2.0

    # Default anonymous / home-scenario context (Demo-3 walkthrough varies the rest).
    home_country: str = "AR"
    home_asn: str = "7303"


@lru_cache
def get_settings() -> Settings:
    return Settings()
