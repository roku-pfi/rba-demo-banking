"""Presenter panel (D-1, ADR-0035). Stage machinery, not product.

Never linked from the bank and never shown as part of RokuSec. It starts the
scenes the audience cannot start from their seats:

- **attackers**: the Lambdas in Tokyo, Frankfurt and São Paulo (I-6) log in to
  the bank from their region, so the IdP sees real foreign addresses;
- **impossible travel**: the one simulated scene. A signed ticket from the IdP
  (``POST /simulation/ticket``) carries the far-away country; the console marks
  the decision *simulado* (ADR-0032);
- **load**: concurrent ``/risk/evaluate`` calls so the PDP scales;
- **reset**: clear Martín's failure window, or forget his profile.

Protected by ``PRESENTER_SECRET``. Locally, with no secret, it is open; in the
cloud, with no secret, it does not exist. Without attacker URLs (local) the
attackers are stand-ins that post the region's country/ASN directly, which only
a local IdP believes.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from rba_demo_banking.config import Settings

logger = logging.getLogger(__name__)

COOKIE = "rba_presenter"


@dataclass(frozen=True)
class Region:
    id: str
    city: str
    # Local stand-in only: what the Lambda's address geolocates to in the cloud.
    country: str
    asn: str = "16509"  # Amazon


REGIONS: tuple[Region, ...] = (
    Region("ap-northeast-1", "Tokio", "JP"),
    Region("eu-central-1", "Fráncfort", "DE"),
    Region("sa-east-1", "São Paulo", "BR"),
)
REGION_BY_ID = {r.id: r for r in REGIONS}

# Impossible travel: Japan on a residential network (KDDI), so the travel rule
# fires and not the hosting-network one.
TRAVEL_COUNTRY, TRAVEL_ASN = "JP", "2516"

# Wrong passwords per region (ADR-0045 defaults: 3 failures from unfamiliar
# contexts step Martín up; 10 from one IP block that IP). A burst steps him up.
# Sustained: each region's IP passes its block and then tries the real password,
# which is refused too. Martín himself is never blocked.
STUFFING = {"burst": 1, "lockout": 10}
STUFFING_ENDS_WITH_PASSWORD = {"burst": False, "lockout": True}


def parse_attacker_urls(raw: str) -> dict[str, str]:
    """``region=url,region=url`` (what scripts/aws-up.sh writes)."""
    urls = {}
    for part in raw.split(","):
        region, _, url = part.strip().partition("=")
        if region and url:
            urls[region.strip()] = url.strip()
    return urls


# ---------------------------------------------------------------- access


def enabled(settings: Settings) -> bool:
    return bool(settings.presenter_secret) or settings.deployment != "cloud"


def _token(settings: Settings) -> str:
    return hmac.new(settings.presenter_secret.encode(), b"presenter-v1", hashlib.sha256).hexdigest()


def cookie_value(settings: Settings, secret: str) -> str | None:
    """The cookie to set for a correct secret, else ``None``."""
    if not settings.presenter_secret or not hmac.compare_digest(secret, settings.presenter_secret):
        return None
    return _token(settings)


def authorized(settings: Settings, cookie: str | None) -> bool:
    if not settings.presenter_secret:
        return settings.deployment != "cloud"
    return bool(cookie) and hmac.compare_digest(cookie, _token(settings))


# ---------------------------------------------------------------- attackers


class Attackers:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._urls = parse_attacker_urls(settings.attacker_urls)

    @property
    def real(self) -> bool:
        return bool(self._urls)

    def run(self, region: Region, passwords: list[str]) -> dict:
        """One region's attack: what the IdP said to each attempt."""
        url = self._urls.get(region.id)
        try:
            out = self._lambda(url, passwords) if url else self._stand_in(region, passwords)
        except httpx.HTTPError as exc:
            logger.warning("attacker %s failed: %s", region.id, exc)
            out = {"attempts": [], "error": "sin respuesta"}
        return {"region": region.id, "city": region.city, "real": bool(url), **out}

    def _lambda(self, url: str, passwords: list[str]) -> dict:
        resp = httpx.post(
            url,
            json={
                "client_id": self._settings.client_id,
                "email": self._settings.victim_email,
                "passwords": passwords,
                "pause_ms": 300,
            },
            headers={"X-RokuSec-Attacker-Secret": self._settings.attacker_secret},
            timeout=130,
        )
        if resp.status_code != 200:
            return {"attempts": [], "error": f"HTTP {resp.status_code}"}
        data = resp.json()
        return {"egress_ip": data.get("egress_ip"), "attempts": data.get("attempts", [])}

    def _stand_in(self, region: Region, passwords: list[str]) -> dict:
        base = self._settings.idp_internal_url.rstrip("/")
        attempts = []
        for password in passwords:
            resp = httpx.post(
                f"{base}/login",
                json={
                    "email": self._settings.victim_email,
                    "password": password,
                    "client_id": self._settings.client_id,
                    "ip_address": self._settings.attacker_ip,
                    "country": region.country,
                    "asn": region.asn,
                    # As the Lambdas: the most common desktop browser (ADR-0043).
                    "device_type": "desktop",
                    "os": "Windows",
                    "browser": "Chrome",
                },
                # Parallel attempts queue behind password hashing; the
                # bank's 2 s IdP timeout is for its own users, not for this.
                timeout=15,
            )
            try:
                outcome = resp.json().get("outcome", f"HTTP_{resp.status_code}")
            except ValueError:
                outcome = f"HTTP_{resp.status_code}"
            attempts.append({"status": resp.status_code, "outcome": outcome})
        return {"egress_ip": self._settings.attacker_ip, "attempts": attempts}

    def tokyo(self) -> list[dict]:
        """Martín's real password from Tokyo. The attacker stops at the passkey."""
        return [self.run(REGION_BY_ID["ap-northeast-1"], [self._settings.victim_password])]

    def stuffing(self, per_region: int, *, then_right: bool = False) -> list[dict]:
        """Wrong passwords from all three regions at once; optionally the real one last."""
        common = ("123456", "qwerty", "martin2024", "password", "111111",
                  "abc123", "123456789", "iloveyou", "admin", "letmein")
        passwords = [f"{common[i % len(common)]}-{uuid.uuid4().hex[:6]}" for i in range(per_region)]
        if then_right:
            passwords.append(self._settings.victim_password)
        with ThreadPoolExecutor(len(REGIONS)) as pool:
            return list(pool.map(lambda r: self.run(r, passwords), REGIONS))


# ---------------------------------------------------------------- travel


def travel_ticket(settings: Settings) -> str | None:
    """A signed ticket for the far-away login, or ``None`` (local: no secret)."""
    if not settings.simulation_secret:
        return None
    resp = httpx.post(
        f"{settings.idp_internal_url.rstrip('/')}/simulation/ticket",
        json={"country": TRAVEL_COUNTRY, "asn": TRAVEL_ASN},
        headers={"X-RokuSec-Simulation-Secret": settings.simulation_secret},
        timeout=settings.idp_timeout_seconds,
    )
    resp.raise_for_status()
    return resp.json()["ticket"]


def travel_login_url(settings: Settings, ticket: str | None) -> str:
    callback = f"{settings.public_url.rstrip('/')}/callback"
    params = {"client_id": settings.client_id, "redirect_uri": callback}
    if ticket:
        params["simulation_ticket"] = ticket
    else:
        # A local IdP trusts client-reported signals.
        params["country"], params["asn"] = TRAVEL_COUNTRY, TRAVEL_ASN
    return f"{settings.idp_public_url.rstrip('/')}/login?{urlencode(params)}"


# ---------------------------------------------------------------- reset


def reset(settings: Settings, mode: str) -> dict:
    """``failures``: empty the failure window, keep the history.
    ``profile``: forget the profile; the next login is a first login."""
    if not settings.redis_url:
        return {"done": False, "error": "sin REDIS_URL"}
    import redis  # only the panel needs it

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=3)
    # Both modes lift the login guard's blocks and counters (ADR-0045).
    for key in client.scan_iter(match="rba:guard:*"):
        client.delete(key)
    touched = []
    for user_id in [u.strip() for u in settings.reset_user_ids.split(",") if u.strip()]:
        key = f"{settings.profile_key_prefix}{user_id}"
        if mode == "profile":
            if client.delete(key):
                touched.append(user_id)
            continue
        raw = client.get(key)
        if raw is None:
            continue
        blob = json.loads(raw)
        if blob.get("failed_login_ts"):
            blob["failed_login_ts"] = []
            client.set(key, json.dumps(blob))
            touched.append(user_id)
    return {"done": True, "mode": mode, "users": touched}


# ---------------------------------------------------------------- load


@dataclass
class LoadRun:
    """Concurrent ``POST /risk/evaluate`` for a while, in a background thread."""

    running: bool = False
    started_at: float = 0.0
    seconds: int = 0
    sent: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def start(self, settings: Settings) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running, self.started_at = True, time.time()
            self.seconds = settings.load_seconds
            self.sent = self.errors = 0
            self.latencies_ms = []
        threading.Thread(target=lambda: asyncio.run(self._run(settings)), daemon=True).start()
        return True

    async def _run(self, settings: Settings) -> None:
        deadline = time.monotonic() + settings.load_seconds
        url = f"{settings.pdp_url.rstrip('/')}/risk/evaluate"
        limits = httpx.Limits(max_connections=settings.load_concurrency)

        async def worker(client: httpx.AsyncClient, n: int) -> None:
            while time.monotonic() < deadline:
                started = time.monotonic()
                try:
                    resp = await client.post(url, json=_evaluation(n))
                    ok = resp.status_code == 200
                except httpx.HTTPError:
                    ok = False
                with self._lock:
                    self.sent += 1
                    if ok:
                        self.latencies_ms.append((time.monotonic() - started) * 1000)
                    else:
                        self.errors += 1

        try:
            async with httpx.AsyncClient(timeout=10, limits=limits) as client:
                await asyncio.gather(*(worker(client, n) for n in range(settings.load_concurrency)))
        finally:
            with self._lock:
                self.running = False

    def snapshot(self) -> dict:
        with self._lock:
            lat = sorted(self.latencies_ms)
            elapsed = (time.time() - self.started_at) if self.started_at else 0
            return {
                "running": self.running,
                "elapsed": round(min(elapsed, self.seconds or elapsed)),
                "seconds": self.seconds,
                "sent": self.sent,
                "errors": self.errors,
                "rps": round(self.sent / elapsed) if elapsed else 0,
                "p50_ms": round(statistics.median(lat)) if lat else None,
                "p95_ms": round(lat[int(len(lat) * 0.95) - 1]) if len(lat) >= 20 else None,
            }


def _evaluation(n: int) -> dict:
    """A plausible login for one of 80 load users, with a fresh event id so the PDP scores it."""
    return {
        "event_id": str(uuid.uuid4()),
        "tenant_id": "roku-bank",
        "application_id": "roku-bank-web",
        "user_id": f"load-user-{(n * 7 + int(time.time() * 1000)) % 80}",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ip_address": f"203.0.113.{1 + n % 79}",
        "asn": "7303",
        "country": "AR",
        "device_type": "mobile" if n % 2 else "desktop",
        "os": ("Android", "iOS", "Windows", "macOS")[n % 4],
        "browser": ("Chrome", "Safari", "Firefox")[n % 3],
        "login_successful": True,
    }
