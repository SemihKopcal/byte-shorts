"""
Ortak cizim katmani -- her serinin paylastigi palet, tipografi, zamanlama
yardimcilari, arka plan, altyazi ve chrome.

Seriler (series_a, series_b ...) BUNU import eder, birbirini DEGIL. Yeni seri
eklemek bir dosya acmak demek; ortak kurallar tek yerden degisir.
"""
import math
import subprocess
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

from .byte import draw_byte_badge, MINT as B_MINT

W, H, FPS = 1080, 1920, 30
FONT_DIR = Path("/usr/share/fonts/opentype/inter")

# ── aktif tema ───────────────────────────────────────────────────────────────
# Bu degerler use_theme() ile DEGISIYOR. Sahneler ve seriler onlari cagri
# aninda okudugu icin (D.INK, D.TONE...) tema degisince hepsi birden
# degisiyor; her sahneye tema gecirmek gerekmiyor.
BG0, BG1 = (7, 7, 12), (15, 15, 26)
GLOW = (139, 139, 255)
INK = (244, 244, 248)
MUTE = (124, 124, 148)
MINT = (74, 222, 128)          # "good"
AMBER = (255, 176, 32)         # "bad"
VIOLET = (139, 139, 255)       # "mid" + ilerleme cubugu
LINE = (34, 34, 52)
TONE = {"base": INK, "good": MINT, "mid": VIOLET, "bad": AMBER}
TEXTURE = "none"
THEME = "midnight"


def use_theme(name: str) -> str:
    """Paleti degistirir. build.render en basta bir kez cagiriyor."""
    from .themes import THEMES
    global BG0, BG1, GLOW, INK, MUTE, MINT, AMBER, VIOLET, LINE, TONE
    global TEXTURE, THEME
    t = THEMES.get(name) or THEMES["midnight"]
    THEME = name if name in THEMES else "midnight"
    BG0, BG1, GLOW = t["bg0"], t["bg1"], t["glow"]
    INK, MUTE, LINE = t["ink"], t["mute"], t["line"]
    MINT, VIOLET, AMBER = t["good"], t["mid"], t["bad"]
    TONE = {"base": INK, "good": MINT, "mid": VIOLET, "bad": AMBER}
    TEXTURE = t["tex"]
    return THEME

# Shorts guvenli alanlari: alt ~290px arayuz (baslik, aksiyon sutunu) ile
# ortulu. Altyazi 1555'te bitiyor, BYTE 1420'nin ustunde kaliyor.
CAPTION_Y = 1555
PUSH = 0.035          # sahne boyunca kamera yakinlasmasi


# ── font cozumleme ───────────────────────────────────────────────────────────
# Yollar SABIT KODLANMIYOR: bu konteynerde Inter /usr/share/fonts/opentype/
# inter altinda .otf olarak duruyor, Ubuntu runner'inda apt paketi .ttf olarak
# baska bir dizine koyuyor, macOS'ta ucuncu bir yer. Once bilinen yollara, sonra
# fontconfig'e soruyoruz. Bulunamazsa SESSIZCE baska fonta dusmek yerine
# patliyoruz -- sessiz font fallback'i videoyu bozar ve fark edilmez.
@lru_cache(maxsize=None)
def _font_file(family: str, style: str, *names: str) -> str:
    for d in (str(Path.home() / ".local/share/fonts/inter"),   # tools/setup_runner.sh
              "/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/inter",
              "/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/noto"):
        for n in names:
            p = Path(d) / n
            if p.exists():
                return str(p)
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", f"{family}:style={style}"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        out = ""
    if not out or family.split()[0].lower() not in out.lower():
        raise RuntimeError(
            f"Font bulunamadi: {family} {style}. Kurulum: apt-get install fonts-inter "
            f"fonts-noto-cjk (fc-match '{family}:style={style}' ile dogrula)")
    return out


@lru_cache(maxsize=None)
def _ttf(key: tuple, size: int) -> ImageFont.FreeTypeFont:
    family, style, names = key
    return ImageFont.truetype(_font_file(family, style, *names), size)


F_HUGE = lambda s: _ttf(("Inter Display", "Black",
                         ("InterDisplay-Black.otf", "InterDisplay-Black.ttf")), s)
F_DISP = lambda s: _ttf(("Inter Display", "Bold",
                         ("InterDisplay-Bold.otf", "InterDisplay-Bold.ttf")), s)
F_SEMI = lambda s: _ttf(("Inter", "SemiBold",
                         ("Inter-SemiBold.otf", "Inter-SemiBold.ttf")), s)
F_MED = lambda s: _ttf(("Inter", "Medium",
                        ("Inter-Medium.otf", "Inter-Medium.ttf")), s)
F_REG = lambda s: _ttf(("Inter", "Regular",
                        ("Inter-Regular.otf", "Inter-Regular.ttf")), s)


def cjk_font(size: int) -> ImageFont.FreeTypeFont:
    """Japonca glif icin. Seri B'nin ders sahnesi bunu kullaniyor."""
    for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
              "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size, index=0) if p.endswith(".ttc") \
                else ImageFont.truetype(p, size)
    raise RuntimeError("CJK fontu yok: apt-get install fonts-noto-cjk")


# ───────────────────────── yardimcilar ─────────────────────────
def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out(x):
    return 1 - (1 - x) ** 3


def appear(t, t0, dur=0.42):
    return ease_out(clamp01((t - t0) / dur))


def punch(t, t0, dur=0.18, amt=0.06):
    """Vurgu: kisa bir buyu-kucul. Beat basina senkron."""
    x = (t - t0) / dur
    if x < 0 or x > 1:
        return 1.0
    return 1.0 + amt * math.sin(x * math.pi)


def countup(t, t0, dur, a, b):
    return a + (b - a) * ease_out(clamp01((t - t0) / dur))


def mix(c1, c2, a):
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * a)) for i in range(3))


def fade(c, a):
    return mix(BG0, c, clamp01(a))


def tracked(d, xy, text, fnt, fill, track=0.0, anchor="lt"):
    if track == 0:
        d.text(xy, text, font=fnt, fill=fill, anchor=anchor)
        return
    widths = [d.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + track * (len(text) - 1)
    x, y = xy
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    # Her harf ORTAK taban cizgisine oturur. anchor="lt" ile cizince virgul ve
    # iki nokta gibi alcak glifler kendi bbox'larinin tepesinden hizalanip
    # yukari firliyordu ("SAME PARAGRAPH, 8" -> "SAME PARAGRAPH' 8").
    asc, _ = fnt.getmetrics()
    by = y + asc if anchor[1] == "t" else (y + asc / 2 if anchor[1] == "m" else y)
    for ch, wd in zip(text, widths):
        d.text((x, by), ch, font=fnt, fill=fill, anchor="ls")
        x += wd + track


def pill(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def bob(t, amp=6.0, speed=2.4):
    return math.sin(t * speed) * amp


def blink_on(t, period=3.0, off=0.14):
    """Imlec yanip sonmesi -- BYTE'in 'canli' oldugunu gosteren tek sinyal."""
    return (t % period) > off


# ───────────────────────── arka plan ─────────────────────────
def _texture(yy, xx, kind):
    """Doku maskesi (0..1). Hepsi kodla -- stok gorsel yok.
    Cok hafif tutuluyor: amac 'burada bir yuzey var' hissi, desen degil."""
    if kind == "grid":
        g = ((xx % 96 < 1.4) | (yy % 96 < 1.4)).astype(np.float32)
    elif kind == "dots":
        g = (((xx % 64 - 32) ** 2 + (yy % 64 - 32) ** 2) < 5).astype(np.float32)
    elif kind == "scan":
        g = (yy % 5 < 1.2).astype(np.float32) * 0.6
    elif kind == "contour":
        # yuksek frekans + dar esik: genis lekeler yerine ince egri cizgiler
        g = (np.abs(np.sin((xx * 0.021) + np.sin(yy * 0.009) * 3.0)) > 0.9985) \
            .astype(np.float32)
    else:
        return None
    # ust tarafta belirgin, altta kayboluyor: metin alanini kirletmiyor
    return g * np.clip(1 - yy / (H * 0.9), 0, 1)[:, :]


def build_bg():
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    base = np.zeros((H, W, 3), dtype=np.float32)
    for i in range(3):
        base[:, :, i] = BG0[i] + (BG1[i] - BG0[i]) * (y ** 0.75)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    tex = _texture(yy, xx, TEXTURE)
    if tex is not None:
        for i in range(3):
            base[:, :, i] += tex * (GLOW[i] * 0.085)

    dist = np.sqrt(((xx - W / 2) / (W * 0.85)) ** 2 + ((yy - H * 0.26) / (H * 0.40)) ** 2)
    glow = np.clip(1 - dist, 0, 1) ** 2.2
    for i in range(3):
        base[:, :, i] += glow * (GLOW[i] * 0.16)
    vig = np.clip((yy - H * 0.62) / (H * 0.38), 0, 1) ** 2
    base *= (1 - vig[:, :, None] * 0.35)
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


def build_grain(n=6):
    tiles = []
    rng = np.random.default_rng(7)
    for _ in range(n):
        small = rng.normal(0, 1, (H // 5, W // 5, 1)).astype(np.float32)
        small = np.repeat(small, 3, axis=2)
        img = Image.fromarray(np.clip(128 + small * 4, 0, 255).astype(np.uint8))
        tiles.append(np.asarray(img.resize((W, H), Image.NEAREST), dtype=np.int16) - 128)
    return tiles

def build_captions(beats):
    chunks = []
    for b in beats:
        cur = []
        for w in b["words"]:
            cur.append(w)
            if len(cur) >= 4 or len(" ".join(x["w"] for x in cur)) >= 24:
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
    return chunks


def draw_caption(d, t, chunks):
    cur = None
    for ch in chunks:
        if ch[0]["s"] - 0.05 <= t <= ch[-1]["e"] + 0.12:
            cur = ch
            break
    if not cur:
        return
    fnt = F_DISP(58)
    words = [w["w"].upper() for w in cur]
    gap = d.textlength(" ", font=fnt)
    widths = [d.textlength(w, font=fnt) for w in words]
    total = sum(widths) + gap * (len(words) - 1)
    x, y = (W - total) / 2, 1555
    pill(d, (x - 30, y - 16, x + total + 30, y + 84), 22, (10, 10, 18))
    for w, wd, meta in zip(words, widths, cur):
        active = meta["s"] <= t <= meta["e"]
        d.text((x, y), w, font=fnt, fill=MINT if active else (214, 214, 226), anchor="lt")
        x += wd + gap


def draw_chrome(d, t, dur, badge_font):
    p = clamp01(t / dur)
    d.rectangle((0, 0, W, 6), fill=(20, 20, 32))
    d.rectangle((0, 0, W * p, 6), fill=VIOLET)
    draw_byte_badge(d, 72, 150, badge_font, 0.15, B_MINT)
