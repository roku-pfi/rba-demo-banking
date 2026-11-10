"""IdP client used by the bank. Talks to the PEP only — never the PDP."""

from __future__ import annotations

from rba_contracts import AccountLinkResponse, CallbackTokenRequest, CallbackTokenResponse, SessionResponse, StoppedAttempt

import httpx

from rba_demo_banking.config import Settings


class IdpError(Exception):
    """IdP refused the callback or session call."""


class IdpClient:
    def exchange(self, code: str) -> CallbackTokenResponse: ...
    def get_session(self, token: str) -> SessionResponse: ...
    def logout(self, token: str) -> None: ...
    def attempts(self, token: str) -> list[StoppedAttempt]: ...
    def dismiss_attempts(self, token: str, up_to: str) -> None: ...
    def password_link(self, token: str, return_to: str) -> str: ...


class HttpIdpClient(IdpClient):
    def __init__(self, settings: Settings) -> None:
        self._base = settings.idp_internal_url.rstrip("/")
        self._timeout = settings.idp_timeout_seconds
        self._client_id = settings.client_id

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

    def _auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def attempts(self, token: str) -> list[StoppedAttempt]:
        """Someone got this user's password right and was stopped (contracts 0.22.0)."""
        try:
            resp = httpx.get(f"{self._base}/session/attempts", headers=self._auth(token), timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise IdpError("IdP unavailable") from exc
        if resp.status_code != 200:
            raise IdpError("missing or expired session")
        return [StoppedAttempt.model_validate(item) for item in resp.json()]

    def dismiss_attempts(self, token: str, up_to: str) -> None:
        try:
            httpx.post(
                f"{self._base}/session/attempts/seen",
                params={"up_to": up_to},
                headers=self._auth(token),
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise IdpError("IdP unavailable") from exc

    def password_link(self, token: str, return_to: str) -> str:
        """A one-time path on the IdP to its password page (contracts 0.25.0).

        The change is confirmed with the passkey, which belongs to the IdP's
        domain; in the cloud that is not the bank's, so it happens there.
        """
        try:
            resp = httpx.post(
                f"{self._base}/account/password/link",
                json={"return_to": return_to},
                headers=self._auth(token),
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise IdpError("IdP unavailable") from exc
        if resp.status_code != 200:
            raise IdpError(f"no password link ({resp.status_code})")
        return AccountLinkResponse.model_validate(resp.json()).path
