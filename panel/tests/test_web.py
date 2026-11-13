"""Web + guvenlik testleri. Gercek Cloudflare yok: RSA anahtari uretip sahte JWKS veriyoruz."""
import json
import re
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from bytepanel import config
from bytepanel.db import Db
from bytepanel.health import HealthMonitor
from bytepanel.security import CfAccess, csrf_token
from bytepanel.service import Service
from bytepanel.storage import MemoryStorage
from bytepanel.web import create_app
from tests.helpers import Clock, FakeGitHub, put_video

TEAM = "semih.cloudflareaccess.com"
AUD = "aud-tag-123"
ME = "semih@example.com"
ORIGIN = "https://panel.test"
A, B = "p001-tay-chatbot", "p002-gpt3-gpu"


def keypair(kid="k1"):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(priv.public_key(), as_dict=True)
    jwk.update(kid=kid, alg="RS256", use="sig")
    return priv, {"keys": [jwk]}


PRIV, JWKS = keypair()
OTHER, _ = keypair("k1")                     # ayni kid, baska anahtar


def token(email=ME, aud=AUD, iss=f"https://{TEAM}", exp=300, iat=0, key=PRIV, kid="k1",
          alg="RS256", extra=None, drop=()):
    now = int(time.time())
    claims = {"email": email, "aud": [aud], "iss": iss, "iat": now + iat, "exp": now + exp}
    claims.update(extra or {})
    for d in drop:
        claims.pop(d, None)
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def make_app(**env):
    e = {"PANEL_ENV": "test", "PANEL_ORIGIN": ORIGIN, "CF_ACCESS_TEAM_DOMAIN": TEAM,
         "CF_ACCESS_AUD": AUD, "PANEL_ALLOWED_EMAILS": ME}
    e.update(env)
    cfg = config.load(e)
    clock = Clock()
    st = MemoryStorage()
    svc = Service(Db(":memory:"), st, FakeGitHub(), cfg, clock=clock)
    access = CfAccess(TEAM, AUD, {ME}, fetch_jwks=lambda: JWKS)
    app = create_app(cfg, service=svc, access=access, monitor=HealthMonitor(svc), start_worker=False)
    return app, svc, st, cfg


class Base(unittest.TestCase):
    def setUp(self):
        self.app, self.svc, self.st, self.cfg = make_app()
        self.c = TestClient(self.app, base_url=ORIGIN, follow_redirects=False)
        self.auth = {"Cf-Access-Jwt-Assertion": token()}

    def get(self, path, **kw):
        return self.c.get(path, headers=self.auth, **kw)

    def post(self, path, data=None, csrf=True, origin=ORIGIN, headers=None):
        h = dict(self.auth)
        if origin:
            h["Origin"] = origin
        h.update(headers or {})
        data = dict(data or {})
        if csrf is True:
            data["csrf"] = csrf_token(self.cfg.csrf_secret, ME)
        elif csrf:
            data["csrf"] = csrf
        return self.c.post(path, data=data, headers=h)

    def add(self, sid=A, **over):
        put_video(self.st, sid, **over)
        self.svc.ingest_inbox()


class Auth(Base):
    GETS = ["/", "/videos", f"/videos/{A}", f"/videos/{A}/preview", "/calendar", "/settings",
            "/health", "/audit", "/static/app.css", "/static/app.js", "/scripts", "/scripts/new"]
    POSTS = [f"/videos/{A}/approve", f"/videos/{A}/reject", f"/videos/{A}/unapprove",
             f"/videos/{A}/plan", "/approve-all", "/pubs/1/now", "/pubs/1/cancel",
             "/pubs/1/retry", "/pubs/1/reschedule", "/settings", "/calendar/plan",
             "/calendar/move", "/calendar/autofill", "/calendar/template",
             "/scripts/new", f"/scripts/{A}/move", f"/scripts/{A}/remove"]

    def test_every_route_refuses_requests_without_a_token(self):
        self.add()
        for p in self.GETS:
            self.assertEqual(self.c.get(p).status_code, 403, p)
        for p in self.POSTS:
            self.assertEqual(self.c.post(p, headers={"Origin": ORIGIN}).status_code, 403, p)

    def test_the_route_list_in_this_test_is_complete(self):
        routes = {(m, r.path) for r in self.app.routes if hasattr(r, "methods")
                  for m in r.methods if m in ("GET", "POST")}
        covered = set()
        for p in self.GETS:
            covered.add(("GET", re.sub(rf"{A}", "{sid}", p)))
        for p in self.POSTS:
            covered.add(("POST", re.sub(r"/pubs/1/", "/pubs/{pid}/", re.sub(A, "{sid}", p))))
        missing = {x for x in routes if x[1] not in ("/healthz",)} - covered
        self.assertEqual(missing, set(), "yeni rota eklendi: kimlik testine ekle")

    def test_healthz_is_open_and_says_nothing(self):
        r = self.c.get("/healthz")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True}))

    def test_docs_and_openapi_are_off(self):
        for p in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.get(p).status_code, 404)

    def test_a_valid_token_gets_through(self):
        self.assertEqual(self.get("/").status_code, 200)

    def test_bad_tokens_are_all_refused(self):
        bad = {
            "wrong audience": token(aud="other"),
            "wrong issuer": token(iss="https://evil.cloudflareaccess.com"),
            "not allowed email": token(email="eve@example.com"),
            "no email (service token)": token(drop=("email",)),
            "expired": token(exp=-120),
            "not yet valid iat": token(iat=0, extra={"nbf": int(time.time()) + 3600}),
            "no exp": token(drop=("exp",)),
            "no aud": token(drop=("aud",)),
            "signed by another key": token(key=OTHER),
            "unknown kid": token(kid="nope"),
            "garbage": "abc.def.ghi",
            "empty": "",
            "huge": "a" * 9000,
        }
        for why, tok in bad.items():
            r = self.c.get("/", headers={"Cf-Access-Jwt-Assertion": tok})
            self.assertEqual(r.status_code, 403, why)

    def test_alg_none_and_hmac_confusion_are_refused(self):
        import base64
        import hashlib
        import hmac as _hmac
        from cryptography.hazmat.primitives import serialization
        claims = {"email": ME, "aud": [AUD], "iss": f"https://{TEAM}",
                  "iat": int(time.time()), "exp": int(time.time()) + 300}

        def b64(b):
            return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
        # alg=none: imzasiz belirtec
        none = b64(json.dumps({"alg": "none", "kid": "k1"}).encode()) + "." + \
            b64(json.dumps(claims).encode()) + "."
        # HS256 karisikligi: saldirgan ACIK anahtari HMAC sirri olarak kullanir (elle imza)
        pem = PRIV.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo)
        signing = b64(json.dumps({"alg": "HS256", "kid": "k1"}).encode()) + "." + \
            b64(json.dumps(claims).encode())
        hs = signing + "." + b64(_hmac.new(pem, signing.encode(), hashlib.sha256).digest())
        for tok in (none, hs):
            self.assertEqual(self.c.get("/", headers={"Cf-Access-Jwt-Assertion": tok}).status_code, 403)

    def test_a_forged_identity_header_is_not_enough(self):
        for h in ({"Cf-Access-Authenticated-User-Email": ME}, {"X-Forwarded-User": ME},
                  {"Cf-Connecting-Ip": "1.2.3.4"}):
            self.assertEqual(self.c.get("/", headers=h).status_code, 403)

    def test_jwks_failure_denies_instead_of_allowing(self):
        def broken():
            raise RuntimeError("down")
        acc = CfAccess(TEAM, AUD, {ME}, fetch_jwks=broken)
        app = create_app(self.cfg, service=self.svc, access=acc, monitor=HealthMonitor(self.svc),
                         start_worker=False)
        c = TestClient(app, base_url=ORIGIN)
        self.assertEqual(c.get("/", headers=self.auth).status_code, 403)


class DevMode(unittest.TestCase):
    def test_dev_identity_works_locally_but_never_through_cloudflare(self):
        app, *_ = make_app(PANEL_DEV_USER=ME)
        c = TestClient(app, base_url=ORIGIN)
        self.assertEqual(c.get("/").status_code, 200)
        for h in ({"Cf-Ray": "abc"}, {"Cf-Connecting-Ip": "1.1.1.1"},
                  {"Cf-Access-Jwt-Assertion": "x"}):
            self.assertEqual(c.get("/", headers=h).status_code, 403, h)

    def test_dev_user_is_a_config_error_in_prod(self):
        with self.assertRaises(config.ConfigError):
            config.load(prod_env(PANEL_DEV_USER="x@y.z"))


def prod_env(**over):
    e = {"PANEL_ENV": "prod", "PANEL_ORIGIN": "https://byte.semihkopcal.com",
         "R2_ENDPOINT": "https://acc.r2.cloudflarestorage.com", "R2_BUCKET": "b",
         "R2_ACCESS_KEY_ID": "id", "R2_SECRET_ACCESS_KEY": "sec",
         "GITHUB_REPO": "SemihKopcal/byte-shorts", "GITHUB_TOKEN": "tok",
         "CF_ACCESS_TEAM_DOMAIN": TEAM, "CF_ACCESS_AUD": AUD,
         "PANEL_ALLOWED_EMAILS": ME, "PANEL_CSRF_SECRET": "x" * 40}
    e.update(over)
    return e


class Csrf(Base):
    def test_a_post_without_origin_is_refused(self):
        self.add()
        self.assertEqual(self.post(f"/videos/{A}/approve", origin=None).status_code, 403)

    def test_a_post_from_another_origin_is_refused(self):
        self.add()
        for o in ("https://evil.example", "http://panel.test", ORIGIN + ".evil.example", "null"):
            self.assertEqual(self.post(f"/videos/{A}/approve", origin=o).status_code, 403, o)
        self.assertEqual(self.svc.video(A)["approval"], "pending")

    def test_referer_is_accepted_only_when_it_matches(self):
        self.add()
        ok = self.post(f"/videos/{A}/approve", origin=None, headers={"Referer": ORIGIN + "/videos"})
        self.assertEqual(ok.status_code, 303)
        self.add(B)
        bad = self.post(f"/videos/{B}/approve", origin=None, headers={"Referer": "https://evil.example/x"})
        self.assertEqual(bad.status_code, 403)

    def test_a_post_without_or_with_a_wrong_token_is_refused(self):
        self.add()
        for tokenv in (False, "deadbeef", "x" * 40):
            self.assertEqual(self.post(f"/videos/{A}/approve", csrf=tokenv).status_code, 403)
        self.assertEqual(self.svc.video(A)["approval"], "pending")

    def test_tokens_are_bound_to_the_actor_and_the_day(self):
        from bytepanel.security import csrf_ok
        s = self.cfg.csrf_secret
        t = csrf_token(s, ME, now=1_000_000)
        self.assertTrue(csrf_ok(s, ME, t, now=1_000_000))
        self.assertTrue(csrf_ok(s, ME, t, now=1_000_000 + 86400))          # dun'un token'i
        self.assertFalse(csrf_ok(s, ME, t, now=1_000_000 + 3 * 86400))
        self.assertFalse(csrf_ok(s, "eve@example.com", t, now=1_000_000))
        self.assertFalse(csrf_ok(b"other-secret", ME, t, now=1_000_000))
        self.assertFalse(csrf_ok(s, ME, "", now=1_000_000))

    def test_get_requests_never_change_state(self):
        self.add()
        for p in ("/", f"/videos/{A}", "/calendar", "/health", "/audit", f"/videos/{A}/approve"):
            self.get(p)
        self.assertEqual(self.svc.video(A)["approval"], "pending")


class Headers(Base):
    def test_security_headers_on_every_kind_of_response(self):
        for r in (self.get("/"), self.c.get("/"), self.get("/nope"), self.c.get("/healthz")):
            h = r.headers
            self.assertIn("default-src 'none'", h["content-security-policy"])
            self.assertIn("script-src 'self'", h["content-security-policy"])
            self.assertNotIn("unsafe-inline", h["content-security-policy"])
            self.assertIn("frame-ancestors 'none'", h["content-security-policy"])
            self.assertEqual(h["x-content-type-options"], "nosniff")
            # no-referrer olursa tarayici ayni site formunda "Origin: null" yollar ve her POST 403 olur
            self.assertEqual(h["referrer-policy"], "same-origin")
            self.assertEqual(h["cache-control"], "no-store")
            self.assertIn("max-age", h["strict-transport-security"])

    def test_csp_allows_video_only_from_the_r2_host(self):
        csp = self.get("/").headers["content-security-policy"]
        self.assertIn(f"media-src {self.cfg.media_host}", csp)

    def test_pages_carry_no_inline_script_or_handlers(self):
        self.add()
        for p in ("/", "/videos", f"/videos/{A}", "/calendar", "/settings", "/health", "/audit"):
            body = self.get(p).text
            self.assertNotRegex(body, r"<script(?![^>]*\bsrc=)", p)
            self.assertNotRegex(body, r"\son(click|submit|load|error)=", p)
            self.assertNotIn("<style", body, p)

    def test_the_oversized_body_is_refused_with_headers(self):
        r = self.c.post("/settings", content=b"x" * 70000,
                        headers={**self.auth, "Origin": ORIGIN,
                                 "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 413)
        self.assertIn("content-security-policy", r.headers)


class Escaping(Base):
    def test_titles_are_html_escaped_everywhere(self):
        self.add(title="<script>alert(1)</script><img src=x onerror=alert(2)>")
        for p in ("/", "/videos", f"/videos/{A}"):
            body = self.get(p).text
            self.assertNotIn("<script>alert(1)", body, p)
            self.assertNotIn("<img src=x", body, p)
        self.assertIn("&lt;script&gt;alert(1)", self.get("/videos").text)

    def test_the_flash_message_is_escaped_and_cleared(self):
        self.c.cookies.set("flash", "PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==")      # <script>alert(1)</script>
        r = self.get("/")
        self.assertNotIn("<script>alert(1)", r.text)
        self.assertIn("&lt;script&gt;", r.text)

    def test_only_safe_links_become_anchors(self):
        self.add()
        self.svc.approve(A, ME)
        with self.svc.db.tx() as c:
            c.execute("UPDATE publications SET status='published',finished_at=?,remote_url=? "
                      "WHERE script_id=?", ("2026-11-08T15:00:00Z", "https://youtu.be/abc", A))
        body = self.get(f"/videos/{A}").text
        self.assertIn('href="https://youtu.be/abc"', body)
        self.assertIn('rel="noopener noreferrer"', body)


class Flows(Base):
    def test_approve_reject_and_calendar(self):
        self.add()
        r = self.post(f"/videos/{A}/approve")
        self.assertEqual((r.status_code, r.headers["location"]), (303, f"/videos/{A}"))
        self.assertEqual(self.svc.video(A)["approval"], "approved")
        self.assertIn("Video p001", self.get("/calendar").text)
        self.post(f"/videos/{A}/unapprove")
        self.post(f"/videos/{A}/reject")
        self.assertEqual(self.svc.video(A)["approval"], "rejected")

    def test_errors_are_shown_as_a_flash_not_a_crash(self):
        r = self.post("/pubs/999/cancel")
        self.assertEqual(r.status_code, 303)
        page = self.c.get("/calendar", headers=self.auth, cookies=r.cookies)
        self.assertIn("Hata", page.text)

    def test_invalid_ids_are_404_not_redirects(self):
        for sid in ("%2e%2e", "A_B", "x" * 90, "ab", "UPPER-CASE"):
            self.assertIn(self.get(f"/videos/{sid}").status_code, (404, 307, 308), sid)
            r = self.post(f"/videos/{sid}/approve")
            self.assertIn(r.status_code, (404, 405, 307, 308), sid)
            self.assertNotIn("location", {k.lower() for k in r.headers} if r.status_code == 404 else set())
        self.assertEqual(self.get("/videos/p404-not-there").status_code, 404)

    def test_a_trailing_newline_does_not_pass_the_id_check(self):
        # `$` ile biten bir regex "id\\n" degerini de kabul ederdi
        r = self.get(f"/videos/{A}%0A")
        self.assertEqual(r.status_code, 404)
        r = self.post(f"/videos/{A}%0A/approve")
        self.assertNotEqual(r.status_code, 303)
        self.assertNotIn("\n", r.headers.get("location", ""))

    def test_settings_toggles_and_validation(self):
        r = self.post("/settings", {"key": "auto_approve", "value": "1", "back": "home"})
        self.assertEqual(r.headers["location"], "/")
        self.assertEqual(self.svc.setting("auto_approve"), "1")
        r = self.post("/settings", {"key": "auto_approve", "value": "1", "back": "https://evil.example"})
        self.assertEqual(r.headers["location"], "/settings")          # yalniz beyaz liste
        self.post("/settings", {"key": "retention_count", "value": "3"})
        self.assertEqual(self.svc.setting("retention_count"), "100")      # gecersiz: degismedi
        self.post("/settings", {"key": "../../etc", "value": "x"})

    def test_pause_and_auto_approve_come_from_the_home_page_forms(self):
        body = self.get("/").text
        self.assertIn('name="key" value="auto_approve"', body)
        self.assertIn('name="key" value="paused"', body)

    def test_reschedule_form(self):
        self.add()
        self.svc.approve(A, ME)
        pid = self.svc.publications(A)[0]["id"]
        self.post(f"/pubs/{pid}/reschedule", {"when": "2026-11-12 08:15"})      # Turkiye saati
        self.assertEqual(self.svc.publications(A)[0]["scheduled_at"], "2026-11-12T05:15:00Z")
        self.post(f"/pubs/{pid}/reschedule", {"when": "tomorrow"})
        self.assertEqual(self.svc.publications(A)[0]["scheduled_at"], "2026-11-12T05:15:00Z")

    def test_preview_returns_a_short_lived_signed_url_only_when_the_file_exists(self):
        self.add()
        j = self.get(f"/videos/{A}/preview").json()
        self.assertIn(f"videos/{A}/{A}.mp4", j["url"])
        self.assertEqual(self.get("/videos/p404-not-there/preview").status_code, 404)

    def test_actions_are_audited_with_the_actor(self):
        self.add()
        self.post(f"/videos/{A}/approve", headers={"Cf-Connecting-Ip": "9.9.9.9"})
        row = [r for r in self.svc.audit_log(10) if r["action"] == "onay"][0]
        self.assertEqual((row["actor"], row["ip"]), (ME, "9.9.9.9"))

    def test_rate_limit_stops_a_flood_of_posts(self):
        codes = [self.post("/pubs/999/cancel").status_code for _ in range(45)]
        self.assertEqual(codes.count(303), 40)
        self.assertEqual(set(codes[40:]), {429})

    def test_pages_render(self):
        self.add()
        self.svc.approve(A, ME)
        for p in ("/", "/videos", f"/videos/{A}", "/calendar", "/settings", "/health", "/audit"):
            self.assertEqual(self.get(p).status_code, 200, p)
        self.assertIn("Her sey yolunda", self.get("/health").text)


class Config(unittest.TestCase):
    def test_prod_needs_everything_and_fails_closed(self):
        config.load(prod_env())                                       # tam ise tamam
        for name in ("PANEL_ORIGIN", "R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID",
                     "R2_SECRET_ACCESS_KEY", "GITHUB_REPO", "GITHUB_TOKEN",
                     "CF_ACCESS_TEAM_DOMAIN", "CF_ACCESS_AUD", "PANEL_ALLOWED_EMAILS",
                     "PANEL_CSRF_SECRET"):
            env = prod_env()
            del env[name]
            with self.assertRaises(config.ConfigError, msg=name):
                config.load(env)

    def test_bad_values_are_rejected(self):
        for over in ({"PANEL_ORIGIN": "http://byte.semihkopcal.com"},
                     {"PANEL_ORIGIN": "https://byte.semihkopcal.com/"},
                     {"PANEL_CSRF_SECRET": "short"},
                     {"CF_ACCESS_TEAM_DOMAIN": "evil.example.com"},
                     {"PANEL_ALLOWED_EMAILS": "not-an-email"},
                     {"R2_ENDPOINT": "http://insecure"},
                     {"GITHUB_REPO": "no-slash"},
                     {"PANEL_ENV": "staging"},
                     {"PANEL_MAX_DISPATCH_PER_HOUR": "0"}):
            with self.assertRaises(config.ConfigError, msg=str(over)):
                config.load(prod_env(**over))

    def test_secrets_can_come_from_files_and_are_not_kept_in_the_repr(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = f"{d}/gh"
            with open(p, "w") as fh:
                fh.write("ghp_secret_value\n")
            env = prod_env(GITHUB_TOKEN_FILE=p)
            del env["GITHUB_TOKEN"]
            cfg = config.load(env)
        self.assertEqual(cfg.gh_token, "ghp_secret_value")
        with self.assertRaises(config.ConfigError):
            config.load(prod_env(GITHUB_TOKEN_FILE="/nonexistent/secret"))


if __name__ == "__main__":
    unittest.main()
