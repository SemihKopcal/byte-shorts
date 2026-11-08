"""
Servis sagligi: "her sey yolunda mi?" sorusunun cevabi tek sayfada.

Her kontrol kendi icinde korunur: biri patlarsa digerleri yine calisir ve
patlayan 'fail' olarak gorunur. Sonuclar kisa sure onbellekte tutulur.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta

from .db import iso, parse_iso

OK, WARN, FAIL = "ok", "warn", "fail"
RANK = {OK: 0, WARN: 1, FAIL: 2}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _age(ts: str | None, now) -> str:
    if not ts:
        return "bilinmiyor"
    try:
        d = now - parse_iso(ts.replace(".000", "")[:19] + "Z")
    except ValueError:
        return "bilinmiyor"
    m = int(d.total_seconds() // 60)
    if m < 60:
        return f"{m} dk once"
    if m < 60 * 48:
        return f"{m // 60} sa once"
    return f"{m // 1440} gun once"


def run_checks(svc) -> list[Check]:
    now = svc.now()
    out: list[Check] = []

    def guard(name, fn):
        try:
            out.extend(fn())
        except Exception as e:                     # kontrolun kendisi patlarsa 'fail'
            out.append(Check(name, FAIL, f"{type(e).__name__}: {str(e)[:160]}"))

    def db():
        svc.db.one("SELECT 1")
        return [Check("Veritabani", OK, "calisiyor")]

    def store():
        svc.storage.ping()
        return [Check("R2 deposu", OK, "ulasilabiliyor")]

    def github():
        svc.gh.ping()
        return [Check("GitHub", OK, "ulasilabiliyor")]

    def runs():
        res = []
        for label, wf in (("Uretim (daily)", "daily.yml"), ("Yayin (panel-publish)", svc.cfg.gh_workflow)):
            r = svc.gh.latest_run(wf)
            if not r:
                res.append(Check(label, WARN, "henuz kosu yok"))
                continue
            when = _age(r["created_at"], now)
            if r["status"] != "completed":
                res.append(Check(label, OK, f"suruyor ({when})"))
            elif r["conclusion"] == "success":
                res.append(Check(label, OK, f"son kosu basarili ({when})"))
            else:
                res.append(Check(label, FAIL, f"son kosu {r['conclusion']} ({when}): {r['url']}"))
        return res

    def queue():
        q = svc.gh.queue_left()
        if q["left"] == 0:
            return [Check("Senaryo kuyrugu", FAIL, "bos: yeni parti yazilmali")]
        if q["left"] <= 8:
            return [Check("Senaryo kuyrugu", WARN, f"{q['left']} senaryo kaldi (tahmini)")]
        return [Check("Senaryo kuyrugu", OK, f"{q['left']} senaryo var (tahmini)")]

    def worker():
        if not svc.last_errors:
            return [Check("Arka plan isleri", OK, "hata yok")]
        return [Check("Arka plan isleri", WARN, f"{k}: {v}") for k, v in sorted(svc.last_errors.items())]

    def work():
        c = svc.counts()
        res = []
        res.append(Check("Onay bekleyen", WARN if c["pending"] > 10 else OK,
                         f"{c['pending']} video"))
        stuck = svc.db.one("SELECT COUNT(*) n FROM publications WHERE status='dispatched' "
                           "AND dispatched_at<=?",
                           (iso(now - timedelta(minutes=svc.cfg.dispatch_timeout_min // 2)),))["n"]
        res.append(Check("Yayin gonderimi", WARN if stuck else OK,
                         f"{stuck} yayin uzun suredir sonuc bekliyor" if stuck else
                         f"{c['dispatched']} suruyor, {c['failed']} basarisiz"))
        if svc.flag("paused"):
            res.append(Check("Duraklatma", WARN, "yayin DURAKLATILDI"))
        return res

    def platforms():
        res = []
        for p in svc.enabled_platforms():
            last = svc.db.one("SELECT status,finished_at,error FROM publications WHERE platform=? "
                              "AND status IN ('published','failed') ORDER BY finished_at DESC LIMIT 1", (p,))
            if not last:
                res.append(Check(f"Platform: {p}", OK, "henuz yayin yok"))
            elif last["status"] == "published":
                res.append(Check(f"Platform: {p}", OK, f"son yayin basarili ({_age(last['finished_at'], now)})"))
            else:
                res.append(Check(f"Platform: {p}", FAIL, f"son yayin basarisiz: {last['error'] or '?'}"))
        return res

    for name, fn in (("Veritabani", db), ("R2 deposu", store), ("GitHub", github),
                     ("Kosular", runs), ("Senaryo kuyrugu", queue), ("Arka plan isleri", worker),
                     ("Is durumu", work), ("Platformlar", platforms)):
        guard(name, fn)
    return out


def overall(checks: list[Check]) -> str:
    return max((c.status for c in checks), key=lambda s: RANK[s], default=OK)


class HealthMonitor:
    def __init__(self, svc, ttl: float = 60.0, clock=time.monotonic):
        self.svc, self.ttl, self._clock = svc, ttl, clock
        self.checks: list[Check] = []
        self.updated = None
        self._at = None

    def refresh(self) -> list[Check]:
        self.checks = run_checks(self.svc)
        self.updated = iso(self.svc.now())
        self._at = self._clock()
        return self.checks

    def get(self) -> list[Check]:
        if self._at is None or self._clock() - self._at > self.ttl:
            return self.refresh()
        return self.checks

    def cached(self) -> list[Check]:
        return self.checks
