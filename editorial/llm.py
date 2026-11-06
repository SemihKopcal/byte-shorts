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
BACKOFF = (5, 15, 40)                 # saniye; uc tekrar, sonra siradaki model
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
        self.model = ""               # son basarili cagrinin modeli
        self.calls = 0
        self.failures = 0

    # ── model secimi ────────────────────────────────────────────────────
    def candidates(self) -> list[str]:
        if self._cands is None:
            forced = os.environ.get("GEMINI_MODEL", "").strip()
            names: list[str] = [forced] if forced else []
            st, out = self.transport("GET", f"{BASE}/models?pageSize=200",
                                     self.key)
            if st == 200:
                names += rank_models(out.get("models", []))
            else:
                self.log(f"  [gemini] model listesi alinamadi ({st}); "
                         "yedek adlar denenecek")
            names += list(LAST_RESORT)
            self._cands = list(dict.fromkeys(names))
        return [m for m in self._cands if m not in self._dead]

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
        for model in self.candidates():
            use_grounding = grounded
            for wait in (0,) + BACKOFF:
                if wait:
                    self.sleep(wait)
                self._pace()
                self.calls += 1
                st, out = self.transport(
                    "POST", f"{BASE}/models/{model}:generateContent", self.key,
                    self._body(prompt, system, temperature, max_tokens,
                               json_mode, use_grounding))
                if st == 200:
                    text = self._text(out)
                    if text is None:
                        self.failures += 1
                        self.log(f"  [gemini] {tag}bos yanit ({model}): "
                                 f"{json.dumps(out)[:200]}")
                        return None
                    self.model = model
                    self.last_grounded = use_grounding
                    return text
                msg = (out.get("error") or {}).get("message", "")[:200]
                if st == 400 and use_grounding:
                    # Bu model/hesap arama destegini vermiyor: aramasiz dene.
                    self.log(f"  [gemini] {tag}arama destegi yok, "
                             f"aramasiz deneniyor ({msg})")
                    use_grounding = False
                    continue
                if st in RETRY or st == 0:
                    self.log(f"  [gemini] {tag}{model} {st}: tekrar denenecek")
                    continue
                if st in (403, 404):
                    self.log(f"  [gemini] {tag}{model} kullanilamiyor "
                             f"({st}): {msg}")
                    self._dead.add(model)
                    break
                self.failures += 1
                self.log(f"  [gemini] {tag}{model} HTTP {st}: {msg}")
                return None
            else:
                # tekrarlar bitti (kota/yogunluk): baska modelin kotasi ayri
                self.log(f"  [gemini] {tag}{model} yanit vermedi, "
                         "siradaki model")
        self.failures += 1
        self.last_grounded = False
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
