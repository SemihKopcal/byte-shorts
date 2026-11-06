"""
Deterministik kurallar. Burada Gemini YOK: ayni girdi her zaman ayni cevabi
verir ve testleri agsiz calisir.

Gemini'nin yazdigini Gemini'nin kendisine "iyi mi?" diye sormak yetmez; bir
model kendi hatasini ayni hatayla onaylayabilir. Kodun kesin olarak
bilebildigi seyleri (sahne adi, sure, aritmetik, hashtag sayisi) kod
kontrol ediyor; yargi gerektirenleri (kanca, anlati, risk) editor rolu.
"""
import ast
import math
import operator
import re
from dataclasses import dataclass, field

ROLES = ("hook", "why", "data", "turn", "resolve")
FORMATS = ("measured", "story", "explain", "trend")
NEEDS_FACTS = {"story": 2, "trend": 2}        # bicim -> en az listelenen olay iddiasi
MAX_FACTS = 8
POSES = ("idle", "point_r", "point_l", "point_up", "shrug", "alert")
CURSORS = ("mint", "amber", "red", "violet")
SCORE_KEYS = ("hook", "story", "clarity", "audience", "voice")

WORDS_PER_SEC = 2.6          # Piper en-us-ryan-high, olculmus
GAP = 0.18
MAX_SECONDS = 52             # QC esigi 59; burada pay birakiyoruz
MAX_BEAT_WORDS = 16
MAX_HOOK_WORDS = 12

# Kanalin sesine yakismayan kaliplar: harekete cagri, soru, abartı, tavsiye.
BANNED = [
    r"\bsubscribe\b", r"\blike and\b", r"\bfollow (me|us|for)\b",
    r"\blink in\b", r"\bcomment below\b", r"\bdon'?t forget\b",
    r"\blet me know\b", r"\bdid you know\b", r"\bimagine\b",
    r"\bwon'?t believe\b", r"\binsane\b", r"\bshocking\b", r"\bmind[- ]?blow",
    r"\bgame[- ]?changer\b", r"\byou should\b", r"\byou must\b",
    r"\bi recommend\b", r"\bbuy (this|it|now)\b", r"\bfinancial advice\b",
]
_BANNED = [re.compile(p, re.I) for p in BANNED]


# ── senaryo ──────────────────────────────────────────────────────────────
def _shape(scene: str, data: dict, who: str) -> list[str]:
    """Sahnenin data'si cizimi KIRACAK sekilde mi bozuk? Render ~3 dakika
    suruyor; burada yakalamak o suredenn once yakalamak demek."""
    p: list[str] = []
    if not isinstance(data, dict):
        return [f"{who}: data bir nesne olmali"]

    def lst(key, lo, hi):
        v = data.get(key)
        if not isinstance(v, list) or not lo <= len(v) <= hi:
            p.append(f"{who} ({scene}): {key} listesi {lo}..{hi} oge olmali")
            return []
        return v

    if scene == "title":
        lst("lines", 1, 3)
    elif scene == "contrast":
        for side in ("left", "right"):
            it = data.get(side)
            if not isinstance(it, dict) or not it.get("value"):
                p.append(f"{who} (contrast): {side}.value yok")
    elif scene == "table":
        for r in lst("rows", 1, 6):
            if not isinstance(r, dict) or not r.get("name") or "value" not in r:
                p.append(f"{who} (table): satirda name/value yok")
            elif not isinstance(r.get("ratio", 1), (int, float)):
                p.append(f"{who} (table): ratio sayi olmali")
    elif scene == "bars":
        for r in lst("rows", 1, 5):
            if not isinstance(r, dict) or not isinstance(r.get("v"), (int, float)):
                p.append(f"{who} (bars): satirda sayisal v yok")
    elif scene == "counter":
        for k in ("from", "to"):
            if not isinstance(data.get(k), (int, float)):
                p.append(f"{who} (counter): {k} sayi olmali")
    elif scene == "split":
        for k in ("a", "b"):
            if not isinstance(data.get(k), dict) or not data[k].get("label"):
                p.append(f"{who} (split): {k}.label yok")
    elif scene == "timeline":
        for s in lst("steps", 1, 5):
            if not isinstance(s, dict) or not s.get("label"):
                p.append(f"{who} (timeline): adimda label yok")
    elif scene == "byte_says":
        if data.get("pose", "idle") not in POSES:
            # cizim burada KeyError ile coker
            p.append(f"{who}: bilinmeyen pose {data.get('pose')!r} "
                     f"({'|'.join(POSES)})")
        if data.get("cursor", "mint") not in CURSORS:
            p.append(f"{who}: bilinmeyen cursor {data.get('cursor')!r}")
    elif scene == "close":
        if not (data.get("lines") or data.get("line")):
            p.append(f"{who} (close): lines yok")
    return p


def validate_script(spec: dict, scene_names) -> list[str]:
    """Dosyaya yazmadan once. Bos liste = temiz."""
    p: list[str] = []
    for k in ("title", "beats", "sources"):
        if not spec.get(k):
            p.append(f"eksik alan: {k}")
    if p:
        return p

    if len(spec["sources"]) < 2:
        p.append("en az 2 kaynak gerekiyor")

    if spec.get("format") not in FORMATS:
        p.append('"format" must be exactly one of: ' + ", ".join(FORMATS))

    beats = spec["beats"]
    if not isinstance(beats, list) or not 10 <= len(beats) <= 18:
        return p + [f"{len(beats) if isinstance(beats, list) else '?'} beat "
                    "-- 10..18 arasi olmali"]

    words, scenes, roles = 0, [], []
    for i, b in enumerate(beats):
        if not isinstance(b, dict):
            p.append(f"#{i}: beat bir nesne olmali")
            continue
        who = b.get("id", f"#{i}")
        say, cap = b.get("say") or "", b.get("cap") or ""
        if not say:
            p.append(f"{who}: say yok")
            continue
        n = len(say.split())
        words += n
        if n > MAX_BEAT_WORDS:
            p.append(f"{who}: {n} kelime, cok uzun (en fazla {MAX_BEAT_WORDS})")
        if not cap:
            p.append(f"{who}: cap yok")
        if re.search(r"https?://|[\[\]{}]", cap + say):
            p.append(f"{who}: metinde URL/parantez var")
        if re.search(r"\d", say):
            p.append(f"{who}: say icinde rakam var -- sesli okunacak sekilde "
                     "yaz (\"three dollars\"); rakam sadece cap'te")
        for rx in _BANNED:
            if rx.search(say) or rx.search(cap):
                p.append(f"{who}: yasakli kalip {rx.pattern!r}")
                break
        s = b.get("scene")
        if s:
            if s not in scene_names:
                p.append(f"{who}: bilinmeyen sahne {s!r}")
            else:
                scenes.append(s)
                p += _shape(s, b.get("data") or {}, who)
        r = b.get("role")
        if r not in ROLES:
            p.append(f"{who}: role {r!r} gecersiz ({'|'.join(ROLES)})")
        else:
            roles.append(r)

    if len(set(scenes)) < 4:
        p.append(f"{len(set(scenes))} farkli sahne -- en az 4 olmali")
    if scenes and scenes[0] not in ("title", "contrast"):
        p.append("ilk sahne 'title' ya da 'contrast' olmali")
    if scenes and scenes[-1] != "close":
        p.append("son sahne 'close' olmali")

    # anlati: hook -> why -> data -> turn -> resolve, o sirayla
    if len(roles) == len(beats):
        idx = [ROLES.index(r) for r in roles]
        if idx != sorted(idx):
            p.append("role'ler sirali degil: hook, why, data, turn, resolve")
        for r in ROLES:
            if r not in roles:
                p.append(f"role eksik: {r}")
        if roles and roles[0] != "hook":
            p.append("ilk beat 'hook' olmali")
        if roles and roles[-1] != "resolve":
            p.append("son beat 'resolve' olmali")
        if roles.count("hook") != 1:
            p.append("tam 1 tane hook beat'i olmali")
    first = (beats[0].get("say") or "").split() if isinstance(beats[0], dict) else []
    if len(first) > MAX_HOOK_WORDS:
        p.append(f"hook {len(first)} kelime -- en fazla {MAX_HOOK_WORDS}")
    if first and first[-1].endswith("?"):
        p.append("hook soru olmamali; sasirtici bir olgu olmali")

    est = words / WORDS_PER_SEC + GAP * (len(beats) - 1)
    if est > MAX_SECONDS:
        p.append(f"tahmini sure {est:.0f}s > {MAX_SECONDS}s ({words} kelime)")

    ids = [b.get("id") for b in beats if isinstance(b, dict)]
    if len(set(ids)) != len(ids):
        p.append("beat id'leri tekrar ediyor")
    return p


# ── aritmetik ────────────────────────────────────────────────────────────
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv, ast.Pow: operator.pow}


def safe_eval(expr: str) -> float:
    """Sadece sayi ve + - * / % ** ( ). eval() DEGIL: Gemini'nin yazdigi
    metni calistiriyoruz, bu yuzden ifade agaci yuruyup izin verilmeyen her
    dugumde duruyor."""
    if not isinstance(expr, str) or len(expr) > 160:
        raise ValueError("ifade yok ya da cok uzun")
    e = (expr.replace("×", "*").replace("÷", "/").replace("^", "**")
             .replace("−", "-").replace(",", "").replace("$", "")
             .replace("%", "/100"))
    tree = ast.parse(e.strip(), mode="eval")

    def go(n):
        if isinstance(n, ast.Expression):
            return go(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = go(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = go(n.left), go(n.right)
            if isinstance(n.op, ast.Pow) and (abs(b) > 20 or abs(a) > 1e9):
                raise ValueError("us cok buyuk")
            return _OPS[type(n.op)](a, b)
        raise ValueError(f"izin verilmeyen ifade: {type(n).__name__}")

    out = float(go(tree))
    if not math.isfinite(out):
        raise ValueError("sonuc sonlu degil")
    return out


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _nums(text: str) -> list[float]:
    out = []
    for m in _NUM.findall(text or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def screen_numbers(spec: dict) -> list[float]:
    """Ekranda gorunen anlamli sayilar: cap + data'daki metinler + sayac
    hedefi. 10 ve alti tam sayilar ve yillar sayilmiyor ('3 steps', '2026')."""
    texts: list[str] = []

    def walk(o, key=""):
        if isinstance(o, str):
            texts.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) \
                        and k in ("to", "v"):
                    texts.append(str(v))
                else:
                    walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)

    for b in spec.get("beats", []):
        texts.append(b.get("cap", ""))
        walk(b.get("data") or {})
    out = []
    for t in texts:
        for v in _nums(t):
            if (v == int(v) and v <= 10) or (1900 <= v <= 2100 and v == int(v)):
                continue
            out.append(v)
    return out


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def check_claims(spec: dict, claims: list, n_sources: int):
    """Editorun cikardigi sayi iddialarini dogrular.

    Donus: (sorunlar, aramayla dogrulanacak iddialar)

    Uc kontrol:
      1. Formul varsa kod HESAPLIYOR; Gemini'nin yazdigi sonuc tutmuyorsa red.
      2. Formul yoksa (bir fiyat sayfasindan okunan rakam) kaynak numarasi
         zorunlu ve arama dogrulamasina gidiyor.
      3. Ekranda gorunen her anlamli sayi bir iddiayla ortusmeli. Editor
         bir rakami "atlayarak" denetimi gecemesin.
    """
    p: list[str] = []
    lookups: list[dict] = []
    covered: list[float] = []

    for c in claims if isinstance(claims, list) else []:
        if not isinstance(c, dict):
            continue
        shown = str(c.get("shown", "")).strip()
        covered += _nums(shown)
        expr, val = c.get("expr"), c.get("value")
        if expr:
            try:
                got = safe_eval(str(expr))
            except (ValueError, SyntaxError, ZeroDivisionError,
                    OverflowError) as e:
                p.append(f"'{shown}': formul hesaplanamadi ({expr}): {e}")
                continue
            if not isinstance(val, (int, float)):
                p.append(f"'{shown}': formulun sonucu (value) yok")
            elif not math.isclose(got, float(val), rel_tol=0.015,
                                  abs_tol=0.006):
                p.append(f"'{shown}': {expr} = {got:g} ama senaryo {val:g} "
                         "diyor -- aritmetigi duzelt")
        else:
            src = c.get("source")
            if not isinstance(src, int) or not 0 <= src < n_sources:
                p.append(f"'{shown}': formul de kaynak numarasi da yok")
            else:
                lookups.append(c)

    for v in screen_numbers(spec):
        if not any(_same(v, c) for c in covered):
            p.append(f"ekranda {v:g} var ama editor bunun icin iddia "
                     "listelemedi")
            break                   # birini soylemek yeter; hepsi gurultu
    return p, lookups


def fact_lookups(spec: dict, facts, n_sources: int):
    """Editorun listeledigi OLAY iddialari (tarih, karar, kim ne yapti).

    Rakamlar check_claims'te formulle kanitlaniyor; hikaye ve gundem
    bicimlerinde videonun asil agirligi olaylar ve bunlar formullenemez. Bu
    iddialar arama destekli dogrulayiciya gider. Hikaye/gundem icin editor en
    az iki tane listelemek zorunda: bos liste "denetlenecek bir sey yok"
    anlamina gelmesin.

    Donus: (sorunlar, aramayla dogrulanacak iddialar) -- check_claims ile ayni
    sekil, boylece ikisi birlestirilip tek dogrulama cagrisina gidiyor.
    """
    p: list[str] = []
    out: list[dict] = []
    for f in facts if isinstance(facts, list) else []:
        if not isinstance(f, dict):
            continue
        claim = str(f.get("claim", "")).strip()
        src = f.get("source")
        if not claim:
            continue
        if not isinstance(src, int) or isinstance(src, bool) \
                or not 0 <= src < n_sources:
            p.append(f"statement '{claim[:70]}' has no valid source index; "
                     "put it on a listed source or remove it")
            continue
        out.append({"shown": claim, "expr": None, "value": None,
                    "source": src, "kind": "fact"})
    fmt = spec.get("format")
    need = NEEDS_FACTS.get(fmt, 0)
    if len(out) < need:
        p.append(f"a {fmt} script must list at least {need} checkable "
                 f"statements (found {len(out)}): state which event or page "
                 "each beat rests on, and add the missing sources")
    return p, out[:MAX_FACTS]


# ── karar ────────────────────────────────────────────────────────────────
@dataclass
class Decision:
    verdict: str                              # publish | revise | reject
    fixes: list = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    risk: str = "low"

    @property
    def mean(self) -> float:
        return sum(self.scores.values()) / len(self.scores) if self.scores else 0


def normalize_review(raw) -> dict:
    """Editorun ham ciktisini guvenli bicime sokar. Eksik/bozuk alan = en
    kotu varsayim: skor 0, risk medium."""
    raw = raw if isinstance(raw, dict) else {}
    sc = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    scores = {}
    for k in SCORE_KEYS:
        v = sc.get(k)
        scores[k] = int(v) if isinstance(v, (int, float)) and 0 <= v <= 10 else 0
    risk = raw.get("risk") if isinstance(raw.get("risk"), dict) else {}
    level = risk.get("level") if risk.get("level") in ("low", "medium", "high") \
        else "medium"
    verdict = raw.get("verdict") if raw.get("verdict") in (
        "publish", "revise", "reject") else "revise"
    fixes = [str(x) for x in raw.get("fixes", []) if x] \
        if isinstance(raw.get("fixes"), list) else []
    notes = raw.get("notes") if isinstance(raw.get("notes"), dict) else {}
    return {"scores": scores, "risk": {"level": level,
                                       "flags": [str(x) for x in
                                                 risk.get("flags", [])][:6]},
            "verdict": verdict, "fixes": fixes, "notes": notes,
            "claims": raw.get("claims") if isinstance(raw.get("claims"), list)
            else [],
            "facts": raw.get("facts") if isinstance(raw.get("facts"), list)
            else []}


def decide(review: dict, problems: list[str], min_score: int = 7) -> Decision:
    """Editorun yargisi + kodun buldugu sorunlar -> nihai karar.

    Gemini 'publish' dese bile kod bir aritmetik hatasi bulduysa yayinlanmaz;
    Gemini 'revise' dediyse kod temiz bulsa da yayinlanmaz. Ikisinin de onayi
    gerekiyor.
    """
    fixes = list(review["fixes"]) + list(problems)
    for k, v in review["scores"].items():
        if v < min_score:
            note = review["notes"].get(k, "")
            fixes.append(f"'{k}' puani {v}, en az {min_score} olmali. {note}"
                         .strip())
    d = Decision("publish", fixes, review["scores"], review["risk"]["level"])
    if review["risk"]["level"] == "high" or review["verdict"] == "reject":
        d.verdict = "reject"
    elif (fixes or review["verdict"] == "revise"
          or review["risk"]["level"] == "medium"):
        d.verdict = "revise"
        if not d.fixes:
            d.fixes = ["editor degisiklik istedi; risk bayraklarini gider: "
                       + ", ".join(review["risk"]["flags"])]
    return d
