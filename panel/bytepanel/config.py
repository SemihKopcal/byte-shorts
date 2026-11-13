"""
Ayarlar. TUM sirlar ortamdan ya da Docker secret dosyasindan (`NAME_FILE`)
gelir; kodda, imajda, repoda sir yok.

Fail-closed: prod'da bir sey eksikse ya da bicimi bozuksa uygulama ACILMAZ
(yarim guvenlikle calismaktansa durur).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

PLATFORMS = ("youtube", "instagram", "tiktok")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}\Z")      # script_id: R2 anahtarlarinin tek kaynagi
HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+\Z")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    env: str                       # prod | dev | test
    db_path: str
    origin: str                    # https://byte.semihkopcal.com (CSRF/Origin kontrolu)
    r2_endpoint: str
    r2_bucket: str
    r2_access_key_id: str
    r2_secret_access_key: str
    gh_repo: str                   # sahip/depo
    gh_token: str
    gh_workflow: str
    gh_ref: str
    cf_team_domain: str            # takim.cloudflareaccess.com
    cf_aud: str
    allowed_emails: frozenset
    csrf_secret: bytes
    dev_user: str
    max_dispatch_per_hour: int
    dispatch_timeout_min: int
    gh_scripts_workflow: str = "panel-scripts.yml"      # senaryo ekle / one al / sil (tools/panel_scripts.py)

    @property
    def media_host(self) -> str:
        """CSP media-src icin R2 uc noktasinin kaynagi."""
        p = urlparse(self.r2_endpoint)
        return f"{p.scheme}://{p.netloc}"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


def _read(env, name: str, required: bool = True, default: str = "") -> str:
    """NAME_FILE (Docker secret) once, sonra NAME."""
    path = env.get(f"{name}_FILE", "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                val = f.read().strip()
        except OSError as e:
            raise ConfigError(f"{name}_FILE okunamadi: {e}") from None
    else:
        val = env.get(name, "").strip()
    if not val:
        if required:                      # prod'da varsayilan YOK: eksikse acilmaz
            raise ConfigError(f"{name} (ya da {name}_FILE) tanimli degil")
        val = default
    return val


def _int(env, name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name, "").strip()
    try:
        v = int(raw) if raw else default
    except ValueError:
        raise ConfigError(f"{name} sayi olmali") from None
    if not lo <= v <= hi:
        raise ConfigError(f"{name} {lo}..{hi} araliginda olmali")
    return v


def load(env=None) -> Config:
    env = os.environ if env is None else env
    mode = env.get("PANEL_ENV", "prod").strip() or "prod"
    if mode not in ("prod", "dev", "test"):
        raise ConfigError("PANEL_ENV prod|dev|test olmali")
    prod = mode == "prod"

    origin = _read(env, "PANEL_ORIGIN", required=prod, default="http://localhost:8000")
    if prod and not (origin.startswith("https://") and origin == origin.rstrip("/")
                     and urlparse(origin).path == ""):
        raise ConfigError("PANEL_ORIGIN prod'da https://alan.adi biciminde olmali (sonda / yok)")

    endpoint = _read(env, "R2_ENDPOINT", required=prod, default="https://example.r2.cloudflarestorage.com")
    if not endpoint.startswith("https://"):
        raise ConfigError("R2_ENDPOINT https:// ile baslamali")

    repo = _read(env, "GITHUB_REPO", required=prod, default="owner/repo")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ConfigError("GITHUB_REPO sahip/depo biciminde olmali")

    team = _read(env, "CF_ACCESS_TEAM_DOMAIN", required=prod, default="team.cloudflareaccess.com").lower()
    if not HOST.match(team) or not team.endswith(".cloudflareaccess.com"):
        raise ConfigError("CF_ACCESS_TEAM_DOMAIN '<takim>.cloudflareaccess.com' olmali")

    emails = frozenset(e.strip().lower()
                       for e in _read(env, "PANEL_ALLOWED_EMAILS", required=prod,
                                      default="dev@localhost").split(",") if e.strip())
    if prod and not emails:
        raise ConfigError("PANEL_ALLOWED_EMAILS bos")
    if any("@" not in e or " " in e for e in emails):
        raise ConfigError("PANEL_ALLOWED_EMAILS gecersiz adres iceriyor")

    csrf = _read(env, "PANEL_CSRF_SECRET", required=prod, default="dev-only-not-secret")
    if prod and len(csrf) < 32:
        raise ConfigError("PANEL_CSRF_SECRET en az 32 karakter olmali (openssl rand -hex 32)")

    dev_user = env.get("PANEL_DEV_USER", "").strip().lower()
    if dev_user and mode == "prod":
        raise ConfigError("PANEL_DEV_USER prod'da tanimli olamaz")

    return Config(
        env=mode,
        db_path=env.get("PANEL_DB", "/data/panel.db"),
        origin=origin,
        r2_endpoint=endpoint,
        r2_bucket=_read(env, "R2_BUCKET", required=prod, default="byte-videos"),
        r2_access_key_id=_read(env, "R2_ACCESS_KEY_ID", required=prod, default="x"),
        r2_secret_access_key=_read(env, "R2_SECRET_ACCESS_KEY", required=prod, default="x"),
        gh_repo=repo,
        gh_token=_read(env, "GITHUB_TOKEN", required=prod, default="x"),
        gh_workflow=env.get("GITHUB_WORKFLOW", "panel-publish.yml").strip(),
        gh_ref=env.get("GITHUB_REF_NAME", "main").strip(),
        cf_team_domain=team,
        cf_aud=_read(env, "CF_ACCESS_AUD", required=prod, default="dev-aud"),
        allowed_emails=emails,
        csrf_secret=csrf.encode(),
        dev_user=dev_user,
        max_dispatch_per_hour=_int(env, "PANEL_MAX_DISPATCH_PER_HOUR", 12, 1, 100),
        dispatch_timeout_min=_int(env, "PANEL_DISPATCH_TIMEOUT_MIN", 45, 5, 360),
        gh_scripts_workflow=env.get("GITHUB_SCRIPTS_WORKFLOW", "panel-scripts.yml").strip(),
    )
