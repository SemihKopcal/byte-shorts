"""
Guvenlik katmani. Panelin kimligi Cloudflare Access'ten gelir; uygulama ayrica
KENDISI dogrular (savunma derinligi): tunel disi bir yoldan istek gelse bile
gecerli bir Access JWT'si yoksa 403.

  - JWT: yalniz RS256, imza + exp/iat + aud + iss zorunlu, e-posta izin listesinde
  - CSRF: Origin tam eslesmeli + form belirteci (HMAC, gunluk)
  - Basliklar: sert CSP, nosniff, Referrer-Policy same-origin, frame yasak, HSTS
  - Hiz siniri: yazma islemleri icin kisi basina dakikada N
"""
from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

import jwt


class AccessError(Exception):
    pass


MAX_TOKEN = 8192


def default_fetch_jwks(team_domain: str) -> dict:
    import httpx
    r = httpx.get(f"https://{team_domain}/cdn-cgi/access/certs", timeout=5.0,
                  follow_redirects=False)
    if r.status_code != 200:
        raise AccessError(f"JWKS HTTP {r.status_code}")
    return r.json()


class CfAccess:
    def __init__(self, team_domain: str, aud: str, allowed_emails, fetch_jwks=None,
                 clock=time.time, ttl: int = 3600, refetch_min: int = 300):
        self.team, self.aud, self.allowed = team_domain, aud, frozenset(allowed_emails)
        self._fetch = fetch_jwks or (lambda: default_fetch_jwks(team_domain))
        self._clock, self._ttl, self._refetch_min = clock, ttl, refetch_min
        self._keys: dict[str, object] = {}
        self._loaded = 0.0
        self._last_try = 0.0

    def _load(self) -> None:
        self._last_try = self._clock()
        try:
            doc = self._fetch()
            keys = {}
            for k in doc.get("keys", []):
                if k.get("kty") == "RSA" and k.get("kid"):
                    keys[k["kid"]] = jwt.PyJWK.from_dict(k).key
        except Exception:
            raise AccessError("anahtarlar alinamadi") from None
        if not keys:
            raise AccessError("anahtar listesi bos")
        self._keys, self._loaded = keys, self._clock()

    def _key_for(self, kid: str):
        now = self._clock()
        if not self._keys or now - self._loaded > self._ttl:
            self._load()
        if kid not in self._keys and now - self._last_try >= self._refetch_min:
            self._load()                     # anahtar donmus olabilir; sinirli sikilikta tazele
        if kid not in self._keys:
            raise AccessError("bilinmeyen anahtar")
        return self._keys[kid]

    def verify(self, token: str) -> str:
        """Gecerliyse izinli e-postayi doner; degilse AccessError."""
        if not token or len(token) > MAX_TOKEN:
            raise AccessError("belirteç yok ya da cok buyuk")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AccessError("belirteç okunamadi") from None
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise AccessError("alg/kid gecersiz")
        key = self._key_for(header["kid"])
        try:
            claims = jwt.decode(
                token, key, algorithms=["RS256"], audience=self.aud,
                issuer=f"https://{self.team}", leeway=30,
                options={"require": ["exp", "iat", "aud", "iss"]})
        except jwt.PyJWTError:
            raise AccessError("belirteç gecersiz") from None
        email = claims.get("email")
        if not isinstance(email, str) or email.strip().lower() not in self.allowed:
            raise AccessError("e-posta izinli degil")
        return email.strip().lower()


# ── CSRF ─────────────────────────────────────────────────────────────
def _csrf(secret: bytes, actor: str, day: int) -> str:
    return hmac.new(secret, f"csrf|{actor}|{day}".encode(), "sha256").hexdigest()[:40]


def csrf_token(secret: bytes, actor: str, now: float | None = None) -> str:
    return _csrf(secret, actor, int((now or time.time()) // 86400))


def csrf_ok(secret: bytes, actor: str, token: str, now: float | None = None) -> bool:
    day = int((now or time.time()) // 86400)
    return any(hmac.compare_digest(token or "", _csrf(secret, actor, d)) for d in (day, day - 1))


def origin_ok(allowed_origin: str, headers) -> bool:
    """Durum degistiren isteklerde Origin (yoksa Referer) panelin kendi adresi olmali."""
    origin = headers.get("origin")
    if origin:
        return origin == allowed_origin
    ref = headers.get("referer")
    if ref:
        p = urlparse(ref)
        return f"{p.scheme}://{p.netloc}" == allowed_origin
    return False


# ── basliklar ────────────────────────────────────────────────────────
def security_headers(media_host: str, https: bool = True) -> dict:
    h = {
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            f"media-src {media_host}; connect-src 'self'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'; object-src 'none'"),
        "X-Content-Type-Options": "nosniff",
        # no-referrer OLMAZ: tarayici ayni siteye form gonderirken bile "Origin: null" yollar,
        # origin_ok bunu (dogru olarak) reddeder ve panelde hicbir dugme calismaz.
        # same-origin: ayni siteye Origin/Referer gider, baska siteye hicbir sey gitmez.
        "Referrer-Policy": "same-origin",
        "X-Frame-Options": "DENY",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "Cache-Control": "no-store",
    }
    if https:
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return h


# ── hiz siniri ───────────────────────────────────────────────────────
class RateLimiter:
    def __init__(self, limit: int = 40, window: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self._clock()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
