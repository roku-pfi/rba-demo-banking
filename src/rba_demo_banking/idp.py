"""IdP client used by the bank. Talks to the PEP only — never the PDP."""

from __future__ import annotations

from rba_contracts import CallbackTokenRequest, CallbackTokenResponse, SessionResponse

import httpx

from rba_demo_banking.config import Settings


class IdpError(Exception):
    """IdP refused the callback or session call."""


class IdpClient:
    def exchange(self, code: str) -> CallbackTokenResponse: ...
    def get_session(self, token: str) -> SessionResponse: ...
    def logout(self, token: str) -> None: ...
    def failed_attempt(self, email: str, *, country: str, asn: str) -> None: ...


class HttpIdpClient(IdpClient):
    def __init__(self, settings: Settings) -> None:
        self._base = settings.idp_internal_url.rstrip("/")
        self._timeout = settings.idp_timeout_seconds
        self._application_id = settings.application_id
        self._attacker_ip = settings.attacker_ip

    def exchange(self, code: str) -> CallbackTokenResponse:
        try:
            resp = httpx.post(
                f"{self._base}/callback/token",
                json=CallbackTokenRequest(code=code).model_dump(),
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise IdpError("IdP unavailable") from exc
        if resp.status_code != 200:
            raise IdpError("unknown or expired code")
        return CallbackTokenResponse.model_validate(resp.json())

    def get_session(self, token: str) -> SessionResponse:
        try:
            resp = httpx.get(
                f"{self._base}/session",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise IdpError("IdP unavailable") from exc
        if resp.status_code != 200:
            raise IdpError("missing or expired session")
        return SessionResponse.model_validate(resp.json())

    def logout(self, token: str) -> None:
        try:
            httpx.post(
                f"{self._base}/logout",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            return

    def failed_attempt(self, email: str, *, country: str, asn: str) -> None:
        """One wrong-password attempt, for the credential-stuffing walkthrough.

        This is the presenter kit standing in for the attacker — the only place
        in the demo that deliberately submits a bad password. It goes through
        the ordinary `POST /login`, so the IdP records it exactly as it would a
        real one (ADR-0027); nothing here talks to the PDP.
        """
        try:
            httpx.post(
                f"{self._base}/login",
                json={
                    "email": email,
                    "password": "not-the-password",
                    "application_id": self._application_id,
                    "ip_address": self._attacker_ip,
                    "country": country,
                    "asn": asn,
                    "device_type": "desktop",
                    "os": "Linux",
                    "browser": "Chrome",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            return
