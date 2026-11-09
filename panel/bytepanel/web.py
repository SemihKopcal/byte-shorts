"""
Web arayuzu. Her rota kimlik ister (yalniz /healthz haric, o da bos bir 'ok').
Durum degistiren her istek: gecerli Access JWT + Origin eslesmesi + CSRF belirteci
+ hiz siniri. Sablonlar otomatik kacisli; kullanici girdisi HTML'e ham girmez.
"""
from __future__ import annotations

import base64
import contextlib
import logging
import re
import threading
from collections import namedtuple
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import config as cfgmod
from . import plan
from .config import PLATFORMS, SLUG
from .db import Db, iso, parse_iso
from .github import GitHub
from .health import HealthMonitor, overall
from .security import (AccessError, CfAccess, RateLimiter, csrf_ok, csrf_token, origin_ok,
                       security_headers)
from .service import DEFAULTS, Invalid, Service
from .storage import make_s3

log = logging.getLogger("bytepanel")
HERE = Path(__file__).parent
Actor = namedtuple("Actor", "email ip")
MAX_BODY = 64 * 1024
TR = plan.TR                                  # Turkiye: sabit UTC+3 (yaz saati yok)


class LimitBody:
    """ASGI duzeyinde govde siniri (chunked istekler dahil)."""

    def __init__(self, app, limit=MAX_BODY):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope["headers"]:
            if k == b"content-length" and v.isdigit() and int(v) > self.limit:
                return await self._too_big(send)
        seen = 0

        async def guarded():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.limit:
                    raise _TooBig()
            return msg
        try:
            await self.app(scope, guarded, send)
        except _TooBig:
            await self._too_big(send)

    @staticmethod
    async def _too_big(send):
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"too large"})


class _TooBig(Exception):
    pass


def fmt_ts(ts) -> str:
    if not ts:
        return "—"
    d = parse_iso(ts)
    return f"{d:%d.%m %H:%M} UTC · TR {d.astimezone(TR):%H:%M}"


def tr_input(ts) -> str:
    """ISO UTC -> 'YYYY-AA-GG SS:DD' (Turkiye): 'Tasi' kutusunun on degeri."""
    return f"{parse_iso(ts).astimezone(TR):%Y-%m-%d %H:%M}" if ts else ""


def build_service(cfg) -> Service:
    db = Db(cfg.db_path)
    gh = GitHub(cfg.gh_repo, cfg.gh_token, cfg.gh_workflow, cfg.gh_ref)
    return Service(db, make_s3(cfg), gh, cfg)


def create_app(cfg=None, *, service=None, access=None, monitor=None, start_worker=None) -> FastAPI:
    cfg = cfg or cfgmod.load()
    svc = service or build_service(cfg)
    access = access or CfAccess(cfg.cf_team_domain, cfg.cf_aud, cfg.allowed_emails)
    monitor = monitor or HealthMonitor(svc)
    limiter = RateLimiter()
    headers = security_headers(cfg.media_host, https=cfg.is_prod or cfg.origin.startswith("https://"))
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["ts"] = fmt_ts
    templates.env.filters["trin"] = tr_input
    css = (HERE / "static" / "app.css").read_bytes()
    js = (HERE / "static" / "app.js").read_bytes()
    stop = threading.Event()
    if start_worker is None:
        start_worker = cfg.is_prod

    def worker():
        n = 0
        while not stop.wait(30):
            try:
                svc.tick()
                n += 1
                if n % 2 == 1:
                    monitor.refresh()
            except Exception:                                    # dongu asla olmesin
                log.exception("tick hatasi")

    @contextlib.asynccontextmanager
    async def lifespan(app):
        t = None
        if start_worker:
            t = threading.Thread(target=worker, name="panel-worker", daemon=True)
            t.start()
        yield
        stop.set()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LimitBody)

    @app.middleware("http")
    async def add_headers(request: Request, call_next):
        resp = await call_next(request)
        for k, v in headers.items():
            resp.headers[k] = v
        return resp

    # ── kimlik ───────────────────────────────────────────────────────
    class Deny(Exception):
        pass

    @app.exception_handler(Deny)
    async def deny(request, exc):
        return PlainTextResponse("forbidden", status_code=403)

    def client_ip(request: Request) -> str:
        return (request.headers.get("cf-connecting-ip") or
                (request.client.host if request.client else ""))[:64]

    def authenticate(request: Request) -> Actor:
        ip = client_ip(request)
        token = request.headers.get("cf-access-jwt-assertion", "")
        if cfg.dev_user and not cfg.is_prod:
            # Yerel deneme: Cloudflare uzerinden gelen hicbir istege dev kimligi verilmez
            if token or any(h in request.headers for h in ("cf-ray", "cf-connecting-ip")):
                raise Deny()
            return Actor(cfg.dev_user, ip)
        try:
            return Actor(access.verify(token), ip)
        except AccessError:
            raise Deny() from None

    async def guarded_post(request: Request):
        """Kimlik + Origin + CSRF + hiz siniri; (actor, form) doner."""
        actor = authenticate(request)
        if not origin_ok(cfg.origin, request.headers):
            raise Deny()
        form = await request.form()
        if not csrf_ok(cfg.csrf_secret, actor.email, str(form.get("csrf", ""))):
            raise Deny()
        if not limiter.allow(actor.email):
            raise _RateLimited()
        return actor, form

    class _RateLimited(Exception):
        pass

    @app.exception_handler(_RateLimited)
    async def limited(request, exc):
        return PlainTextResponse("too many requests", status_code=429)

    # ── yardimcilar ──────────────────────────────────────────────────
    def render(request, actor, name, **ctx):
        flash = request.cookies.get("flash", "")
        try:
            flash = base64.urlsafe_b64decode(flash.encode()).decode()[:300] if flash else ""
        except Exception:
            flash = ""
        resp = templates.TemplateResponse(
            request, name,
            {"actor": actor, "csrf": csrf_token(cfg.csrf_secret, actor.email), "flash": flash,
             "platforms": PLATFORMS, "settings": svc.settings(), "now": iso(svc.now()), **ctx})
        if flash:
            resp.delete_cookie("flash", path="/")
        return resp

    def go(path: str, msg: str = "") -> Response:
        r = RedirectResponse(path, status_code=303)
        if msg:
            r.set_cookie("flash", base64.urlsafe_b64encode(msg[:300].encode()).decode(),
                         max_age=30, httponly=True, samesite="strict", secure=cfg.is_prod, path="/")
        return r

    def sid_or_404(sid: str) -> str:
        if not SLUG.match(sid):
            raise Invalid("video bulunamadi")
        return sid

    async def act(request, back, fn, ok_msg, sid=None):
        actor, form = await guarded_post(request)
        if sid is not None and not SLUG.match(sid):          # yonlendirme adresine girmeden once
            return PlainTextResponse("not found", status_code=404)
        try:
            fn(actor, form)
            return go(back, ok_msg)
        except Invalid as e:
            return go(back, f"Hata: {e}")

    def cal_back(form) -> str:
        """Takvim islemlerinden sonra donulecek adres: formdan gelen deger YENIDEN INSA edilir
        (regex'ten gecen parcalardan), ham metin hic yonlendirmeye girmez."""
        m = plan.MONTH_RX.match(str(form.get("m", "")))
        if m:
            return f"/calendar?m={m[1]}-{m[2]}"
        m = plan.DAY_RX.match(str(form.get("d", "")))
        if m:
            return f"/calendar?d={m[1]}-{m[2]}-{m[3]}"
        return "/calendar?view=list" if form.get("view") == "list" else "/calendar"

    async def act_cal(request, do, ok_msg):
        """do(actor, form) bir mesaj dondurebilir (yoksa ok_msg)."""
        actor, form = await guarded_post(request)
        back = cal_back(form)
        try:
            return go(back, do(actor, form) or ok_msg)
        except Invalid as e:
            return go(back, f"Hata: {e}")

    def need_int(form, key: str) -> int:
        v = str(form.get(key, ""))
        if not re.fullmatch(r"[0-9]{1,9}", v):          # str.isdigit() "²" gibi karakterleri de kabul eder
            raise Invalid("gecersiz kayit")
        return int(v)

    def need_day(form, key: str = "d"):
        try:
            d = plan.parse_day(str(form.get(key, "")))
            plan.parse_month(f"{d:%Y-%m}", plan.to_tr(svc.now()).date())     # +-3 yil siniri
            return d
        except ValueError as e:
            raise Invalid(str(e)) from None

    # ── sayfalar ─────────────────────────────────────────────────────
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    @app.get("/static/app.css", include_in_schema=False)
    async def css_(request: Request):
        authenticate(request)
        return Response(css, media_type="text/css")

    @app.get("/static/app.js", include_in_schema=False)
    async def js_(request: Request):
        authenticate(request)
        return Response(js, media_type="text/javascript")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home(request: Request):
        actor = authenticate(request)
        checks = monitor.cached()
        pending = [v for v in svc.videos(200) if v["approval"] == "pending" and not v["files_deleted_at"]][:5]
        return render(request, actor, "home.html", counts=svc.counts(), checks=checks,
                      status=overall(checks) if checks else "unknown", pending=pending,
                      upcoming=svc.upcoming(5), recent=svc.recent_results(5), errors=svc.last_errors)

    @app.get("/videos", response_class=HTMLResponse, include_in_schema=False)
    async def videos(request: Request):
        actor = authenticate(request)
        rows = []
        for v in svc.videos(300):
            pubs = {p["platform"]: p for p in svc.publications(v["script_id"])}
            rows.append({"v": v, "pubs": pubs})
        return render(request, actor, "videos.html", rows=rows)

    @app.get("/videos/{sid}", response_class=HTMLResponse, include_in_schema=False)
    async def video(request: Request, sid: str):
        actor = authenticate(request)
        try:
            v = svc.video(sid_or_404(sid))
        except Invalid:
            return PlainTextResponse("not found", status_code=404)
        pubs = {p["platform"]: p for p in svc.publications(sid)}
        return render(request, actor, "video.html", v=v, pubs=pubs)

    @app.get("/videos/{sid}/preview", include_in_schema=False)
    async def preview(request: Request, sid: str):
        authenticate(request)
        try:
            return JSONResponse({"url": svc.preview_url(sid_or_404(sid))})
        except Invalid as e:
            return JSONResponse({"error": str(e)}, status_code=404)

    @app.post("/videos/{sid}/approve", include_in_schema=False)
    async def approve(request: Request, sid: str):
        return await act(request, f"/videos/{sid}",
                         lambda a, f: svc.approve(sid_or_404(sid), a.email, a.ip), "Onaylandi, takvime eklendi.", sid=sid)

    @app.post("/videos/{sid}/reject", include_in_schema=False)
    async def reject(request: Request, sid: str):
        return await act(request, f"/videos/{sid}",
                         lambda a, f: svc.reject(sid_or_404(sid), a.email, a.ip), "Reddedildi.", sid=sid)

    @app.post("/videos/{sid}/unapprove", include_in_schema=False)
    async def unapprove(request: Request, sid: str):
        return await act(request, f"/videos/{sid}",
                         lambda a, f: svc.unapprove(sid_or_404(sid), a.email, a.ip), "Onay geri alindi.", sid=sid)

    @app.post("/videos/{sid}/plan", include_in_schema=False)
    async def plan_video(request: Request, sid: str):
        return await act(request, f"/videos/{sid}",
                         lambda a, f: svc.plan_platform(sid_or_404(sid), str(f.get("platform", "")),
                                                        a.email, a.ip), "Yayin planlandi.", sid=sid)

    @app.post("/approve-all", include_in_schema=False)
    async def approve_all(request: Request):
        actor, _ = await guarded_post(request)
        n = svc.approve_all_pending(actor.email, actor.ip)
        return go("/", f"{n} video onaylandi.")

    @app.get("/calendar", response_class=HTMLResponse, include_in_schema=False)
    async def calendar(request: Request):
        actor = authenticate(request)
        q = request.query_params
        if q.get("view") == "list":
            return render(request, actor, "calendar_list.html", upcoming=svc.upcoming(200),
                          recent=svc.recent_results(30))
        today = plan.to_tr(svc.now()).date()
        try:
            if q.get("d"):
                day = plan.parse_day(q["d"])
                plan.parse_month(f"{day:%Y-%m}", today)
            else:
                y, mo = plan.parse_month(q.get("m"), today)
        except ValueError as e:
            return go("/calendar", f"Hata: {e}")
        extras = await run_in_threadpool(svc.extras)          # GitHub istegi: olay dongusunu tutma
        if q.get("d"):
            return render(request, actor, "calendar_day.html", d=svc.day_model(day, extras),
                          extras=extras)
        return render(request, actor, "calendar.html", mm=svc.month_model(y, mo, extras),
                      qs=svc.queue_summary(extras), extras=extras, unplanned=svc.autofill_count(),
                      week=svc.week_rows(), week_set=svc.week() is not None, today_iso=today.isoformat())

    @app.post("/calendar/plan", include_in_schema=False)
    async def cal_plan(request: Request):
        def do(a, f):
            sid, _, pf = str(f.get("choice", "")).partition(":")
            if not SLUG.match(sid):
                raise Invalid("video secilmedi")
            try:
                when = plan.tr_to_utc(need_day(f), str(f.get("time", "")).strip())
            except ValueError as e:
                raise Invalid(str(e)) from None
            svc.plan_at(sid, pf, when, a.email, a.ip)
        return await act_cal(request, lambda a, f: do(a, f), "Takvime eklendi.")

    @app.post("/calendar/move", include_in_schema=False)
    async def cal_move(request: Request):
        return await act_cal(request, lambda a, f: svc.move_pub(need_int(f, "pub"), need_day(f),
                                                                 a.email, a.ip), "Yayin tasindi.")

    @app.post("/calendar/autofill", include_in_schema=False)
    async def cal_autofill(request: Request):
        def do(a, f):
            n = svc.autofill(a.email, a.ip)
            return f"{n} yayin bos saatlere dizildi." if n else "Dizilecek video yok."
        return await act_cal(request, do, "")

    @app.post("/calendar/template", include_in_schema=False)
    async def cal_template(request: Request):
        def do(a, f):
            if f.get("clear") == "1":
                value = ""
            else:
                parts = [str(f.get(f"d{i}", "")).strip() for i in range(7)]
                if any("|" in x for x in parts):
                    raise Invalid("Saatlerde '|' kullanilamaz")
                value = "|".join(parts)
            svc.set_setting("week_tr", value, a.email, a.ip)
            return "Haftalik sablon kaydedildi." if value else "Haftalik sablon kapatildi (Ayarlar'daki UTC saatleri gecerli)."
        return await act_cal(request, do, "")

    def pub_action(path, fn, msg):
        @app.post(f"/pubs/{{pid}}/{path}", include_in_schema=False, name=f"pub_{path}")
        async def handler(request: Request, pid: int):
            return await act_cal(request, lambda a, f: fn(pid, a, f), msg)

    pub_action("now", lambda pid, a, f: svc.publish_now(pid, a.email, a.ip), "Simdi yayinlanacak.")
    pub_action("cancel", lambda pid, a, f: svc.cancel_publication(pid, a.email, a.ip), "Iptal edildi.")
    pub_action("retry", lambda pid, a, f: svc.retry(pid, a.email, a.ip),
               "Yeniden planlandi. Once platformda var mi kontrol ettin mi?")

    def _resched(pid, a, f):
        try:
            when = plan.parse_tr_datetime(str(f.get("when", "")))
        except ValueError as e:
            raise Invalid(str(e)) from None
        svc.reschedule(pid, when, a.email, a.ip)
    pub_action("reschedule", _resched, "Zaman guncellendi.")

    @app.get("/settings", response_class=HTMLResponse, include_in_schema=False)
    async def settings(request: Request):
        actor = authenticate(request)
        return render(request, actor, "settings.html")

    @app.post("/settings", include_in_schema=False)
    async def settings_post(request: Request):
        actor, f = await guarded_post(request)
        back = "/" if f.get("back") == "home" else "/settings"       # beyaz liste
        try:
            svc.set_setting(str(f.get("key", "")), str(f.get("value", "")), actor.email, actor.ip)
            return go(back, "Ayar kaydedildi.")
        except Invalid as e:
            return go(back, f"Hata: {e}")

    @app.get("/health", response_class=HTMLResponse, include_in_schema=False)
    async def health(request: Request):
        actor = authenticate(request)
        checks = await run_in_threadpool(monitor.get)
        return render(request, actor, "health.html", checks=checks,
                      status=overall(checks), updated=monitor.updated)

    @app.get("/audit", response_class=HTMLResponse, include_in_schema=False)
    async def audit(request: Request):
        actor = authenticate(request)
        return render(request, actor, "audit.html", rows=svc.audit_log(200))

    app.state.service, app.state.monitor = svc, monitor
    return app


def main():                                         # uvicorn: bytepanel.web:main --factory
    return create_app()
