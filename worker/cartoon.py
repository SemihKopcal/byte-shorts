"""
Karton / cizgi film stili -- dikey Short icin.

NEDEN: koyu ve yazi agirlikli tek bir gorunum, 30 video sonra "hep ayni sablon" hissi veriyor ve
YouTube'un temmuz 2026 politikasi tam da kalip uretilmis icerigi hedefliyor. Aciklayici cizgi film
kanallarinin (kagit zemin, kalin cizgili sprite'lar, fosforlu anahtar kelime, elle cizilmis isaretler,
iris gecisi) teknigi ayni, sadece bizim BYTE'imizle: kod cizer, hicbir stok gorsel ve hicbir baska
kanalin karakteri yok.

NE DEGISIYOR (sahne kodu degismiyor -- 26 sahne turu temanin renklerini zaten okuyor):
  * iki yuz: acik KAGIT ve koyu LACIVERT (themes.TOON_THEMES); sahneler arasinda sirayla
  * BYTE sunucu: sol ustte kalin dis cizgili, sesin siddetiyle oynayan imlecli; fosforlu kelimeyi gosterir
  * fosforlu anahtar kelime: sahnenin verisinden (ya da beat'teki "kw" alanindan) cikar, soldan saga boyanir
  * isaretler: beat'te "mark": "check" | "x" ise elle cizilir; her anahtar kelimede kucuk "vurgu" cizgileri
  * gecis: sahne degisimlerinde iris (daire acilir, kalin cizgili halka); eski FX gecisleri yerine
  * altyazi: krem hap + kalin cizgi + sert golge, aktif kelime fosforlu

HEPSI SENARYO KIMLIGINDEN (sha256) turetilir, rastgele DEGIL: publish.yml videoyu yeniden uretebiliyor,
iki render birebir ayni cikmali.

Acma/kapama: brand.json "cartoon": {"enabled": true, "alternate": true, "share": 1.0}.
  enabled=false -> hic dokunmaz (eski koyu gorunum); share<1 -> videolarin bir kismi (kimlikten, rastgele
  degil) eski gorunumde kalir; alternate=false -> hep kagit.
"""
from __future__ import annotations

import hashlib
import math
import re
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import byte as B
from . import draw as D
from . import fx as FX
from . import style as STYLE

VERSION = 1
K = 2                          # sprite/maske asiri ornekleme (kenar yumusatma)
IRIS_LEAD = 0.12               # iris, sahnenin ilk beat'inden bu kadar ONCE acilmaya baslar
IRIS_SECONDS = 0.55
KW_DELAY = 0.30                # sahne basladiktan sonra fosforlu kelime
KW_WIPE = 0.38
POINT_SECONDS = 1.15           # kelime belirirken BYTE bu sure kolunu uzatir
KW_MAX_CHARS = 18
INTRO_LEAD = 0.55              # ilk karede sahne bu kadar "ilerlemis" gelir: kapak karesi/ilk saniye bos olmasin
INTRO_END = 0.90               # ... ve bu ana kadar gercek zamana yetisir (turev > 0: geri/ziplama yok)
FONT_FILE = Path(__file__).parent / "assets" / "FredokaOne-Regular.ttf"   # SIL OFL (assets/OFL-*.txt)

PAPER, INK = "paper", "ink"
YELLOW = (255, 211, 25)
CREAM = (252, 250, 242)
PEN = (28, 26, 34)
GREEN, RED = (46, 184, 104), (214, 48, 48)

HOST_X, HOST_Y, HOST_SCALE = 124, 244, 0.50      # BYTE'in govde merkezi (cy) ve olcegi; ust bant (sahneler 330'dan basliyor)
STRIP_X0, STRIP_X1, STRIP_CY = 256, 1030, 250

DEFAULTS = {"enabled": False, "alternate": True, "share": 1.0}
_SAFE = re.compile(r"^[A-Za-z0-9 .,%$€£#&@+=<>/\\:;?!()\[\]{}~^*_|'\"\-–—·×÷…°]+$")


# ── ayar + kimlik ──────────────────────────────────────────────────────────────────────
def _u(sid: str, key: str) -> float:
    h = hashlib.sha256(f"{sid}|{key}|cartoon{VERSION}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def settings(brand: dict) -> dict:
    raw = brand.get("cartoon") if isinstance(brand.get("cartoon"), dict) else {}
    try:
        share = min(1.0, max(0.0, float(raw.get("share", 1.0))))
    except (TypeError, ValueError):
        share = 1.0
    return {"enabled": raw.get("enabled", False) is True,
            "alternate": raw.get("alternate", True) is not False,
            "share": share}


def apply(spec: dict, brand: dict) -> bool:
    """Profili senaryoya (bellekte) koyar. Kapaliysa / pay disindaysa / elle yazilmis seriyse False."""
    st = settings(brand)
    if not st["enabled"] or spec.get("_cartoon"):
        return False
    if str(spec.get("series", "")).upper() != "G":        # A/B serileri elle cizili: eski gorunum
        return False
    sid = STYLE.sid_of(spec)
    if _u(sid, "share") >= st["share"]:
        return False
    spec["_cartoon"] = {"v": VERSION, "alternate": st["alternate"], "start": int(_u(sid, "start") * 2)}
    return True


def active(spec: dict) -> bool:
    return bool(spec.get("_cartoon"))


def stage_themes(prof: dict, n: int) -> list[str]:
    """Sahne basina tema: kagit / lacivert sirayla (ya da hep kagit)."""
    if not prof.get("alternate", True):
        return [PAPER] * n
    s = int(prof.get("start", 0))
    return [PAPER if (i + s) % 2 == 0 else INK for i in range(n)]


# ── sahne verisinden fosforlu kelime / ton ─────────────────────────────────────────────
def _s(x):
    return x.strip() if isinstance(x, str) and x.strip() else None


def _ok(text, limit=KW_MAX_CHARS):
    text = _s(text)
    if not text:
        return None
    text = text.replace("≈", "~").replace("→", "->")
    return text if len(text) <= limit and _SAFE.match(text) else None


# Sahne -> kelimesini KUCUK gosteren alan. Yalniz bunlarda otomatik serit cikar: dots/counter/equation/contrast
# gibi sahneler ayni metni dev puntoyla yaziyor, ustte tekrar etmek yineleme olur (orada serit yalniz beat'te
# acik "kw" varsa).
AUTO_KW_FIELD = {"title": "kicker", "bits": "label", "terminal": "label"}


def auto_kw(name: str, data) -> str | None:
    """Sahnenin verisinden TEK kisa anahtar kelime -- yalniz sahne onu kucuk gosteriyorsa (AUTO_KW_FIELD)."""
    d = data if isinstance(data, dict) else {}
    field = AUTO_KW_FIELD.get(name)
    if not field:
        return None
    r = _ok(d.get(field))
    if r is None and name == "title":
        lines = d.get("lines")
        r = _ok(lines[0] if isinstance(lines, list) and lines else None)
    return r


def tone_of(data) -> str:
    """Sahnenin baskin tonu (good/mid/bad/base). BYTE'in imlec rengi buradan: 'bad' -> kehribar."""
    if isinstance(data, dict):
        for key in ("tone", "accent"):
            if data.get(key) in ("good", "mid", "bad"):
                return data[key]
        for v in data.values():
            if isinstance(v, dict) and v.get("tone") in ("good", "mid", "bad"):
                return v["tone"]
    return "base"


def plan(spec: dict, groups) -> list[dict]:
    """Sahne (grup) basina {name, tone, items:[{id, kw, mark}], kw, mark}.

    items: fosforlu kelimeler, BEAT'e bagli (beat'in kendi "kw"/"mark" alani; kw yalniz cumle okunurken gorunur).
    Grubun ilk beat'inde elle kw yoksa ve sahne kucuk etiket gosteriyorsa (AUTO_KW_FIELD) otomatik kelime
    en basa eklenir; ilk beat'te "kw": "" yazmak onu kapatir. kw/mark: ilk ogenin kisayolu (geriye uyum)."""
    beats = {b["id"]: b for b in spec.get("beats", [])}
    out = []
    for name, data, ids in groups:
        items = []
        for bid in ids:
            b = beats.get(bid, {})
            kw = _ok(b.get("kw"))
            if kw:
                mk = b.get("mark") if b.get("mark") in ("check", "x") else None
                items.append({"id": bid, "kw": kw, "mark": mk})
        first = ids[0]
        if not (items and items[0]["id"] == first) and beats.get(first, {}).get("kw") != "":
            auto = auto_kw(name, data)
            if auto:
                items.insert(0, {"id": first, "kw": auto, "mark": None})
        out.append({"name": name, "tone": tone_of(data), "items": items,
                    "kw": items[0]["kw"] if items else None, "mark": items[0]["mark"] if items else None})
    return out


# ── ses zarfi: BYTE'in imleci sesle oynar (dudak senkronunun karsiligi) ─────────────────
def voice_env(path, nframes: int, fps: int, beats) -> np.ndarray:
    """Kare basina 0..1 ses siddeti. Ses dosyasi okunamazsa kelime zamanlarindan uydurulur."""
    try:
        with wave.open(str(path)) as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw != 2:
            raise ValueError("16 bit degil")
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
        win = max(2, int(sr / fps))
        cs = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
        idx = (np.arange(nframes) / fps * sr).astype(np.int64)
        a = np.clip(idx - win // 2, 0, len(x))
        b = np.clip(idx + win // 2, 0, len(x))
        rms = np.sqrt((cs[b] - cs[a]) / np.maximum(b - a, 1) + 1e-12)
        loud = rms[rms > 0.02 * max(rms.max(), 1e-9)]
        ref = np.percentile(loud, 90) if len(loud) else 1.0
        env = np.clip(rms / max(ref, 1e-6), 0, 1) ** 0.8
        return np.convolve(env, [0.25, 0.5, 0.25], mode="same")
    except Exception:                                           # noqa: BLE001
        env = np.zeros(nframes, np.float32)
        for b in beats or []:
            for w in b.get("words", []):
                i0, i1 = max(0, int(w["s"] * fps)), min(nframes, int(w["e"] * fps) + 1)
                if i1 > i0:
                    env[i0:i1] = 0.45 + 0.4 * np.abs(np.sin(np.linspace(0, math.pi, i1 - i0)))
        return env


# ── cizim yardimcilari ─────────────────────────────────────────────────────────────────
def intro_time(t: float) -> float:
    """Sahne animasyonlarinin gordugu zaman. t=0'da INTRO_LEAD, INTRO_END'de t'ye esit; arada tek yonlu
    ve surekli. Sebep: Instagram/TikTok kapagi ve kaydirma karari ilk kareye bagli; eskiden t=0 karesi
    neredeyse bostu (sayi ve BYTE 0,2-0,5 sn'de beliriyordu). Ses/altyazi/anahtar kelime gercek zamanda."""
    if t >= INTRO_END:
        return t
    return t + INTRO_LEAD * (1.0 - t / INTRO_END)


def _clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def _ease_out(x):
    return 1 - (1 - _clamp(x)) ** 3


def _ease_back(x):
    x = _clamp(x)
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _smooth(x):
    x = _clamp(x)
    return x * x * (3 - 2 * x)


def _grow(mask: Image.Image, px: float) -> Image.Image:
    """Maskeyi px kadar yuvarlak sisirir (gauss+esik: MaxFilter'dan cok hizli)."""
    return mask.filter(ImageFilter.GaussianBlur(px / 1.64)).point(lambda v: 255 if v > 12 else 0)


def _outlined(rgba: Image.Image, px: int, pen, shadow_col=None, shadow_off: int = 0):
    """RGBA sprite -> kalin dis cizgili sprite (+ sert ofset golge). (sprite, marj) doner."""
    m = int(px + 8 + shadow_off)
    base = Image.new("RGBA", (rgba.width + 2 * m, rgba.height + 2 * m), (0, 0, 0, 0))
    base.paste(rgba, (m, m))
    g = _grow(base.split()[3], px)
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    if shadow_off and shadow_col:
        out.paste(Image.new("RGBA", base.size, tuple(shadow_col) + (255,)), (shadow_off, shadow_off), g)
    out.paste(Image.new("RGBA", base.size, tuple(pen) + (255,)), (0, 0), g)
    out.alpha_composite(base)
    return out, m


def _down(img: Image.Image) -> Image.Image:
    return img.resize((max(1, img.width // K), max(1, img.height // K)), Image.LANCZOS)


def _put(canvas: Image.Image, sprite: Image.Image, x: float, y: float) -> None:
    canvas.paste(sprite.convert("RGB"), (int(round(x)), int(round(y))), sprite.split()[3])


def _stamp(canvas: Image.Image, mask: Image.Image, color, x: float, y: float) -> None:
    canvas.paste(tuple(color), (int(round(x)), int(round(y)), int(round(x)) + mask.width, int(round(y)) + mask.height), mask)


@lru_cache(maxsize=None)
def _fredoka(px: int):
    try:
        return ImageFont.truetype(str(FONT_FILE), px)
    except OSError:                                             # varlik dosyasi yoksa Inter'e dus
        return D.F_HUGE(px)


def caption_font(word: str):
    """Altyazi kelimesi icin font: Fredoka'nin kapsadigi karakterler (ASCII + yaygin noktalama) ise Fredoka,
    degilse (≈, →, aksanli harf...) Inter. Yoksa eksik glif bos kutu / bos fosforlu hap olarak cikiyor."""
    # yalniz sembolden olusan kelimeler (=, ·, +, ×) Fredoka'da yukari kayik ve minik cikiyor: Inter daha dengeli
    if not any(c.isalnum() for c in word):
        return D.F_DISP(56)
    return _fredoka(60) if _SAFE.match(word) else D.F_DISP(56)


def _densify(pts, step=3.0):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(1, n + 1)]
    return out


def _stroke_mask(strokes, frac, width, size, seed=1.0, wob=1.6) -> Image.Image:
    """Elle cizilmis cizgi: strokes (1x koordinat), frac 0..1 = kalemin ilerlemesi. K kat cozunurlukte
    cizilir, 1x'e indirilir (yumusak kenar). Doner: size boyutunda 'L' maske."""
    big = Image.new("L", (size[0] * K, size[1] * K), 0)
    d = ImageDraw.Draw(big)
    dense = [_densify([(x * K, y * K) for x, y in s], 3.0) for s in strokes]
    lim = frac * sum(len(s) for s in dense)
    n = 0
    r = width * K / 2
    for s in dense:
        for x, y in s:
            if n >= lim:
                return _down(big)
            n += 1
            ox = wob * K * math.sin(0.09 * n + seed) + 0.6 * wob * K * math.sin(0.23 * n + 2 * seed)
            oy = wob * K * math.cos(0.08 * n + seed * 1.3)
            d.ellipse((x + ox - r, y + oy - r, x + ox + r, y + oy + r), fill=255)
    return _down(big)


def _colored(mask: Image.Image, col):
    return Image.merge("RGBA", (*[Image.new("L", mask.size, c) for c in col], mask))


# ── fosforlu anahtar kelime ────────────────────────────────────────────────────────────
@lru_cache(maxsize=128)
def keyword_masks(text: str, seed: float):
    """(serit_maske, yazi_maske, w, h) 1x, hafif egik. Metne gore yazi boyutu 76..44 arasinda secilir."""
    size = 76
    while size > 28:
        bb = _fredoka(size * K).getbbox(text)
        if (bb[2] - bb[0]) / K + 56 <= STRIP_X1 - STRIP_X0 - 24:
            break
        size -= 4
    f = _fredoka(size * K)
    bb = f.getbbox(text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    px, py = 28 * K, 15 * K
    w, h = tw + 2 * px, th + 2 * py
    strip = Image.new("L", (w, h), 0)
    ds = ImageDraw.Draw(strip)

    def j(i):
        return 4 * K * math.sin(seed * 3.1 + i * 1.7)

    top = [(w * i / 6, j(i)) for i in range(7)]
    rgt = [(w + j(9), h * i / 3) for i in range(1, 3)]
    bot = [(w * (6 - i) / 6, h + j(i + 20)) for i in range(7)]
    lft = [(j(31), h * (3 - i) / 3) for i in range(1, 3)]
    ds.polygon(top + rgt + bot + lft, fill=255)
    txt = Image.new("L", (w, h), 0)
    ImageDraw.Draw(txt).text((px - bb[0], py - bb[1]), text, font=f, fill=255)
    ang = -2.0 + 4.0 * ((seed * 7.13) % 1.0)
    strip = strip.rotate(ang, resample=Image.BICUBIC, expand=True)
    txt = txt.rotate(ang, resample=Image.BICUBIC, expand=True)
    return _down(strip), _down(txt), strip.width // K, strip.height // K


def _wipe(mask: Image.Image, p: float) -> Image.Image:
    m = Image.new("L", mask.size, 0)
    ImageDraw.Draw(m).rectangle((0, 0, int(mask.width * _clamp(p)), mask.height), fill=255)
    return ImageChops.multiply(mask, m)


@lru_cache(maxsize=4)
def _bg(name: str) -> Image.Image:
    """Tema kagidi/zemini (sabit tohumlu, deterministik) -- ayni surecte bir kez uretilir. Kopyasini al."""
    D.use_theme(name)
    return D.build_bg()


# ── ana sinif: kare kare kompozisyon ───────────────────────────────────────────────────
class Toon:
    """build.render'in karton modu. frame(i) -> altyazi + chrome DAHIL RGB kare (greyn build'de eklenir).

    Sahne katmani: stages[k] fonksiyonu kendi temasinda kendi kagidina cizilir; sahne degisiminde eski
    sahne son halinde dondurulur ve iris ile yenisine acilir (eski FX gecisleri kullanilmaz).
    Ust bant (y<330) sahnelere kapali: BYTE sunucu ve fosforlu kelime orada."""

    def __init__(self, spec, stages, S, duration, tl, chunks, plan_, corner=None, corner_text="",
                 voice_path=None, close_t0=None):
        self.spec, self.stages, self.S, self.duration = spec, stages, S, duration
        self.chunks, self.plan = chunks, plan_
        self.corner, self.corner_text = corner, corner_text
        self.close_t0 = duration if close_t0 is None else close_t0
        prof = spec["_cartoon"]
        n = len(stages)
        self.themes = stage_themes(prof, n)
        self.bgs = {name: _bg(name) for name in dict.fromkeys(self.themes)}
        self.sid = STYLE.sid_of(spec)
        self.cams = STYLE.cameras(self.sid, n)
        self.nframes = int(duration * D.FPS)
        self.env = voice_env(voice_path, self.nframes + 2, D.FPS, tl.get("beats") if tl else None) \
            if voice_path else np.zeros(self.nframes + 2)
        yy, xx = np.mgrid[0:D.H, 0:D.W].astype(np.float32)
        self._xx, self._yy = xx, yy
        self.badge_font = D.F_SEMI(26)

    # ── sahne katmani ─────────────────────────────────────────────────────────────
    def stage_at(self, t: float) -> int:
        si = 0
        for k, (t0, _t1, _f) in enumerate(self.stages):
            if t0 - IRIS_LEAD <= t:
                si = k
        return si

    def _scene(self, k: int, t: float) -> Image.Image:
        name = self.themes[k]
        D.use_theme(name)
        img = self.bgs[name].copy()
        t0, _t1, fn = self.stages[k]
        if t >= t0 - 0.25:
            fn(ImageDraw.Draw(img), t, self.S, self.spec)
        return img

    def _iris_center(self, k: int):
        return (D.W * (0.5 + 0.30 * (_u(self.sid, f"ix{k}") - 0.5)), 700 + 360 * (_u(self.sid, f"iy{k}") - 0.5))

    def _iris(self, old, new, u, k):
        cx, cy = self._iris_center(k)
        far = max(math.hypot(cx, cy), math.hypot(D.W - cx, cy), math.hypot(cx, D.H - cy),
                  math.hypot(D.W - cx, D.H - cy)) + 40
        r = _smooth(u) * far
        if r < 3:
            return old
        dist = np.hypot(self._xx - cx, self._yy - cy)
        a = np.clip(r - dist + 0.5, 0, 1)[..., None]
        out = np.asarray(new, np.float32) * a + np.asarray(old, np.float32) * (1 - a)
        both_paper = self.themes[k - 1] == PAPER and self.themes[k] == PAPER
        ring_col = np.array(PEN if both_paper else CREAM, np.float32)
        w = 9.0 * (1 - 0.5 * u)
        ring = np.clip(w - np.abs(dist - r) + 0.5, 0, 1)[..., None] * (1 - _smooth((u - 0.8) / 0.2))
        out = out * (1 - ring) + ring_col * ring
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))

    def scene_layer(self, t: float):
        """(RGB sahne katmani, aktif sahne indeksi, iris ilerlemesi 0..1 ya da None)."""
        si = self.stage_at(t)
        t0 = self.stages[si][0]
        u = (t - (t0 - IRIS_LEAD)) / IRIS_SECONDS
        if si >= 1 and 0 <= u < 1:
            old = self._scene(si - 1, min(t, self.stages[si - 1][1]))
            new = self._scene(si, t)
            return self._iris(old, new, u, si), si, u
        return self._scene(si, t), si, None

    def _camera(self, img, t, si):
        t0, t1, _f = self.stages[si]
        p = _clamp((t - t0) / max(0.1, t1 - t0))
        s, dx, dy = FX.camera_state(self.cams[si]["mode"], p, self.cams[si]["amp"], img.width, img.height)
        return FX.apply_camera(img, s, dx, dy)

    # ── ust katman: BYTE, kelime, altyazi, chrome ─────────────────────────────────
    def _host(self, img, t, i, si, kw_start, t_anim=None):
        D.use_theme(self.themes[si])
        pen, shadow = D.OUTLINE, D.SHADOW
        env = float(self.env[min(i, len(self.env) - 1)])
        speaking = env > 0.08
        tone = self.plan[si]["tone"]
        cursor = B.AMBER if tone == "bad" else B.MINT
        pointing = kw_start is not None and 0 <= t - kw_start < POINT_SECONDS
        pose = "point_r" if pointing else "idle"
        blink = True if (speaking or t > self.duration - 1.2) else D.blink_on(t, 1.4, 0.22)
        cw = 0.85 + 1.35 * env
        ta = t if t_anim is None else t_anim
        pop = max(0.05, _ease_back((ta - 0.15) / 0.45)) if ta < 0.7 else 1.0
        bob = 3.0 * math.sin(2 * math.pi * t / 1.7) if t > 0.8 else 0.0
        B.draw_byte_sticker(ImageDraw.Draw(img), HOST_X, HOST_Y + bob, HOST_SCALE * pop, pose, cursor, blink,
                            cw, pen=pen, shadow=shadow)

    def _item_at(self, si, t):
        """(j, ogе, ts, te): t'de en son baslamis fosforlu kelime. ts = beat basi + KW_DELAY; te = cumle bitisi + 0.25
        (sonraki kelime baslarsa o ana kadar, sahne bitisinden 0.12 once en gec)."""
        items = self.plan[si]["items"]
        t1 = self.stages[si][1]
        found = None
        for j, it in enumerate(items):
            s0, s1 = self.S.get(it["id"], (self.stages[si][0], t1))
            ts, te = s0 + KW_DELAY, min(s1 + 0.25, t1 - 0.12)
            if j + 1 < len(items):
                n0 = self.S.get(items[j + 1]["id"], (t1, t1))[0] + KW_DELAY
                te = min(te, n0)
            if ts <= t:
                found = (j, it, ts, te)
        return found

    def _keyword(self, img, t, si, a_corner):
        """Fosforlu kelimeyi cizer. Doner: kelimenin baslangic zamani (BYTE'in kol uzatmasi icin) ya da None."""
        if a_corner > 0.05:
            return None
        hit = self._item_at(si, t)
        if not hit:
            return None
        j, item, ts, t_end = hit
        if t > t_end:
            return ts
        kw = item["kw"]
        seed = 1.0 + _u(self.sid, f"kw{si}_{j}") * 5
        strip, txt, w, h = keyword_masks(kw, round(seed, 3))
        p = _ease_out((t - ts) / KW_WIPE)
        out = _clamp((t_end - t) / 0.15)                        # kapanirken hizlica sonuyor
        p *= out
        D.use_theme(self.themes[si])
        x = STRIP_X0 + 6
        y = STRIP_CY - h / 2
        s_ = _wipe(strip, p)
        _stamp(img, s_, D.SHADOW, x + 6, y + 6)
        _stamp(img, s_, YELLOW, x, y)
        _stamp(img, _wipe(txt, p), PEN, x, y)
        # vurgu cizgileri: sag ust kosede uc kalin cizgi, disa dogru acilir
        pb = _smooth(_clamp((t - (ts + KW_WIPE * 0.6)) / 0.30)) * out
        if pb > 0:
            d = ImageDraw.Draw(img)
            ox, oy = x + w - 2, y + 6
            for ang in (28, 62, 96):
                a_ = math.radians(ang)
                r0, r1 = 12 + 4 * pb, 12 + 4 * pb + 30 * pb
                p0 = (ox + r0 * math.cos(a_), oy - r0 * math.sin(a_))
                p1 = (ox + r1 * math.cos(a_), oy - r1 * math.sin(a_))
                d.line([p0, p1], fill=D.OUTLINE, width=7)
                for q in (p0, p1):
                    d.ellipse((q[0] - 3.5, q[1] - 3.5, q[0] + 3.5, q[1] + 3.5), fill=D.OUTLINE)
        # elle cizilen isaret (beat'te "mark")
        mk = item["mark"]
        if mk:
            pm = _clamp((t - (ts + KW_WIPE + 0.1)) / 0.32) * out
            if pm > 0:
                self._mark(img, mk, pm, x + w + 14, STRIP_CY - 46)
        return ts

    def _mark(self, img, kind, p, x, y):
        if kind == "check":
            m = _stroke_mask([[(4, 52), (34, 88), (98, 4)]], p, 15, (130, 100), seed=2)
            col = GREEN
        else:
            m = _stroke_mask([[(0, 0), (80, 80)], [(80, 0), (0, 80)]], p, 14, (96, 96), seed=3)
            col = RED
        sp, mg = _outlined(_colored(m.resize((m.width * K, m.height * K), Image.BICUBIC), col), 4 * K, D.OUTLINE)
        sp = _down(sp)
        if x + sp.width > D.W - 16:
            x = D.W - 16 - sp.width
        _put(img, sp, x - mg / K, y - mg / K)

    def _caption(self, img, t):
        cur = None
        for ch in self.chunks:
            if ch[0]["s"] - 0.05 <= t <= ch[-1]["e"] + 0.12:
                cur = ch
                break
        if not cur:
            return
        words = [w["w"].upper() for w in cur]
        fonts = [caption_font(w) for w in words]
        d = ImageDraw.Draw(img)
        gap = d.textlength(" ", font=fonts[0]) + 4
        widths = [d.textlength(w, font=f) for w, f in zip(words, fonts)]
        total = sum(widths) + gap * (len(words) - 1)
        x0, y = (D.W - total) / 2, 1560
        box = (x0 - 34, y - 14, x0 + total + 34, y + 92)
        d.rounded_rectangle((box[0] + 8, box[1] + 8, box[2] + 8, box[3] + 8), radius=30, fill=D.SHADOW)
        d.rounded_rectangle(box, radius=30, fill=CREAM, outline=PEN, width=5)
        x = x0
        for w, wd, f, meta in zip(words, widths, fonts, cur):
            if meta["s"] <= t <= meta["e"]:
                d.rounded_rectangle((x - 10, y + 12, x + wd + 10, y + 68), radius=15, fill=YELLOW)
            if any(c.isalnum() for c in w):
                d.text((x, y + 14 + (0 if _SAFE.match(w) else 4)), w, font=f, fill=PEN, anchor="lt")
            else:                                                # =, ·, ÷ ...: murekkep kutusu buyuk harflerin ortasina otursun
                bb = d.textbbox((0, 0), w, font=f, anchor="ls")
                d.text((x, y + 35 - (bb[1] + bb[3]) / 2), w, font=f, fill=PEN, anchor="ls")
            x += wd + gap

    def _chrome(self, img, t, si):
        D.use_theme(self.themes[si])
        d = ImageDraw.Draw(img)
        p = _clamp(t / self.duration)
        d.rectangle((0, 0, D.W, 8), fill=D.TRACK)
        d.rectangle((0, 0, D.W * p, 8), fill=D.VIOLET)
        d.line([(0, 8), (D.W, 8)], fill=D.OUTLINE, width=2)

    def _corner(self, img, t, si):
        """CTA kose etiketi (begen / takip): BYTE'in yaninda; o sirada fosforlu kelime susar."""
        if not self.corner or not self.corner_text:
            return 0.0
        t0, t1 = self.corner
        a = min(_clamp((t - t0) / 0.35), _clamp((t1 - t) / 0.35))
        if a > 0.01:
            D.use_theme(self.themes[si])
            D.draw_cta_corner(ImageDraw.Draw(img), t, self.corner, self.corner_text, origin=(STRIP_X0, 226))
        return a

    def frame(self, i: int) -> Image.Image:
        t = i / D.FPS
        te = intro_time(t)
        img, si, u = self.scene_layer(te)
        img = self._camera(img, t, si)
        a_corner = self._corner(img, t, si)
        kw_start = self._keyword(img, t, si, a_corner)
        self._host(img, t, i, si, kw_start, t_anim=te)
        if t < self.close_t0 - 0.1:
            self._caption(img, t)
        self._chrome(img, t, si)
        return img
