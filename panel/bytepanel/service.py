"""
Panelin is mantigi: R2'den gelen kayitlari alir, onay/takvim/yayin durumunu
yonetir, 100'luk dongu uygular.

Kural: DIS DUNYADAN gelen her sey (R2'deki JSON'lar dahil) dogrulanir. Bir
anahtar ya da URL kayittan ALINMAZ; script_id'den turetilir / izinli alan
adlariyla karsilastirilir.

Yayin semantigi: EN FAZLA BIR KEZ. Once DB'ye "dispatched" yazilir, sonra
GitHub'a gidilir. Yarim kalan bir islem otomatik tekrar denenmez (ayni videoyu
iki kez yuklemek, yuklenmemesinden kotu); zaman asiminda "failed" olur ve
elle yeniden denenir.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from .config import PLATFORMS, SLUG
from .db import Db, iso, parse_iso, utcnow
from .github import GitHubError
from .storage import StorageError, TooLarge

INBOX, RESULTS = "inbox/", "results/"
MAX_RECORD = 64 * 1024
REQ_ID = re.compile(r"^[a-f0-9]{32}\Z")
HEX64 = re.compile(r"^[a-f0-9]{64}\Z")
CTRL = re.compile(r"[\x00-\x1f\x7f]")
SLOT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d\Z")

REMOTE_HOSTS = {
    "youtube": {"youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"},
    "instagram": {"instagram.com", "www.instagram.com"},
    "tiktok": {"tiktok.com", "www.tiktok.com", "vm.tiktok.com"},
}

DEFAULTS = {
    "auto_approve": "0",
    "paused": "0",
    "platform_youtube": "1",
    "platform_instagram": "0",
    "platform_tiktok": "0",
    "youtube_privacy": "public",
    "retention_count": "100",
    "slots_utc": "01:15,07:15,13:15,19:15",
}


class Invalid(ValueError):
    """Kullaniciya gosterilebilir dogrulama hatasi."""


def clean(s, n: int) -> str:
    return CTRL.sub(" ", str(s))[:n].strip()


def keys_for(script_id: str) -> dict:
    return {"video": f"videos/{script_id}/{script_id}.mp4",
            "manifest": f"videos/{script_id}/manifest.json",
            "captions": f"videos/{script_id}/captions.md"}


def parse_slots(text: str) -> list[str]:
    slots = sorted({s.strip() for s in text.split(",") if s.strip()})
    if not slots or len(slots) > 24 or not all(SLOT.match(s) for s in slots):
        raise Invalid("Saatler 'SS:DD,SS:DD' (UTC, 24 saat) biciminde olmali; en fazla 24 tane")
    return slots


def safe_remote_url(platform: str, url: str) -> str:
    """Yalniz https + o platformun alan adi; aksi halde bos (link olarak basilmaz)."""
    try:
        p = urlparse(url)
    except ValueError:
        return ""
    if p.scheme == "https" and (p.hostname or "") in REMOTE_HOSTS.get(platform, ()):
        return url[:300]
    return ""


class Service:
    def __init__(self, db: Db, storage, github, cfg, clock=utcnow):
        self.db, self.storage, self.gh, self.cfg, self.now = db, storage, github, cfg, clock
        self.last_errors: dict[str, str] = {}

    # ── ayarlar ──────────────────────────────────────────────────────
    def setting(self, key: str) -> str:
        r = self.db.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else DEFAULTS[key]

    def flag(self, key: str) -> bool:
        return self.setting(key) == "1"

    def settings(self) -> dict:
        return {k: self.setting(k) for k in DEFAULTS}

    def set_setting(self, key: str, value: str, actor: str, ip: str = "") -> None:
        if key not in DEFAULTS:
            raise Invalid("bilinmeyen ayar")
        value = str(value).strip()
        if key in ("auto_approve", "paused") or key.startswith("platform_"):
            if value not in ("0", "1"):
                raise Invalid("0 ya da 1 olmali")
        elif key == "youtube_privacy":
            if value not in ("public", "unlisted", "private"):
                raise Invalid("public, unlisted ya da private olmali")
        elif key == "retention_count":
            if not value.isdigit() or not 10 <= int(value) <= 1000:
                raise Invalid("10..1000 arasi sayi olmali")
            value = str(int(value))
        elif key == "slots_utc":
            value = ",".join(parse_slots(value))
        with self.db.tx() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.audit(actor, ip, "ayar", f"{key}={value}")

    def enabled_platforms(self) -> list[str]:
        return [p for p in PLATFORMS if self.flag(f"platform_{p}")]

    # ── denetim kaydi ────────────────────────────────────────────────
    def audit(self, actor: str, ip: str, action: str, detail: str = "") -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO audit(at,actor,ip,action,detail) VALUES(?,?,?,?,?)",
                      (iso(self.now()), clean(actor, 120), clean(ip, 64),
                       clean(action, 60), clean(detail, 400)))

    # ── takvim ───────────────────────────────────────────────────────
    def next_free_slot(self, platform: str, after: datetime) -> datetime:
        slots = parse_slots(self.setting("slots_utc"))
        taken = {r["scheduled_at"] for r in self.db.all(
            "SELECT scheduled_at FROM publications WHERE platform=? "
            "AND status IN ('planned','dispatched')", (platform,))}
        day = after.date()
        for d in range(0, 400):
            for s in slots:
                hh, mm = int(s[:2]), int(s[3:])
                cand = datetime(day.year, day.month, day.day, hh, mm,
                                tzinfo=after.tzinfo) + timedelta(days=d)
                if cand > after + timedelta(minutes=2) and iso(cand) not in taken:
                    return cand
        raise Invalid("bos slot bulunamadi")

    def _plan(self, c, script_id: str, platform: str) -> None:
        """Bir yayin satiri acar (varsa dokunmaz). tx icinde cagrilir."""
        row = c.execute("SELECT 1 FROM publications WHERE script_id=? AND platform=?",
                        (script_id, platform)).fetchone()
        if row:
            return
        when = self.next_free_slot(platform, self.now())
        c.execute("INSERT INTO publications(script_id,platform,status,scheduled_at) "
                  "VALUES(?,?,'planned',?)", (script_id, platform, iso(when)))

    # ── ice alma ─────────────────────────────────────────────────────
    def ingest_inbox(self) -> int:
        n = 0
        for key in self.storage.list_keys(INBOX, 200):
            if not key.endswith(".json"):
                continue
            try:
                rec = self._parse_inbox(self.storage.get_bytes(key, MAX_RECORD))
            except (Invalid, ValueError, KeyError, TypeError, TooLarge) as e:
                self._quarantine(key, "inbox-rejected/", f"gecersiz kayit: {e}")
                continue
            sid = rec["script_id"]
            f = keys_for(sid)
            if not all(self.storage.exists(k) for k in f.values()):
                continue          # dosyalar henuz yuklenmemis olabilir: bir sonraki turda
            auto = self.flag("auto_approve")
            with self.db.tx() as c:
                have = c.execute("SELECT 1 FROM videos WHERE script_id=?", (sid,)).fetchone()
                if not have:
                    c.execute(
                        "INSERT INTO videos(script_id,title,series,duration,size_bytes,sha256,"
                        "video_key,manifest_key,captions_key,run_url,approval,approved_at,"
                        "approved_by,rendered_at,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sid, rec["title"], rec["series"], rec["duration"], rec["size_bytes"],
                         rec["sha256"], f["video"], f["manifest"], f["captions"], rec["run_url"],
                         "approved" if auto else "pending",
                         iso(self.now()) if auto else None, "otomatik" if auto else None,
                         rec["rendered_at"], iso(self.now())))
                    if auto:
                        for p in self.enabled_platforms():
                            self._plan(c, sid, p)
            self.storage.delete(key)
            if not have:
                self.audit("sistem", "", "ice alindi", f"{sid} ({'otomatik onay' if auto else 'onay bekliyor'})")
                n += 1
        return n

    @staticmethod
    def _parse_inbox(raw: bytes) -> dict:
        d = json.loads(raw)
        if not isinstance(d, dict) or d.get("v") != 1:
            raise Invalid("v=1 degil")
        sid = d.get("script_id")
        if not isinstance(sid, str) or not SLUG.match(sid):
            raise Invalid("script_id gecersiz")
        title = clean(d.get("title", ""), 200)
        if not title:
            raise Invalid("baslik bos")
        duration = float(d.get("duration", 0))
        if not 0 < duration <= 180:
            raise Invalid("sure 0..180 sn disinda")
        size = int(d.get("size_bytes", 0))
        if not 0 <= size <= 2_000_000_000:
            raise Invalid("boyut gecersiz")
        sha = str(d.get("sha256", ""))
        if sha and not HEX64.match(sha):
            raise Invalid("sha256 gecersiz")
        rendered = str(d.get("rendered_at", ""))
        parse_iso(rendered)
        run_url = str(d.get("run_url", ""))
        if run_url and not run_url.startswith("https://github.com/"):
            run_url = ""
        return {"script_id": sid, "title": title, "series": clean(d.get("series", ""), 8),
                "duration": duration, "size_bytes": size, "sha256": sha,
                "rendered_at": rendered, "run_url": run_url[:300]}

    def _quarantine(self, key: str, prefix: str, why: str) -> None:
        try:
            self.storage.move(key, prefix + key.split("/", 1)[1])
        except (StorageError, KeyError):
            self.storage.delete(key)
        self.audit("sistem", "", "karantina", f"{key}: {why}")

    def ingest_results(self) -> int:
        n = 0
        for key in self.storage.list_keys(RESULTS, 200):
            if not key.endswith(".json"):
                continue
            try:
                d = json.loads(self.storage.get_bytes(key, MAX_RECORD))
                if not isinstance(d, dict) or d.get("v") != 1:
                    raise Invalid("v=1 degil")
                rid, sid, plat = d.get("request_id"), d.get("script_id"), d.get("platform")
                if not (isinstance(rid, str) and REQ_ID.match(rid)
                        and isinstance(sid, str) and SLUG.match(sid) and plat in PLATFORMS):
                    raise Invalid("alanlar gecersiz")
                ok = d.get("ok") is True
                err = clean(d.get("error", ""), 400)
                rid_remote = clean(d.get("remote_id", ""), 80)
                url = safe_remote_url(plat, str(d.get("remote_url", "")))
            except (Invalid, ValueError, TypeError, TooLarge) as e:
                self._quarantine(key, "results-rejected/", f"gecersiz sonuc: {e}")
                continue
            with self.db.tx() as c:
                row = c.execute("SELECT id,status FROM publications WHERE script_id=? AND "
                                "platform=? AND request_id=?", (sid, plat, rid)).fetchone()
                if row and row["status"] == "dispatched":
                    c.execute("UPDATE publications SET status=?,finished_at=?,remote_id=?,"
                              "remote_url=?,error=? WHERE id=?",
                              ("published" if ok else "failed", iso(self.now()),
                               rid_remote, url, "" if ok else (err or "bilinmeyen hata"), row["id"]))
                    n += 1
                    matched = True
                else:
                    matched = False
            if matched:
                self.storage.delete(key)
                self.audit("sistem", "", "sonuc", f"{sid}/{plat}: {'basarili' if ok else 'hata'}")
            else:
                self._quarantine(key, "results-orphan/", "eslesen bekleyen yayin yok")
        return n

    # ── onay ─────────────────────────────────────────────────────────
    def _video(self, script_id: str):
        v = self.db.one("SELECT * FROM videos WHERE script_id=?", (script_id,))
        if not v:
            raise Invalid("video bulunamadi")
        return v

    def approve(self, script_id: str, actor: str, ip: str = "") -> None:
        v = self._video(script_id)
        if v["files_deleted_at"]:
            raise Invalid("dosyalari silinmis video onaylanamaz")
        with self.db.tx() as c:
            c.execute("UPDATE videos SET approval='approved',approved_at=?,approved_by=? "
                      "WHERE script_id=?", (iso(self.now()), clean(actor, 120), script_id))
            for p in self.enabled_platforms():
                self._plan(c, script_id, p)
        self.audit(actor, ip, "onay", script_id)

    def approve_all_pending(self, actor: str, ip: str = "") -> int:
        ids = [r["script_id"] for r in self.db.all(
            "SELECT script_id FROM videos WHERE approval='pending' AND files_deleted_at IS NULL "
            "ORDER BY rendered_at")]
        for sid in ids:
            self.approve(sid, actor, ip)
        return len(ids)

    def reject(self, script_id: str, actor: str, ip: str = "") -> None:
        self._video(script_id)
        with self.db.tx() as c:
            c.execute("UPDATE videos SET approval='rejected',approved_at=NULL,approved_by=NULL "
                      "WHERE script_id=?", (script_id,))
            c.execute("UPDATE publications SET status='canceled',finished_at=? "
                      "WHERE script_id=? AND status='planned'", (iso(self.now()), script_id))
        self.audit(actor, ip, "red", script_id)

    def unapprove(self, script_id: str, actor: str, ip: str = "") -> None:
        v = self._video(script_id)
        busy = self.db.one("SELECT 1 FROM publications WHERE script_id=? AND status='dispatched'",
                           (script_id,))
        if busy:
            raise Invalid("yayin su an gonderiliyor, bekle")
        with self.db.tx() as c:
            c.execute("UPDATE videos SET approval='pending',approved_at=NULL,approved_by=NULL "
                      "WHERE script_id=?", (v["script_id"],))
            c.execute("UPDATE publications SET status='canceled',finished_at=? "
                      "WHERE script_id=? AND status='planned'", (iso(self.now()), script_id))
        self.audit(actor, ip, "onay geri alindi", script_id)

    def plan_platform(self, script_id: str, platform: str, actor: str, ip: str = "") -> None:
        v = self._video(script_id)
        if platform not in PLATFORMS:
            raise Invalid("bilinmeyen platform")
        if v["approval"] != "approved" or v["files_deleted_at"]:
            raise Invalid("video onayli ve dosyalari duruyor olmali")
        with self.db.tx() as c:
            old = c.execute("SELECT id,status FROM publications WHERE script_id=? AND platform=?",
                            (script_id, platform)).fetchone()
            if old and old["status"] in ("planned", "dispatched", "published"):
                raise Invalid("bu platform icin yayin zaten var")
            when = iso(self.next_free_slot(platform, self.now()))
            if old:
                c.execute("UPDATE publications SET status='planned',scheduled_at=?,request_id=NULL,"
                          "dispatched_at=NULL,finished_at=NULL,error=NULL WHERE id=?",
                          (when, old["id"]))
            else:
                c.execute("INSERT INTO publications(script_id,platform,status,scheduled_at) "
                          "VALUES(?,?,'planned',?)", (script_id, platform, when))
        self.audit(actor, ip, "yayin planlandi", f"{script_id}/{platform}")

    def reschedule(self, pub_id: int, when: datetime, actor: str, ip: str = "") -> None:
        if when < self.now() - timedelta(minutes=1):
            raise Invalid("gecmis bir zaman secilemez")
        if when > self.now() + timedelta(days=400):
            raise Invalid("cok uzak bir tarih")
        with self.db.tx() as c:
            r = c.execute("UPDATE publications SET scheduled_at=? WHERE id=? AND status='planned'",
                          (iso(when), pub_id))
            if r.rowcount != 1:
                raise Invalid("yalniz 'planli' yayinin zamani degisir")
        self.audit(actor, ip, "zaman degisti", f"#{pub_id} -> {iso(when)}")

    def publish_now(self, pub_id: int, actor: str, ip: str = "") -> None:
        self.reschedule(pub_id, self.now(), actor, ip)

    def cancel_publication(self, pub_id: int, actor: str, ip: str = "") -> None:
        with self.db.tx() as c:
            r = c.execute("UPDATE publications SET status='canceled',finished_at=? "
                          "WHERE id=? AND status='planned'", (iso(self.now()), pub_id))
            if r.rowcount != 1:
                raise Invalid("yalniz 'planli' yayin iptal edilir")
        self.audit(actor, ip, "yayin iptal", f"#{pub_id}")

    def retry(self, pub_id: int, actor: str, ip: str = "") -> None:
        """Basarisiz yayini yeniden planlar. UYARI: platformda zaten var mi diye
        once elle bakilmali (zaman asimi sonucu kaybolmus olabilir)."""
        with self.db.tx() as c:
            row = c.execute("SELECT p.platform,p.script_id,v.approval,v.files_deleted_at "
                            "FROM publications p JOIN videos v USING(script_id) "
                            "WHERE p.id=? AND p.status='failed'", (pub_id,)).fetchone()
            if not row:
                raise Invalid("yalniz 'basarisiz' yayin yeniden denenir")
            if row["approval"] != "approved" or row["files_deleted_at"]:
                raise Invalid("video onayli ve dosyalari duruyor olmali")
            when = iso(self.next_free_slot(row["platform"], self.now()))
            c.execute("UPDATE publications SET status='planned',scheduled_at=?,request_id=NULL,"
                      "dispatched_at=NULL,finished_at=NULL,error=NULL WHERE id=?", (when, pub_id))
        self.audit(actor, ip, "yeniden deneme", f"#{pub_id}")

    # ── yayin ────────────────────────────────────────────────────────
    def expire_dispatched(self) -> int:
        cutoff = iso(self.now() - timedelta(minutes=self.cfg.dispatch_timeout_min))
        with self.db.tx() as c:
            r = c.execute("UPDATE publications SET status='failed',finished_at=?,"
                          "error='zaman asimi: sonuc gelmedi. Platformda var mi kontrol et, "
                          "yoksa yeniden dene.' WHERE status='dispatched' AND dispatched_at<=?",
                          (iso(self.now()), cutoff))
            return r.rowcount

    def dispatch_due(self) -> int:
        if self.flag("paused"):
            return 0
        now = self.now()
        hour_ago = iso(now - timedelta(hours=1))
        sent = self.db.one("SELECT COUNT(*) n FROM publications WHERE dispatched_at>=?",
                           (hour_ago,))["n"]
        budget = self.cfg.max_dispatch_per_hour - sent
        if budget <= 0:
            self.last_errors["dispatch"] = "saatlik gonderim siniri doldu"
            return 0
        enabled = set(self.enabled_platforms())
        rows = self.db.all(
            "SELECT p.id,p.script_id,p.platform,v.video_key FROM publications p "
            "JOIN videos v USING(script_id) WHERE p.status='planned' AND p.scheduled_at<=? "
            "AND v.approval='approved' AND v.files_deleted_at IS NULL "
            "ORDER BY p.scheduled_at LIMIT ?", (iso(now), budget))
        n = 0
        for r in rows:
            if r["platform"] not in enabled:
                continue
            if not self.storage.exists(r["video_key"]):
                self._fail(r["id"], "video dosyasi R2'de yok")
                continue
            rid = uuid.uuid4().hex
            with self.db.tx() as c:                        # ONCE kayit, SONRA gonderim
                ok = c.execute("UPDATE publications SET status='dispatched',request_id=?,"
                               "dispatched_at=?,attempts=attempts+1 WHERE id=? AND status='planned'",
                               (rid, iso(now), r["id"])).rowcount
            if ok != 1:
                continue
            try:
                self.gh.dispatch({"script_id": r["script_id"], "platform": r["platform"],
                                  "privacy": self.setting("youtube_privacy"), "request_id": rid})
            except GitHubError as e:
                self._fail(r["id"], f"GitHub'a gonderilemedi: {e}")
                continue
            self.audit("sistem", "", "gonderildi", f"{r['script_id']}/{r['platform']}")
            n += 1
        return n

    def _fail(self, pub_id: int, msg: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE publications SET status='failed',finished_at=?,error=? WHERE id=?",
                      (iso(self.now()), clean(msg, 400), pub_id))

    # ── 100'luk dongu ────────────────────────────────────────────────
    def enforce_retention(self) -> list[str]:
        keep = int(self.setting("retention_count"))
        rows = self.db.all("SELECT script_id,video_key,manifest_key,captions_key FROM videos "
                           "WHERE files_deleted_at IS NULL ORDER BY rendered_at,script_id")
        excess = len(rows) - keep
        gone: list[str] = []
        for r in rows:
            if excess <= 0:
                break
            v = self.db.one("SELECT approval FROM videos WHERE script_id=?", (r["script_id"],))
            busy = self.db.one("SELECT 1 FROM publications WHERE script_id=? "
                               "AND status IN ('planned','dispatched')", (r["script_id"],))
            if v["approval"] == "pending" or busy:
                continue                  # bekleyen is varken dosya silinmez
            for k in (r["video_key"], r["manifest_key"], r["captions_key"]):
                self.storage.delete(k)
            with self.db.tx() as c:
                c.execute("UPDATE videos SET files_deleted_at=? WHERE script_id=?",
                          (iso(self.now()), r["script_id"]))
            self.audit("sistem", "", "dosya silindi", f"{r['script_id']} (100'luk dongu)")
            gone.append(r["script_id"])
            excess -= 1
        return gone

    def tick(self) -> dict:
        out = {}
        for name, fn in (("ice_alma", self.ingest_inbox), ("sonuc", self.ingest_results),
                         ("zaman_asimi", self.expire_dispatched), ("gonderim", self.dispatch_due),
                         ("dongu", self.enforce_retention)):
            try:
                res = fn()
                out[name] = len(res) if isinstance(res, list) else res
                self.last_errors.pop(name, None)
            except Exception as e:                       # bir adim digerlerini durdurmasin
                self.last_errors[name] = f"{type(e).__name__}: {str(e)[:200]}"
                out[name] = "hata"
        return out

    # ── okuma (arayuz icin) ──────────────────────────────────────────
    def videos(self, limit: int = 200):
        return self.db.all("SELECT * FROM videos ORDER BY rendered_at DESC, script_id DESC LIMIT ?",
                           (limit,))

    def video(self, script_id: str):
        return self._video(script_id)

    def publications(self, script_id: str):
        return self.db.all("SELECT * FROM publications WHERE script_id=? ORDER BY platform",
                           (script_id,))

    def upcoming(self, limit: int = 100):
        return self.db.all(
            "SELECT p.*,v.title FROM publications p JOIN videos v USING(script_id) "
            "WHERE p.status IN ('planned','dispatched') ORDER BY p.scheduled_at LIMIT ?", (limit,))

    def recent_results(self, limit: int = 20):
        return self.db.all(
            "SELECT p.*,v.title FROM publications p JOIN videos v USING(script_id) "
            "WHERE p.status IN ('published','failed') ORDER BY p.finished_at DESC LIMIT ?", (limit,))

    def counts(self) -> dict:
        q = lambda sql: self.db.one(sql)["n"]            # noqa: E731
        return {
            "pending": q("SELECT COUNT(*) n FROM videos WHERE approval='pending' "
                         "AND files_deleted_at IS NULL"),
            "planned": q("SELECT COUNT(*) n FROM publications WHERE status='planned'"),
            "dispatched": q("SELECT COUNT(*) n FROM publications WHERE status='dispatched'"),
            "published": q("SELECT COUNT(*) n FROM publications WHERE status='published'"),
            "failed": q("SELECT COUNT(*) n FROM publications WHERE status='failed'"),
            "stored": q("SELECT COUNT(*) n FROM videos WHERE files_deleted_at IS NULL"),
            "total": q("SELECT COUNT(*) n FROM videos"),
        }

    def audit_log(self, limit: int = 100):
        return self.db.all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))

    def preview_url(self, script_id: str) -> str:
        v = self._video(script_id)
        if v["files_deleted_at"]:
            raise Invalid("dosya 100'luk dongude silinmis")
        return self.storage.presign_get(v["video_key"], 300)
