"""
Takvim mantigi: SAF fonksiyonlar (veritabani, ag, sistem saati YOK; her sey parametre).

Saat dilimi: kayitlar UTC saklanir, kullaniciya ve girdilere Turkiye saati (sabit UTC+3,
yaz saati uygulamasi 2016'dan beri yok) gosterilir. Boylece tzdata paketine bagimlilik yok.

Disaridan gelen her metin (ay, gun, saat, haftalik sablon) burada dogrulanir ve gecersizse
ValueError firlatir; cagiran bunu kullaniciya gosterilebilir hataya cevirir.
"""
from __future__ import annotations

import calendar as _cal
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .db import parse_iso

TR = timezone(timedelta(hours=3))
UTC = timezone.utc
TIME_RX = re.compile(r"^([01]\d|2[0-3]):[0-5]\d\Z", re.ASCII)
MONTH_RX = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])\Z", re.ASCII)
DAY_RX = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\Z", re.ASCII)
# \d yalniz ASCII rakam (re.ASCII): tam genislikli/baska yazi sistemi rakamlari kabul edilmez
MAX_MONTHS = 36                       # bugunden en fazla +-3 yil
MAX_PER_DAY = 8                       # bir gunde en fazla bu kadar yayin saati
SHOWN_PER_DAY = 3                     # ay hucresinde gorunen etiket sayisi

WEEKDAYS = ("Pzt", "Sal", "Car", "Per", "Cum", "Cmt", "Paz")
MONTHS = ("Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran", "Temmuz", "Agustos", "Eylul",
          "Ekim", "Kasim", "Aralik")
ARM_LABELS = {"short": "K", "standard": "S"}


# ── zaman ────────────────────────────────────────────────────────────
def to_tr(dt: datetime) -> datetime:
    return dt.astimezone(TR)


def tr_to_utc(day: date, hhmm: str) -> datetime:
    if not TIME_RX.match(hhmm or ""):
        raise ValueError("Saat 'SS:DD' (24 saat, Turkiye saati) biciminde olmali")
    return datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[3:]), tzinfo=TR).astimezone(UTC)


def parse_day(text: str) -> date:
    m = DAY_RX.match((text or "").strip())
    if not m:
        raise ValueError("Tarih 'YYYY-AA-GG' biciminde olmali")
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        raise ValueError("Gecersiz tarih") from None


def parse_tr_datetime(text: str) -> datetime:
    """'YYYY-AA-GG SS:DD' ya da 'YYYY-AA-GGTSS:DD' (Turkiye saati) -> UTC."""
    s = (text or "").strip().replace("T", " ")
    parts = s.split(" ")
    if len(parts) != 2:
        raise ValueError("Zaman 'YYYY-AA-GG SS:DD' (Turkiye saati) biciminde olmali")
    return tr_to_utc(parse_day(parts[0]), parts[1])


def parse_month(text: str | None, today: date) -> tuple[int, int]:
    """'YYYY-AA' -> (yil, ay). Bos = bugunun ayi. Bugunden +-MAX_MONTHS ay disi reddedilir."""
    if not text:
        return today.year, today.month
    m = MONTH_RX.match(text.strip())
    if not m:
        raise ValueError("Ay 'YYYY-AA' biciminde olmali")
    y, mo = int(m[1]), int(m[2])
    if abs((y - today.year) * 12 + (mo - today.month)) > MAX_MONTHS:
        raise ValueError("Bu ay cok uzakta")
    return y, mo


def shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    i = y * 12 + (m - 1) + delta
    return i // 12, i % 12 + 1


def month_grid(y: int, m: int) -> list[list[date]]:
    """Pazartesi baslayan haftalar; ayi tamamen kapsar (disaridan gunlerle doldurulur)."""
    return [[d for d in week] for week in _cal.Calendar(firstweekday=0).monthdatescalendar(y, m)]


# ── haftalik sablon (Turkiye saati) ──────────────────────────────────
def parse_week(text: str) -> list[list[str]]:
    """'10:15,22:15|10:15,22:15|||...' (Pzt..Paz, '|' ile ayrili; bos = o gun yayin yok)."""
    parts = (text or "").split("|")
    if len(parts) != 7:
        raise ValueError("Haftalik sablon 7 gun icermeli (Pzt..Paz)")
    week = []
    for name, p in zip(WEEKDAYS, parts):
        times = sorted({t.strip() for t in p.split(",") if t.strip()})
        if len(times) > MAX_PER_DAY or not all(TIME_RX.match(t) for t in times):
            raise ValueError(f"{name}: saatler 'SS:DD,SS:DD' (Turkiye saati) biciminde olmali; "
                             f"en fazla {MAX_PER_DAY}")
        week.append(times)
    return week


def format_week(week: list[list[str]]) -> str:
    return "|".join(",".join(day) for day in week)


def week_is_configured(week: list[list[str]] | None) -> bool:
    return bool(week) and any(week)


def iter_slots(after: datetime, week: list[list[str]] | None, slots_utc: list[str], days: int = 400):
    """`after`'dan SONRAKI yayin saatlerini artan sirada (UTC, tz-aware) uretir.
    Haftalik sablon tanimliysa (Turkiye saati) o, yoksa slots_utc (her gun) kullanilir."""
    after = after.astimezone(UTC)
    if week_is_configured(week):
        start = to_tr(after).date()
        for d in range(days):
            day = start + timedelta(days=d)
            for hhmm in week[day.weekday()]:
                cand = tr_to_utc(day, hhmm)
                if cand > after:
                    yield cand
    else:
        start = after.date()
        for d in range(days):
            day = start + timedelta(days=d)
            for s in sorted(slots_utc):
                cand = datetime(day.year, day.month, day.day, int(s[:2]), int(s[3:]), tzinfo=UTC)
                if cand > after:
                    yield cand


# ── uretim kosulari ve kuyruk ────────────────────────────────────────
def predict_runs(after: datetime, runs_utc: list[str], until: datetime, queue: list[str],
                 limit: int = 800) -> list[dict]:
    """`after`'dan `until`'a kadarki daily kosulari; her birine kuyruktan siradaki senaryo atanir.
    Kuyruk biterse script_id None (= 'kuyruk bitti')."""
    after, until = after.astimezone(UTC), until.astimezone(UTC)
    out, qi = [], 0
    day = after.date()
    while len(out) < limit:
        for s in sorted(runs_utc):
            at = datetime(day.year, day.month, day.day, int(s[:2]), int(s[3:]), tzinfo=UTC)
            if at <= after:
                continue
            if at > until:
                return out
            out.append({"at": at, "script_id": queue[qi] if qi < len(queue) else None})
            qi += 1
        day += timedelta(days=1)
        if not runs_utc:
            break
    return out


def compute_queue(ids, done, order) -> list[str]:
    """tools/pick_script.py `queue()` ile AYNI kural: islenmemisler dosya adi sirasiyla, ama
    content/order.json'daki (islenmemis) idler once ve LISTE SIRASIYLA."""
    todo = sorted(set(ids) - set(done))
    present = set(todo)
    first: list[str] = []
    for sid in order:
        if sid in present and sid not in first:
            first.append(sid)
    taken = set(first)
    return first + [sid for sid in todo if sid not in taken]


def queue_days(left: int, runs_per_day: int) -> int:
    if runs_per_day <= 0:
        return 0
    return -(-max(left, 0) // runs_per_day)


def arm_label(arm: str) -> str:
    return ARM_LABELS.get(arm, (arm or "")[:1].upper())


# ── ay / gun modeli (sablon icin) ────────────────────────────────────
KIND_ORDER = {"pub": 0, "made": 1, "run": 2}


def _arm(info: dict | None) -> dict:
    info = info or {}
    return {"arm": info.get("label", ""), "arm_n": int(info.get("n", 0)), "arm_name": info.get("name", "")}


def events_for(pubs: list[dict], made: list[dict], runs: list[dict],
               arm_info: dict[str, dict]) -> dict[date, list[dict]]:
    """Yayinlar (pubs), uretilmis videolar (made), tahmini kosular (runs) -> Turkiye gunune gore."""
    by_day: dict[date, list[dict]] = defaultdict(list)
    for p in pubs:
        t = to_tr(parse_iso(p["scheduled_at"]))
        by_day[t.date()].append({
            "kind": "pub", "id": p["id"], "script_id": p["script_id"], "title": p["title"],
            "platform": p["platform"], "status": p["status"], "hhmm": f"{t:%H:%M}",
            "draggable": p["status"] == "planned", "error": p.get("error") or "",
            "remote_url": p.get("remote_url") or "", **_arm(arm_info.get(p["script_id"]))})
    for v in made:
        t = to_tr(parse_iso(v["rendered_at"]))
        by_day[t.date()].append({
            "kind": "made", "script_id": v["script_id"], "title": v["title"], "hhmm": f"{t:%H:%M}",
            "approval": v["approval"], **_arm(arm_info.get(v["script_id"]))})
    shown_empty = False
    for r in runs:
        t = to_tr(r["at"])
        sid = r["script_id"]
        if sid is None:                 # kuyruk bitti: yalniz ILK bos kosu gosterilir (takvimi kirmiziya boyama)
            if shown_empty:
                continue
            shown_empty = True
        by_day[t.date()].append({
            "kind": "run", "script_id": sid or "", "title": sid or "kuyruk bitti: uretim yok",
            "hhmm": f"{t:%H:%M}", "empty": sid is None, **_arm(arm_info.get(sid or ""))})
    for evs in by_day.values():
        evs.sort(key=lambda e: (KIND_ORDER[e["kind"]], e["hhmm"], e["title"]))
    return by_day


def build_month(y: int, m: int, today: date, pubs: list[dict], made: list[dict], runs: list[dict],
                arm_info: dict[str, dict]) -> dict:
    by_day = events_for(pubs, made, runs, arm_info)
    weeks = []
    for week in month_grid(y, m):
        row = []
        for d in week:
            ev = by_day.get(d, [])
            row.append({"date": d, "iso": d.isoformat(), "num": d.day, "in_month": d.month == m,
                        "today": d == today, "past": d < today, "events": ev,
                        "shown": ev[:SHOWN_PER_DAY], "more": max(0, len(ev) - SHOWN_PER_DAY),
                        "weekday": WEEKDAYS[d.weekday()]})
        weeks.append(row)
    py, pm = shift_month(y, m, -1)
    ny, nm = shift_month(y, m, 1)
    return {"year": y, "month": m, "title": f"{MONTHS[m - 1]} {y}", "weeks": weeks,
            "prev": f"{py:04d}-{pm:02d}", "next": f"{ny:04d}-{nm:02d}",
            "this": f"{y:04d}-{m:02d}", "weekdays": WEEKDAYS}


def grid_bounds_utc(y: int, m: int) -> tuple[datetime, datetime]:
    """Ay izgarasinin ilk gununun 00:00'i ile son gununun ertesi 00:00'i (Turkiye) -> UTC [bas, son)."""
    weeks = month_grid(y, m)
    return tr_to_utc(weeks[0][0], "00:00"), tr_to_utc(weeks[-1][-1] + timedelta(days=1), "00:00")


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    return tr_to_utc(day, "00:00"), tr_to_utc(day + timedelta(days=1), "00:00")


def day_times_tr(day: date, week: list[list[str]] | None, slots_utc: list[str]) -> list[str]:
    """O gun icin onerilen yayin saatleri (Turkiye): sablon varsa sablon, yoksa UTC saatlerinin TR karsiligi."""
    if week_is_configured(week):
        return list(week[day.weekday()])
    out = set()
    for s in slots_utc:
        t = datetime(day.year, day.month, day.day, int(s[:2]), int(s[3:]), tzinfo=UTC)
        out.add(f"{to_tr(t):%H:%M}")
    return sorted(out)
