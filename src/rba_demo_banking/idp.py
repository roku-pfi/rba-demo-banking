"""IdP client used by the bank. Talks to the PEP only — never the PDP."""

from __future__ import annotations

from rba_contracts import CallbackTokenRequest, CallbackTokenResponse, SessionResponse, StoppedAttempt

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
    def change_password(self, token: str, current: str, new: str) -> int: ...


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

    def change_password(self, token: str, current: str, new: str) -> int:
        """The IdP's status: 204 done, 403 wrong current password, 422 rejected."""
        try:
            resp = httpx.post(
                f"{self._base}/account/password",
                json={"current_password": current, "new_password": new},
                headers=self._auth(token),
                timeout=max(self._timeout, 5.0),  # two password hashes
            )
        except httpx.HTTPError as exc:
            raise IdpError("IdP unavailable") from exc
        return resp.status_code
