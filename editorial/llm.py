"""
Gemini istemcisi. Hatta Gemini'ye giden TEK kapi burasi.

Neden ayri bir dosya: Gemini'nin dort ayri isi var (yapimci, yazar, editor,
metin yazari) ve hepsi ayni sorunlarla karsilasiyor: model adi degisir,
kota dolar, gecici 503 gelir, JSON'u ```json citlari icinde yollar. Bunu her
rolde ayri cozmek yerine bir kere burada cozuyoruz.

Tasarim kararlari
  * MODEL ADI SABIT DEGIL. Google modelleri sik emekliye ayiriyor; kodda
    "gemini-2.0-flash" yazarsa bir sabah 404 doner ve hat durur. Bunun yerine
    ListModels'e soruyoruz: bu anahtarla CAGIRILABILEN en yeni kararli flash
    hangisi. Calismayana (404/403/kota) siradakine geciliyor.
  * Anahtar URL'de degil `x-goog-api-key` basliginda: hata mesajlari ve
    Actions logu URL'yi yazdirabiliyor, anahtar logda kalmasin.
  * Hicbir cagri hata FIRLATMIYOR; None donuyor. Cagiran taraf yedege dusebilsin.
  * Bozuk model DINLENDIRILIYOR: tekrarlari biten (503/zaman asimi) model 5
    dakika boyunca denenmiyor. Yoksa sonraki her rol (yazar, editor, metin)
    ayni bozuk modele bastan vurup dakikalar harciyor; canli kosuda 27 dakika
    boyle gitti.
  * Sert tavan: GEMINI_DEADLINE (varsayilan 600 sn). Dolunca ask() hemen None
    doner, hat "bugun video yok" der; Actions saatlerce asili kalmaz. Saglikli
    bir kosu 2-4 dakika; tavan sadece patolojik durum icin.
  * Tek cagri zaman asimi GEMINI_TIMEOUT (varsayilan 60 sn). Bu kosuda HIC
    cevap vermemis bir modele ilk istek en fazla 45 sn bekler ve zaman asimina
    ugrarsa tekrar denenmez: bozuk modelin maliyeti en kotu 45 sn.
  * Ardisik cagrilar arasinda en az MIN_INTERVAL saniye: ucretsiz katman
    dakikada birkac istege izin veriyor, bir videonun 10+ cagrisi bunu asar.
  * `transport` disaridan verilebiliyor: testler ag olmadan calisiyor.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRY = {429, 500, 502, 503, 504}
BACKOFF = (5, 15)                     # saniye; iki tekrar, sonra siradaki model
COOLDOWN = 300                        # tekrarlari biten model bu kadar saniye dinlenir
FIRST_TIMEOUT = 45                    # hic cevap vermemis modele ilk istek
PING_TIMEOUT = 20                     # saglik yoklamasi (warm/probe) zaman asimi
MAX_HINT = 65                         # Google "55s sonra dene" derse en fazla bu kadar bekle
LAST_RESORT = ("gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash")

_FLASH = re.compile(
    r"^gemini-(\d+)(?:\.(\d+))?-flash(-lite)?(-preview[\w.-]*)?$")


def default_transport(method, url, key, body=None, timeout=120):
    """(status, json). Ag hatasi = (0, {...}); asla firlatmaz."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:                                   # noqa: BLE001
            return e.code, {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return 0, {"error": {"message": str(e)}}


def quota_hint(out: dict) -> tuple[str, float | None]:
    """429 govdesinden (tur, bekleme_saniyesi).

    tur: "zero"  bu modelde bu anahtar icin kota HIC yok (limit: 0)
         "daily" gunluk kota dolmus; saatlerce gecmez
         "rate"  dakikalik sinir; biraz beklenince gecer
         ""      govdeden anlasilamadi
    Beklemeye deger tek durum "rate". Digerlerinde ayni modele dakikalarca
    istek atmak boşuna: sonraki modele gecilir.
    """
    err = (out or {}).get("error") or {}
    msg = str(err.get("message", ""))
    kind, delay = "", None
    rank = {"": 0, "rate": 1, "daily": 2, "zero": 3}
    for d in err.get("details") or []:
        if not isinstance(d, dict):
            continue
        t = str(d.get("@type", ""))
        if t.endswith("QuotaFailure"):
            for v in d.get("violations") or []:
                if not isinstance(v, dict):
                    continue
                if str(v.get("quotaValue", "")) == "0":
                    k = "zero"
                elif "perday" in str(v.get("quotaId", "")).lower():
                    k = "daily"
                else:
                    k = "rate"
                if rank[k] > rank[kind]:
                    kind = k
        if t.endswith("RetryInfo"):
            m = re.match(r"^(\d+(?:\.\d+)?)s$", str(d.get("retryDelay", "")))
            if m:
                delay = float(m[1])
    if not kind:
        low = msg.lower()
        if re.search(r"limit:\s*0\b", low):
            kind = "zero"
        elif "perday" in low.replace(" ", "") or "per day" in low:
            kind = "daily"
    if delay is None:
        m = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", msg, re.I)
        if m:
            delay = float(m[1])
    return kind, delay


def gist(msg: str, n: int = 220) -> str:
    """Hata mesajinin LOGA yazilacak ozu. Gemini'nin 429 mesaji uzun bir
    giris cumlesiyle baslar; asil bilgi ("Quota exceeded for metric ... limit:
    0, model: ...") sonunda."""
    t = " ".join(str(msg).split())
    i = t.find("Quota exceeded")
    if i >= 0:
        t = t[i:]
    return t[:n]


def rank_models(models: list[dict]) -> list[str]:
    """ListModels cevabindan, denenecek siraya dizilmis model adlari.

    Sira: kararli > preview, lite olmayan > lite, sonra en yeni surum.
    Gorsel/ses/canli varyantlar (-image, -tts, -live...) regex'e uymadigi
    icin kendiliginden elenir.
    """
    scored = []
    for m in models:
        name = m.get("name", "").removeprefix("models/")
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        mt = _FLASH.match(name)
        if not mt:
            continue
        major, minor = int(mt[1]), int(mt[2] or 0)
        scored.append(((not mt[4], not mt[3], major, minor), name))
    scored.sort(reverse=True)
    return [n for _, n in scored]


def parse_json(text: str):
    """Modelin metninden JSON'u cikarir. Citlari ve onsoz/sonsozu tolere eder.
    Basarisizsa None."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


class Gemini:
    def __init__(self, key: str, *, transport=default_transport,
                 sleep=time.sleep, clock=time.monotonic, log=None,
                 min_interval: float | None = None):
        self.key = key
        self.transport = transport
        self.sleep = sleep
        self.clock = clock
        self.log = log or (lambda m: print(m, file=sys.stderr, flush=True))
        self.min_interval = (
            float(os.environ.get("GEMINI_MIN_INTERVAL", "4"))
            if min_interval is None else min_interval)
        self._cands: list[str] | None = None
        self._dead: set[str] = set()
        self._last = -1e9
        self.wait_budget = float(os.environ.get("GEMINI_WAIT_BUDGET") or 240)
        self.deadline = float(os.environ.get("GEMINI_DEADLINE") or 600)
        self.timeout = float(os.environ.get("GEMINI_TIMEOUT") or 60)
        self._proven: set[str] = set()      # bu kosuda en az bir kez cevap vermis
        self._t0 = clock()
        self._cool: dict[str, float] = {}   # model -> dinlenme bitis zamani
        self.waited = 0.0             # 429/5xx icin toplam beklenen saniye
        self.reasons: dict[str, str] = {}   # model -> son hata ozeti
        self.model = ""               # son basarili cagrinin modeli
        self.calls = 0
        self.failures = 0

    # ── model secimi ────────────────────────────────────────────────────
    def candidates(self) -> list[str]:
        if self._cands is None:
            forced = os.environ.get("GEMINI_MODEL", "").strip()
            names: list[str] = [forced] if forced else []
            st, out = self.transport("GET", f"{BASE}/models?pageSize=200",
                                     self.key, timeout=self.timeout)
            if st == 200:
                names += rank_models(out.get("models", []))
            else:
                self.log(f"  [gemini] model listesi alinamadi ({st}); "
                         "yedek adlar denenecek")
            names += list(LAST_RESORT)
            self._cands = list(dict.fromkeys(names))
        live = [m for m in self._cands if m not in self._dead]
        now = self.clock()
        rested = [m for m in live if self._cool.get(m, 0) <= now]
        # bu kosuda cevap vermis modeller one (sira kararli)
        return sorted(rested or live, key=lambda m: m not in self._proven)

    # ── saglik yoklamasi ───────────────────────────────────────────────
    def probe(self, model: str, *, grounded: bool = False,
              timeout: float = PING_TIMEOUT):
        """Tek kucuk istek: (durum, govde, saniye). Hic firlatmaz."""
        self._pace()
        self.calls += 1
        t = self.clock()
        st, out = self.transport(
            "POST", f"{BASE}/models/{model}:generateContent", self.key,
            self._body("Reply with the single word: ready", None, 0.0, 64,
                       False, grounded), timeout=timeout)
        return st, out, self.clock() - t

    def warm(self, limit: int = 10, budget: float = 120) -> str | None:
        """Ilk SAGLIKLI modeli bulur ve one alir; bulamazsa None.

        Yazar/editor gibi pahali cagrilari bozuk bir modele harcamak yerine,
        kosunun basinda her aday icin 20 sn'lik kucuk bir yoklama: en yeni
        kararli modelden baslar, ilk cevap vereni secer. Bozuklar dinlenir
        ya da (kotasi yok/404) kosu boyunca elenir."""
        start = self.clock()
        for model in self.candidates():
            if limit <= 0 or self.clock() - start > budget:
                break
            limit -= 1
            st, out, secs = self.probe(model)
            if st == 200:
                self.model = model
                self._proven.add(model)
                self.log(f"  [gemini] {model} hazir ({secs:.1f} sn)")
                return model
            msg = gist((out.get("error") or {}).get("message", ""))
            kind = quota_hint(out)[0] if st == 429 else ""
            self.reasons[model] = f"{st} {kind}".strip() + f": {msg}"
            if st in (403, 404) or kind in ("zero", "daily"):
                self._dead.add(model)
            else:
                self._rest(model)
            self.log(f"  [gemini] {model} yoklamaya cevap vermedi: "
                     f"{self.reasons[model][:160]}")
        return None

    def _rest(self, model: str):
        self._cool[model] = self.clock() + COOLDOWN

    def over_deadline(self) -> bool:
        return self.clock() - self._t0 > self.deadline

    # ── cagri ───────────────────────────────────────────────────────────
    def _body(self, prompt, system, temperature, max_tokens, json_mode,
              grounded):
        cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
        # Arama destegiyle JSON modu birlikte kullanilamiyor; o durumda
        # JSON'u metinden cikaracagiz (parse_json).
        if json_mode and not grounded:
            cfg["responseMimeType"] = "application/json"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": cfg}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if grounded:
            body["tools"] = [{"google_search": {}}]
        return body

    def _pace(self):
        wait = self.min_interval - (self.clock() - self._last)
        if wait > 0:
            self.sleep(wait)
        self._last = self.clock()

    def ask(self, prompt: str, *, system: str | None = None,
            temperature: float = 0.9, max_tokens: int = 8192,
            json_mode: bool = True, grounded: bool = False,
            role: str = "") -> str | None:
        """Metin dondurur; hicbir model cevap veremezse None."""
        tag = f"[{role}] " if role else ""
        self.reasons = {m: r for m, r in self.reasons.items()
                        if m in self._dead}
        for model in self.candidates():
            use_grounding = grounded
            hint: float | None = None
            net_fail = 0
            proven = model in self._proven
            for wait in (0,) + BACKOFF:
                if self.over_deadline():
                    self.failures += 1
                    self.last_grounded = False
                    self.log(f"  [gemini] {tag}zaman tavani doldu "
                             f"({self.deadline:.0f} sn), vazgeciliyor")
                    return None
                if wait:
                    w = min(max(wait, hint or 0), MAX_HINT)
                    if self.waited + w > self.wait_budget:
                        self.log(f"  [gemini] {tag}bekleme butcesi doldu "
                                 f"({self.wait_budget:.0f} sn), siradaki model")
                        self._rest(model)
                        break
                    self.waited += w
                    self.sleep(w)
                hint = None
                self._pace()
                self.calls += 1
                st, out = self.transport(
                    "POST", f"{BASE}/models/{model}:generateContent", self.key,
                    self._body(prompt, system, temperature, max_tokens,
                               json_mode, use_grounding),
                    timeout=(self.timeout if proven or wait
                             else min(self.timeout, FIRST_TIMEOUT)))
                if st == 200:
                    text = self._text(out)
                    if text is None:
                        self.failures += 1
                        self.log(f"  [gemini] {tag}bos yanit ({model}): "
                                 f"{json.dumps(out)[:200]}")
                        return None
                    self.model = model
                    self._proven.add(model)
                    self.last_grounded = use_grounding
                    return text
                msg = gist((out.get("error") or {}).get("message", ""))
                if st == 400 and use_grounding:
                    # Bu model/hesap arama destegini vermiyor: aramasiz dene.
                    self.log(f"  [gemini] {tag}arama destegi yok, "
                             f"aramasiz deneniyor ({msg})")
                    use_grounding = False
                    continue
                if st == 429:
                    kind, delay = quota_hint(out)
                    self.reasons[model] = f"429 {kind or '?'}: {msg}"
                    if (kind in ("zero", "daily") and use_grounding
                            and re.search(r"ground|search", msg, re.I)):
                        # Kota ARAMA icin bitmis, modelin kendisi icin degil.
                        self.log(f"  [gemini] {tag}{model} arama kotasi yok, "
                                 f"aramasiz deneniyor ({msg})")
                        use_grounding = False
                        continue
                    if kind in ("zero", "daily"):
                        what = ("bu anahtarda kotasi yok" if kind == "zero"
                                else "gunluk kotasi dolmus")
                        self.log(f"  [gemini] {tag}{model} {what}, siradaki "
                                 f"model ({msg})")
                        self._dead.add(model)
                        break
                    self.log(f"  [gemini] {tag}{model} 429 hiz siniri"
                             + (f", {delay:.0f} sn sonra" if delay else "")
                             + f" ({msg})")
                    hint = delay
                    continue
                if st in RETRY or st == 0:
                    self.reasons[model] = f"{st}: {msg}"
                    if st == 0:
                        # zaman asimi/ag hatasi: her biri dakikalar yiyor,
                        # bir kez daha denemek yeter
                        net_fail += 1
                        if net_fail >= (2 if proven else 1):
                            self.log(f"  [gemini] {tag}{model} ulasilamiyor "
                                     f"({msg}), dinlendiriliyor")
                            self._rest(model)
                            break
                    self.log(f"  [gemini] {tag}{model} {st}: tekrar "
                             f"denenecek ({msg})")
                    continue
                if st in (403, 404):
                    self.reasons[model] = f"{st}: {msg}"
                    self.log(f"  [gemini] {tag}{model} kullanilamiyor "
                             f"({st}): {msg}")
                    self._dead.add(model)
                    break
                self.failures += 1
                self.log(f"  [gemini] {tag}{model} HTTP {st}: {msg}")
                return None
            else:
                # tekrarlar bitti (kota/yogunluk): baska modelin kotasi ayri
                self._rest(model)
                self.log(f"  [gemini] {tag}{model} yanit vermedi, "
                         f"{COOLDOWN // 60} dk dinlendiriliyor, siradaki model")
        self.failures += 1
        self.last_grounded = False
        if self.reasons:
            self.log("  [gemini] hicbir model cevap vermedi: " + "; ".join(
                f"{m}: {r[:90]}" for m, r in list(self.reasons.items())[:6]))
        return None

    last_grounded = False

    @staticmethod
    def _text(out: dict) -> str | None:
        try:
            parts = out["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            return None
        # "thought" parcalari modelin ic dusuncesi; cevabin parcasi degil
        txt = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return txt or None

    def ask_json(self, prompt: str, **kw):
        """JSON nesnesi/listesi ya da None. Bozuk JSON'da bir kez, hatayi
        modele soyleyerek tekrar dener."""
        raw = self.ask(prompt, **kw)
        data = parse_json(raw)
        if data is None and raw:
            self.log("  [gemini] gecersiz JSON, bir kez daha isteniyor")
            raw = self.ask(
                prompt + "\n\nYour previous reply was not valid JSON. "
                "Reply with ONLY the JSON object, no commentary.", **kw)
            data = parse_json(raw)
        return data
