"""
Senaryo ekleme (kolay form) icin PANEL TARAFI: formu okur, hizli on kontrol yapar, R2 kaydini kurar.

Yetkili kapi burada DEGIL: panel imajinda editorial/ kodu yok ve panel depoya yazamaz. Form R2'ye
(scripts-in/) konur, `panel-scripts` workflow'u (tools/panel_scripts.py) onu senaryoya cevirip AYNI
editor kapisindan gecirir (editorial/formscript.py + editorial/authored.py). Buradaki kontrol yalniz
"yanlis yazdin, 2 dakika beklemeden gor" icindir. Sinirlar editorial/rules.py ve formscript.py ile
AYNI olmali: tests/test_formscript.py ikisinin ayni kaldigini kilitliyor.

Yalniz standart kutuphane: Docker imajina ek bagimlilik girmez.
"""
from __future__ import annotations

import json
import re

IN_PREFIX, OUT_PREFIX = "scripts-in/", "scripts-out/"
MAX_RECORD = 64 * 1024
ACTIONS = ("ingest", "move_first", "remove")

# ── editorial/formscript.py ile ayni ─────────────────────────────────────
FORMATS = ("story", "measured", "explain")
THEMES = ("midnight", "ember", "deep", "moss", "slate", "plum", "rust", "ice")
MARKS = ("", "check", "x")
BEATS_MIN, BEATS_MAX = 10, 14
SOURCES_MIN, SOURCES_MAX = 2, 6
FACTS_MIN, FACTS_MAX = 2, 6
CALCS_MAX = 4
LIMIT = {"title": 60, "description": 400, "tag": 24, "say": 200, "cap": 48,
         "fact": 300, "note": 300, "url": 300}
TAGS_MAX = 5
# ── editorial/rules.py ile ayni ──────────────────────────────────────────
KW_MAX = 18
KW_OK = re.compile(r"^[A-Za-z0-9 .,%$€£#&@+=<>/\\:;?!()\[\]{}~^*_|'\"\-–—·×÷…°]+$")
MAX_BEAT_WORDS, MAX_HOOK_WORDS = 16, 12
WORDS_PER_SEC, GAP, MAX_SECONDS = 2.6, 0.18, 52
BANNED = [
    r"\bsubscribe\b", r"\blike and\b", r"\bfollow (me|us|for)\b",
    r"\blink in\b", r"\bcomment below\b", r"\bdon'?t forget\b",
    r"\blet me know\b", r"\bdid you know\b", r"\bimagine\b",
    r"\bwon'?t believe\b", r"\binsane\b", r"\bshocking\b", r"\bmind[- ]?blow",
    r"\bgame[- ]?changer\b", r"\byou should\b", r"\byou must\b",
    r"\bi recommend\b", r"\bbuy (this|it|now)\b", r"\bfinancial advice\b",
]
_BANNED = [re.compile(p, re.I) for p in BANNED]

# Formdaki sabit satir sayisi (JavaScript yok: bos satirlar atlanir)
BEAT_ROWS, SOURCE_ROWS, FACT_ROWS, CALC_ROWS = BEATS_MAX, SOURCES_MAX, FACTS_MAX, CALCS_MAX

CTRL = re.compile(r"[\x00-\x1f\x7f]")
URL = re.compile(r"^https://[^\s/]+\.[^\s/]+\S*$")
CALC_CHARS = re.compile(r"^[0-9+\-*/().,%\s×÷^−]+$")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})


def text(s, n: int) -> str:
    s = CTRL.sub(" ", str(s if s is not None else "")).translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip()[:n].strip()


# ── form <-> sozluk ──────────────────────────────────────────────────────
def blank_form() -> dict:
    return {"title": "", "format": "story", "theme": "", "tags": "", "description": "",
            "beats": [], "sources": [], "facts": [], "calcs": []}


def form_from_post(post) -> dict:
    """HTML formundan (alan adi + sira) sozluk. Fazla uzun metinler on kontrolde yakalansin diye bir
    karakter fazla tutulur; HER SEY burada kirpilir: ham girdi saklanmaz."""
    g = lambda k, n: text(post.get(k, ""), n)                      # noqa: E731
    form = {"title": g("title", LIMIT["title"] + 1), "format": g("format", 20) or "story",
            "theme": g("theme", 20), "tags": g("tags", 200), "description": g("description", LIMIT["description"] + 1),
            "beats": [], "sources": [], "facts": [], "calcs": []}
    for i in range(1, BEAT_ROWS + 1):
        row = {"say": g(f"say_{i}", LIMIT["say"] + 1), "cap": g(f"cap_{i}", LIMIT["cap"] + 1),
               "kw": g(f"kw_{i}", 40), "mark": g(f"mark_{i}", 10)}
        if any(row.values()):
            form["beats"].append(row)
    for i in range(1, SOURCE_ROWS + 1):
        u = g(f"src_{i}", LIMIT["url"] + 1)
        if u:
            form["sources"].append(u)
    for i in range(1, FACT_ROWS + 1):
        row = {"text": g(f"fact_text_{i}", LIMIT["fact"] + 1), "source": g(f"fact_src_{i}", 3),
               "note": g(f"fact_note_{i}", LIMIT["note"] + 1)}
        if any(row.values()):
            form["facts"].append(row)
    for i in range(1, CALC_ROWS + 1):
        row = {"shown": g(f"calc_shown_{i}", 30), "expr": g(f"calc_expr_{i}", 161)}
        if any(row.values()):
            form["calcs"].append(row)
    return form


def padded(form: dict) -> dict:
    """Sablon icin: her liste sabit satir sayisina bosla doldurulur."""
    f = dict(form)
    for key, n, empty in (("beats", BEAT_ROWS, {"say": "", "cap": "", "kw": "", "mark": ""}),
                          ("sources", SOURCE_ROWS, ""),
                          ("facts", FACT_ROWS, {"text": "", "source": "", "note": ""}),
                          ("calcs", CALC_ROWS, {"shown": "", "expr": ""})):
        rows = list(f.get(key) or [])[:n]
        f[key] = rows + [dict(empty) if isinstance(empty, dict) else empty for _ in range(n - len(rows))]
    return f


# ── on kontrol ───────────────────────────────────────────────────────────
def precheck(form) -> list[str]:
    """Hizli, YEREL kontrol (Turkce sorun listesi). Bos liste = gonderilebilir; kesin karar CI'daki kapida."""
    p: list[str] = []
    if not isinstance(form, dict):
        return ["form okunamadi"]
    title = form.get("title", "")
    if not title:
        p.append("Baslik bos.")
    elif len(title) > LIMIT["title"]:
        p.append(f"Baslik en fazla {LIMIT['title']} karakter olabilir.")
    if form.get("format") not in FORMATS:
        p.append("Bicim 'story', 'measured' ya da 'explain' olmali.")
    if form.get("theme", "") and form["theme"] not in THEMES:
        p.append("Bilinmeyen tema.")
    if len(form.get("description", "")) < 30:
        p.append("Aciklama (1-2 cumle) en az 30 karakter olmali.")
    tags = [t.strip() for t in re.split(r"[,\n]", str(form.get("tags", ""))) if t.strip()]
    if len(tags) > TAGS_MAX or any(len(t) > LIMIT["tag"] for t in tags):
        p.append(f"En fazla {TAGS_MAX} etiket, her biri en fazla {LIMIT['tag']} karakter.")

    beats = form.get("beats") or []
    if not BEATS_MIN <= len(beats) <= BEATS_MAX:
        p.append(f"{len(beats)} cumle yazmissin: {BEATS_MIN} ile {BEATS_MAX} arasi olmali.")
    words = 0
    for i, b in enumerate(beats, start=1):
        say, cap, kw, mark = b.get("say", ""), b.get("cap", ""), b.get("kw", ""), b.get("mark", "")
        who = f"Cumle {i}"
        if not say:
            p.append(f"{who}: 'Okunacak cumle' bos.")
            continue
        if not cap:
            p.append(f"{who}: 'Ekran yazisi' bos.")
        if len(say) > LIMIT["say"] or len(cap) > LIMIT["cap"]:
            p.append(f"{who}: cumle ya da ekran yazisi cok uzun (ekran yazisi en fazla {LIMIT['cap']} karakter).")
        n = len(say.split())
        words += n
        if n > MAX_BEAT_WORDS:
            p.append(f"{who}: {n} kelime, en fazla {MAX_BEAT_WORDS} olabilir.")
        if re.search(r"https?://|[\[\]{}]", cap + say):
            p.append(f"{who}: metinde baglanti ya da parantez var.")
        if re.search(r"\d", say):
            p.append(f"{who}: okunacak cumlede rakam var; yazi ile yaz ('three dollars'). Rakam yalniz ekran yazisinda.")
        if any(rx.search(say) or rx.search(cap) for rx in _BANNED):
            p.append(f"{who}: yasakli kalip (begen/abone ol, 'did you know', 'imagine' gibi).")
        if kw:
            if len(kw) > KW_MAX:
                p.append(f"{who}: vurgulu kelime en fazla {KW_MAX} karakter.")
            elif not KW_OK.match(kw):
                p.append(f"{who}: vurgulu kelimede desteklenmeyen karakter var (harf, rakam ve . , % $ + - : ? ! olur).")
            elif kw.lower() not in cap.lower():
                p.append(f"{who}: vurgulu kelime, ekran yazisinin icinden AYNEN alinmali.")
        if mark not in MARKS:
            p.append(f"{who}: isaret bos, 'check' ya da 'x' olmali.")
        elif mark and not kw:
            p.append(f"{who}: isaret icin vurgulu kelime gerekli.")
    if beats:
        first = (beats[0].get("say", "")).split()
        if len(first) > MAX_HOOK_WORDS:
            p.append(f"Ilk cumle (kanca) {len(first)} kelime, en fazla {MAX_HOOK_WORDS} olabilir.")
        if first and first[-1].endswith("?"):
            p.append("Ilk cumle soru olmamali; sasirtici bir olgu olmali.")
        est = words / WORDS_PER_SEC + GAP * (len(beats) - 1)
        if est > MAX_SECONDS:
            p.append(f"Tahmini sure {est:.0f} sn, en fazla {MAX_SECONDS} sn olmali ({words} kelime): cumleleri kisalt.")

    srcs = form.get("sources") or []
    if not SOURCES_MIN <= len(srcs) <= SOURCES_MAX:
        p.append(f"{len(srcs)} kaynak yazmissin: {SOURCES_MIN} ile {SOURCES_MAX} arasi olmali.")
    for s in srcs:
        if len(s) > LIMIT["url"] or not URL.match(s):
            p.append(f"Kaynak 'https://' ile baslayan bir internet adresi olmali: {s[:50]}")
    if len(set(srcs)) != len(srcs):
        p.append("Ayni kaynak iki kez yazilmis.")

    facts = form.get("facts") or []
    if not FACTS_MIN <= len(facts) <= FACTS_MAX:
        p.append(f"{len(facts)} dogrulanan olay yazmissin: {FACTS_MIN} ile {FACTS_MAX} arasi olmali.")
    used = set()
    for i, x in enumerate(facts, start=1):
        if not x.get("text"):
            p.append(f"Olay {i}: metin bos.")
        if not x.get("note"):
            p.append(f"Olay {i}: 'sayfa ne diyor' notu bos.")
        src = str(x.get("source", ""))
        if not re.fullmatch(r"[1-9]\d?", src) or not 1 <= int(src) <= max(len(srcs), 1):
            p.append(f"Olay {i}: kaynak no 1 ile {len(srcs)} arasi olmali.")
        else:
            used.add(int(src))
    for i in range(1, len(srcs) + 1):
        if facts and i not in used:
            p.append(f"Kaynak {i} hicbir olayda kullanilmiyor: ya bir olaya bagla ya da kaldir.")

    calcs = form.get("calcs") or []
    if len(calcs) > CALCS_MAX:
        p.append(f"En fazla {CALCS_MAX} hesap satiri.")
    for i, c in enumerate(calcs, start=1):
        if not re.fullmatch(r"-?\d[\d,]*(\.\d+)?", c.get("shown", "")) or not CALC_CHARS.match(c.get("expr", "")) \
                or len(c.get("expr", "")) > 160:
            p.append(f"Hesap {i}: ekrandaki sayi bir rakam, hesap de yalniz sayi ve + - * / ** ( ) olmali.")
    return p


def estimate(form: dict) -> dict:
    """Formun yaklasik suresi (canli on izleme): {words, seconds}."""
    beats = form.get("beats") or []
    words = sum(len(str(b.get("say", "")).split()) for b in beats)
    return {"words": words, "seconds": round(words / WORDS_PER_SEC + GAP * max(len(beats) - 1, 0))}


# ── R2 kayitlari ─────────────────────────────────────────────────────────
def request_record(rid: str, form: dict, at: str) -> bytes:
    rec = {"v": 1, "request_id": rid, "action": "new", "at": at, "form": form}
    data = json.dumps(rec, ensure_ascii=False).encode()
    if len(data) > MAX_RECORD:
        raise ValueError("form cok buyuk")
    return data


def parse_result(raw: bytes) -> dict:
    """tools/panel_scripts.py'nin yazdigi scripts-out/<istek>.json. Gelen veri DIS DUNYADAN sayilir."""
    d = json.loads(raw)
    if not isinstance(d, dict) or d.get("v") != 1:
        raise ValueError("v=1 degil")
    rid = d.get("request_id")
    if not isinstance(rid, str) or not re.fullmatch(r"[a-f0-9]{32}", rid):
        raise ValueError("request_id gecersiz")
    status = d.get("status")
    if status not in ("ok", "rejected", "error"):
        raise ValueError("status gecersiz")
    problems = [text(x, 300) for x in (d.get("problems") if isinstance(d.get("problems"), list) else [])][:20]
    return {"request_id": rid, "status": status, "action": text(d.get("action", ""), 20),
            "script_id": text(d.get("script_id", ""), 80), "title": text(d.get("title", ""), 120),
            "message": text(d.get("message", ""), 300), "problems": [x for x in problems if x]}
