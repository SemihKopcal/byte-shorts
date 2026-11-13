"""
Kolay form -> senaryo. Panelin "Yeni hikaye" formu buradaki sekle uygun bir sozluk gonderir
(baslik, cumleler, kaynaklar, olay satirlari); bu modul onu content/scripts/<id>.json
senaryosuna cevirir: id, roller, sahneler, sayi iddialari, yayin metni.

KAPI DEGISMEZ: sonuc yine editorial.authored.problems'ten gecmek zorunda
(tools/panel_scripts.py bunu calistirir). Burada yalniz "forma bak, iskeleti kur" var;
sure, sahne bicimi, yasak kalip, aritmetik denetimi rules.py'de kaldi.

Yazarin (Semih'in) yapacagi sey: 10-14 cumle + kaynaklar + her rakamin hangi sayfada
yazdigini soyleyen olay satirlari. Sahne secimi sezgisel ve DETERMINISTIK (ayni form her
zaman ayni senaryo):
  * ilk cumle  -> title, son cumle -> close
  * "$1.65 billion", "100M+" gibi birim/buyuk sayi -> counter (en cok 2)
  * 3+ cumlede yil/tarih varsa -> timeline
  * kalan bosluklar (3 cumleden uzun sahnesiz kesit) -> steps / flow / checklist
"""
from __future__ import annotations

import json
import re
import unicodedata

from . import rules

FORMATS = ("story", "measured", "explain")
THEMES = ("midnight", "ember", "deep", "moss", "slate", "plum", "rust", "ice")
MARKS = ("", "check", "x")
BEATS_MIN, BEATS_MAX = 10, 14
SOURCES_MIN, SOURCES_MAX = 2, 6
FACTS_MIN, FACTS_MAX = 2, 6
CALCS_MAX = 4
TAGS_MAX = 5
MAX_STATIC = 3                      # arka arkaya en fazla bu kadar cumle ayni sahnede kalsin
LIMIT = {"title": 60, "description": 400, "tag": 24, "say": 200, "cap": 48,
         "fact": 300, "note": 300, "url": 300}

KICKER = {"story": "True story", "measured": "Measured", "explain": "Explained"}
URL = re.compile(r"^https://[^\s/]+\.[^\s/]+\S*$")
CTRL = re.compile(r"[\x00-\x1f\x7f]")
HASHTAG_BODY = re.compile(r"[^A-Za-z0-9]")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})

MONTHS = {"jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr", "may": "May", "jun": "Jun",
          "jul": "Jul", "aug": "Aug", "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec"}
_DATE = re.compile(r"\b(?:(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?"
                   r"(?:(?P<day>\d{1,2}),?\s+)?(?P<year>(?:19|20)\d{2})\b")
_NUMTOK = re.compile(r"(?P<prefix>[$€£])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                     r"(?P<unit>\s?(?:million|billion|trillion|thousand)\b|[KMBkmb]\b|%)?(?P<plus>\+)?")


def text(s, n: int) -> str:
    """Kontrol karakterlerini at, bosluklari tek yap, tipografik tirnaklari duzelt, n'e kes."""
    s = CTRL.sub(" ", str(s if s is not None else "")).translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip()[:n].strip()


def short(s: str, n: int) -> str:
    """Kelime sinirinda kisalt (rakami ortasindan kesme); sondaki noktalama atilir."""
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s.rstrip(" ,;:-")
    cut = s[:n]
    if s[n] != " " and " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:-")


def slugify(title: str, limit: int = 40) -> str:
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    if len(s) > limit:
        s = s[:limit]
        if "-" in s:
            s = s[:s.rindex("-")]
    return s.strip("-") or "story"


# ── formu temizle ve denetle ─────────────────────────────────────────────
def normalize_form(raw) -> tuple[dict | None, list[str]]:
    """Ham formu temizler. (temiz form, sorunlar); sorun varsa form None."""
    p: list[str] = []
    if not isinstance(raw, dict):
        return None, ["form bir nesne olmali"]
    f: dict = {}
    f["title"] = text(raw.get("title"), LIMIT["title"] + 1)
    if not f["title"]:
        p.append("baslik bos")
    elif len(f["title"]) > LIMIT["title"]:
        p.append(f"baslik en fazla {LIMIT['title']} karakter")
    f["format"] = text(raw.get("format"), 20) or "story"
    if f["format"] not in FORMATS:
        p.append("bicim story, measured ya da explain olmali")
    f["theme"] = text(raw.get("theme"), 20)
    if f["theme"] and f["theme"] not in THEMES:
        p.append("bilinmeyen tema")
    tags = raw.get("tags", "")
    tags = re.split(r"[,\n]", tags) if isinstance(tags, str) else tags if isinstance(tags, list) else []
    f["tags"] = [t for t in (text(x, LIMIT["tag"]) for x in tags) if t][:TAGS_MAX]
    f["description"] = text(raw.get("description"), LIMIT["description"])
    if len(f["description"]) < 30:
        p.append("aciklama (1-2 cumle) en az 30 karakter olmali")

    beats = []
    for i, b in enumerate(raw.get("beats") if isinstance(raw.get("beats"), list) else [], start=1):
        if not isinstance(b, dict):
            continue
        say, cap = text(b.get("say"), LIMIT["say"] + 1), text(b.get("cap"), LIMIT["cap"] + 1)
        kw, mark = text(b.get("kw"), 40), text(b.get("mark"), 10)
        if not (say or cap or kw):
            continue
        if not say:
            p.append(f"cumle {i}: seslendirilecek metin (say) bos")
        if not cap:
            p.append(f"cumle {i}: ekran yazisi (cap) bos")
        if len(say) > LIMIT["say"]:
            p.append(f"cumle {i}: say cok uzun")
        if len(cap) > LIMIT["cap"]:
            p.append(f"cumle {i}: ekran yazisi en fazla {LIMIT['cap']} karakter")
        if mark not in MARKS:
            p.append(f"cumle {i}: isaret '' | check | x olmali")
        beats.append({"say": say, "cap": cap, "kw": kw, "mark": mark})
    if not BEATS_MIN <= len(beats) <= BEATS_MAX:
        p.append(f"{len(beats)} cumle: {BEATS_MIN}-{BEATS_MAX} arasi olmali")
    f["beats"] = beats

    srcs = [text(s, LIMIT["url"] + 1) for s in (raw.get("sources") if isinstance(raw.get("sources"), list) else [])]
    srcs = [s for s in srcs if s]
    if not SOURCES_MIN <= len(srcs) <= SOURCES_MAX:
        p.append(f"{len(srcs)} kaynak: {SOURCES_MIN}-{SOURCES_MAX} arasi olmali")
    for s in srcs:
        if len(s) > LIMIT["url"] or not URL.match(s):
            p.append(f"kaynak https:// ile baslayan bir adres olmali: {s[:60]!r}")
    if len(set(srcs)) != len(srcs):
        p.append("kaynaklar tekrar ediyor")
    f["sources"] = srcs

    facts = []
    for i, x in enumerate(raw.get("facts") if isinstance(raw.get("facts"), list) else [], start=1):
        if not isinstance(x, dict):
            continue
        claim, note = text(x.get("text"), LIMIT["fact"] + 1), text(x.get("note"), LIMIT["note"] + 1)
        src_raw = str(x.get("source", "")).strip()
        if not (claim or note or src_raw):
            continue
        if not claim:
            p.append(f"olay {i}: metin bos")
        if not note:
            p.append(f"olay {i}: 'sayfa ne diyor' notu bos")
        if len(claim) > LIMIT["fact"] or len(note) > LIMIT["note"]:
            p.append(f"olay {i}: metin cok uzun")
        if not re.fullmatch(r"[1-9]\d?", src_raw) or not 1 <= int(src_raw) <= max(len(srcs), 1):
            p.append(f"olay {i}: kaynak no 1-{len(srcs)} arasi olmali")
            src = 0
        else:
            src = int(src_raw)
        facts.append({"text": claim, "source": src, "note": note})
    if not FACTS_MIN <= len(facts) <= FACTS_MAX:
        p.append(f"{len(facts)} dogrulanan olay: {FACTS_MIN}-{FACTS_MAX} arasi olmali")
    f["facts"] = facts

    calcs = []
    for i, x in enumerate(raw.get("calcs") if isinstance(raw.get("calcs"), list) else [], start=1):
        if not isinstance(x, dict):
            continue
        shown, expr = text(x.get("shown"), 30), text(x.get("expr"), 160)
        if not (shown or expr):
            continue
        try:
            value = float(shown.replace(",", ""))
            got = rules.safe_eval(expr)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
            p.append(f"hesap {i}: ekrandaki sayi bir rakam, hesap de gecerli bir islem olmali "
                     "(yalniz sayi ve + - * / ** parantez)")
            continue
        if abs(got - value) > max(abs(value) * 0.015, 0.006):
            p.append(f"hesap {i}: {expr} = {got:g} ama ekrandaki sayi {shown}")
            continue
        calcs.append({"shown": shown, "expr": expr, "value": value})
    if len(calcs) > CALCS_MAX:
        p.append(f"en fazla {CALCS_MAX} hesap")
    f["calcs"] = calcs
    return (None, p) if p else (f, [])


# ── sahne yapitasi ───────────────────────────────────────────────────────
def date_label(cap: str):
    """Cap'teki ilk tarih -> ('Feb 14, 2005', (basla, bitis)) ya da None. En fazla 12 karakter."""
    m = _DATE.search(cap)
    if not m:
        return None
    mon = MONTHS.get((m.group("mon") or "").lower()[:3])
    day = f"{int(m.group('day'))}, " if mon and m.group("day") else ""
    return (f"{mon} {day}{m.group('year')}" if mon else m.group("year")), m.span()


def counter_token(cap: str):
    """Cap'te sayac olacak kadar belirgin ilk sayi -> (counter data'si, guclu mu) ya da None.
    Tarihin icindeki gun/yil sayilmaz; birimi ya da simgesi olan sayi (guclu) once gelir."""
    dates = [m.span() for m in _DATE.finditer(cap)]
    for m in _NUMTOK.finditer(cap):
        if any(a <= m.start() < b for a, b in dates):
            continue
        raw = m.group("num")
        value = float(raw.replace(",", ""))
        unit, plus, prefix = m.group("unit") or "", m.group("plus") or "", m.group("prefix") or ""
        strong = bool(unit or prefix or plus)
        year_like = value == int(value) and 1900 <= value <= 2100 and not strong
        if year_like or not (strong or value > 10):
            continue
        dp = len(raw.split(".")[1]) if "." in raw else 0
        note = short((cap[:m.start()] + " " + cap[m.end():]).strip(" ,;:-"), 36)
        data = {"from": 0, "to": int(value) if dp == 0 else value, "dp": dp}
        if prefix:
            data["prefix"] = prefix
        if unit or plus:
            data["suffix"] = unit + plus
        if note:
            data["note"] = note
        return data, strong
    return None


def _title_lines(cap: str) -> list[str]:
    if len(cap) <= 24 or " " not in cap:
        return [cap]
    words, best, mid = cap.split(), None, len(cap) / 2
    for i in range(1, len(words)):
        a = " ".join(words[:i])
        if best is None or abs(len(a) - mid) < abs(len(best) - mid):
            best = a
    return [best, cap[len(best):].strip()]


def _filler(kind: str, caps: list[str]) -> dict:
    """steps | flow | checklist: onceki cumlelerin ekran yazilarini toplar."""
    if kind == "flow":
        last = caps[-2:] if len(caps) >= 2 else caps * 2
        nodes = [{"label": short(c, 26) or "Step"} for c in last]
        nodes[-1]["tone"] = "good"
        return {"scene": "flow", "data": {"nodes": nodes}}
    if kind == "checklist":
        return {"scene": "checklist", "data": {"rows": [{"text": short(c, 34) or "Done", "ok": True}
                                                         for c in caps[-3:]]}}
    return {"scene": "steps", "data": {"steps": [{"label": short(c, 34) or "Step"} for c in caps[-3:]]}}


def plan_scenes(beats: list[dict], fmt: str) -> dict[int, dict]:
    """{cumle sirasi: {"scene","data"}}. Deterministik; kurallar rules.validate_script'te dogrulanir."""
    n = len(beats)
    caps = [b["cap"] for b in beats]
    out: dict[int, dict] = {
        0: {"scene": "title", "data": {"kicker": KICKER.get(fmt, ""), "lines": _title_lines(caps[0])}},
        n - 1: {"scene": "close", "data": {"lines": [short(c, 30) for c in caps[max(0, n - 2):]]
                                           or [short(caps[-1], 30)], "accent": "good"}},
    }
    middle = range(1, n - 1)
    # sayaclar: birimli sayilar once; ilk ve (aralarinda en az 3 cumle varsa) son
    found = [(i, t) for i in middle if (t := counter_token(caps[i]))]
    pool = [(i, d) for i, (d, strong) in found if strong] or [(i, d) for i, (d, _) in found]
    pick = pool[:1]
    if len(pool) >= 2 and pool[-1][0] - pool[0][0] >= 3:
        pick.append(pool[-1])
    for i, d in pick:
        out[i] = {"scene": "counter", "data": d}
    # zaman cizelgesi: 3+ cumlede tarih
    dated = [(i, date_label(caps[i])) for i in middle if i not in out]
    dated = [(i, d) for i, d in dated if d][:5]
    if len(dated) >= 3:
        steps = []
        for i, (lab, (a, b)) in dated:
            label = short((caps[i][:a] + " " + caps[i][b:]).strip(" ,;:-"), 26) or short(caps[i], 26)
            steps.append({"at": lab, "label": label})
        steps[-1]["tone"] = "good"
        out[dated[-1][0]] = {"scene": "timeline", "data": {"steps": steps}}
    # bosluklar: ayni sahnede cok uzun kalma
    kinds, k = ("steps", "flow", "checklist"), 0
    cur = 0
    while True:
        later = [i for i in sorted(out) if i > cur]
        nxt = later[0] if later else n
        if nxt - cur > MAX_STATIC and cur + MAX_STATIC < n - 1:
            at = cur + MAX_STATIC
            out[at] = _filler(kinds[k % 3], caps[max(0, at - 2):at + 1])
            k += 1
            cur = at
        elif later:
            cur = nxt
        else:
            break
    return out


# ── iddialar ─────────────────────────────────────────────────────────────
def _num_text(v: float) -> str:
    s = format(v, "f").rstrip("0").rstrip(".")
    return s or "0"


def derive_claims(spec: dict, facts: list[dict], calcs: list[dict] | None = None
                  ) -> tuple[list[dict], list[str]]:
    """Ekrandaki her anlamli sayi icin iddia uretir: once yazarin hesap satirlari (kod hesaplar),
    kalanlar icin o rakami iceren bir olay satirindan (kaynak + not)."""
    claims, problems, seen = [], [], []
    for c in calcs or []:
        claims.append({"shown": c["shown"], "expr": c["expr"], "value": c["value"], "source": None})
        seen += rules._nums(c["shown"])
    for v in rules.screen_numbers(spec):
        if any(rules._same(v, s) for s in seen):
            continue
        seen.append(v)
        hit = next((x for x in facts if any(rules._same(v, n) for n in rules._nums(x["text"]))), None)
        if hit is None:
            problems.append(f"ekranda {_num_text(v)} gorunuyor ama 'dogrulanan olay' satirlarinin hicbirinde bu "
                            "rakam yok: rakami iceren olayi rakamla yaz (ornek: '100 million', '$1.65 billion')")
            continue
        claims.append({"shown": _num_text(v), "expr": None, "value": None,
                       "source": hit["source"] - 1, "note": hit["note"]})
    return claims, problems


# ── hashtag ve yayin metni ───────────────────────────────────────────────
def hashtags(tags: list[str]) -> dict[str, list[str]]:
    out = ["#tech"]
    for t in tags:
        h = "#" + HASHTAG_BODY.sub("", t).lower()
        if re.fullmatch(r"#[a-z][a-z0-9]{1,29}", h) and h not in out:
            out.append(h)
    return {"youtube": out[:4], "instagram": out[:3], "tiktok": out[:2]}


def first_sentences(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    cut = s[:n]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > 40 else short(s, n)


# ── ana cevirici ─────────────────────────────────────────────────────────
def compile_form(form, number: int, today: str) -> tuple[dict | None, list[str]]:
    """(senaryo, sorunlar). Sorun varsa senaryo None. Sorunsuz cikmasi KAPIDAN gececegi anlamina
    gelmez: tools/panel_scripts.py ayrica editorial.authored.problems calistirir."""
    f, p = normalize_form(form)
    if p or f is None:
        return None, p
    if not 1 <= number <= 999:
        return None, ["senaryo numarasi 1-999 disina cikti"]
    beats = f["beats"]
    n = len(beats)
    roles = ["hook"] + ["why"] * 2 + ["data"] * (n - 7) + ["turn"] * 2 + ["resolve"] * 2
    scenes = plan_scenes(beats, f["format"])
    out_beats = []
    for i, b in enumerate(beats):
        item = {"id": f"b{i + 1}", "role": roles[i], "say": b["say"], "cap": b["cap"]}
        if b["kw"]:
            item["kw"] = b["kw"]
        if b["mark"]:
            item["mark"] = b["mark"]
        if i in scenes:
            item.update(scenes[i])
        out_beats.append(item)

    theme = f["theme"] or THEMES[sum(map(ord, f["title"])) % len(THEMES)]
    desc = f["description"]
    spec = {
        "id": f"p{number:03d}-{slugify(f['title'])}",
        "series": "G", "lang": "en", "format": f["format"], "theme": theme,
        "title": f["title"], "summary": desc,
        "tags": f["tags"] or [f["format"]],
        "sources": list(f["sources"]),
        "beats": out_beats,
    }
    claims, cp = derive_claims(spec, f["facts"], f["calcs"])
    problems = list(cp)
    used = {x["source"] - 1 for x in f["facts"]}
    for i, s in enumerate(f["sources"]):
        if i not in used:
            problems.append(f"kaynak {i + 1} hicbir olay satirinda kullanilmiyor: {s[:70]}")
    if problems:
        return None, problems
    spec["claims"] = claims
    spec["facts"] = [{"claim": x["text"], "source": x["source"] - 1, "note": x["note"]} for x in f["facts"]]
    tags = hashtags(f["tags"])
    spec["copy_parts"] = {"youtube": {"hook": desc},
                          "instagram": {"caption": first_sentences(desc, 240)},
                          "tiktok": {"caption": f["title"]},
                          "hashtags": tags}
    spec["authored"] = {"by": "panel", "date": today}
    return spec, []


def dumps(spec: dict) -> str:
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
