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

from .byte import draw_byte, draw_byte_sticker, draw_byte_badge, MINT as B_MINT

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
# Yuzeyler ve cizgiler (CTA hapi, ilerleme cubugu, koyu cubuk ustu yazi...). Koyu temalarda ESKI sabit
# degerler; acik/karton temalarda temadan geliyor (themes.py'de "panel" vb. alanlar).
PANEL = (22, 22, 36)           # CTA hapinin dolgusu
PANEL2 = (16, 16, 28)          # kose etiketinin dolgusu
ON_ACCENT = (10, 10, 18)       # vurgu renginin ustundeki yazi
TRACK = (20, 20, 32)           # ilerleme cubugunun izi
SHADOW = (0, 0, 0)             # karton stilinde sert ofset golge
OUTLINE = (24, 22, 28)         # karton stilinde sprite dis cizgisi
STICKER = False                # True -> BYTE kalin dis cizgili cikartma olarak cizilir (karton temalari)


def use_theme(name: str) -> str:
    """Paleti degistirir. build.render en basta bir kez cagiriyor."""
    from .themes import ALL_THEMES as THEMES
    global BG0, BG1, GLOW, INK, MUTE, MINT, AMBER, VIOLET, LINE, TONE
    global TEXTURE, THEME, PANEL, PANEL2, ON_ACCENT, TRACK, SHADOW, OUTLINE, STICKER
    t = THEMES.get(name) or THEMES["midnight"]
    THEME = name if name in THEMES else "midnight"
    BG0, BG1, GLOW = t["bg0"], t["bg1"], t["glow"]
    INK, MUTE, LINE = t["ink"], t["mute"], t["line"]
    MINT, VIOLET, AMBER = t["good"], t["mid"], t["bad"]
    TONE = {"base": INK, "good": MINT, "mid": VIOLET, "bad": AMBER}
    TEXTURE = t["tex"]
    PANEL, PANEL2 = t.get("panel", (22, 22, 36)), t.get("panel2", (16, 16, 28))
    ON_ACCENT, TRACK = t.get("on_accent", (10, 10, 18)), t.get("track", (20, 20, 32))
    SHADOW, OUTLINE = t.get("shadow", (0, 0, 0)), t.get("outline", (24, 22, 28))
    STICKER = "outline" in t
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


@lru_cache(maxsize=None)
def _cjk_file() -> str:
    """CJK fontunu BUL -- dosya adlarini sabit yazma.

    Onceki hali uc sabit yol deniyordu ve Ubuntu 24.04'te fonts-noto-cjk
    paketi dosyayi baska adla koyunca "CJK fontu yok" diye patliyordu;
    font aslinda kuruluydu. Artik once bizim indirdigimiz dosya, sonra
    sistemdeki HERHANGI bir CJK fontu, en son fontconfig.
    """
    own = Path.home() / ".local/share/fonts/cjk/NotoSansJP.ttf"
    if own.exists():
        return str(own)
    for d in ("/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/noto",
              "/usr/share/fonts/opentype", "/usr/share/fonts/truetype",
              "/usr/share/fonts", "/Library/Fonts", "/System/Library/Fonts"):
        base = Path(d)
        if not base.exists():
            continue
        for pat in ("**/NotoSansCJK*", "**/NotoSansJP*", "**/*CJK*",
                    "**/*japanese*", "**/*Gothic*"):
            hits = sorted(base.glob(pat))
            if hits:
                return str(hits[0])
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ja"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        out = ""
    if out and Path(out).exists():
        return out
    raise RuntimeError(
        "CJK fontu bulunamadi. tools/setup_runner.sh calistir "
        "(ya da apt-get install fonts-noto-cjk).")


def cjk_font(size: int) -> ImageFont.FreeTypeFont:
    """Japonca glif icin. Seri B'nin ders sahnesi bunu kullaniyor."""
    p = _cjk_file()
    f = ImageFont.truetype(p, size, index=0) if p.endswith((".ttc", ".otc")) \
        else ImageFont.truetype(p, size)
    # Degisken fontlar varsayilan olarak en ince agirlikta aciliyor; ekranda
    # neredeyse gorunmez oluyorlar.
    try:
        f.set_variation_by_name("Regular")
    except Exception:
        pass
    return f


# ───────────────────────── yardimcilar ─────────────────────────
def byte(d, cx, cy, scale=1.0, pose="idle", cursor=B_MINT, blink=True, cursor_w=1.0):
    """BYTE'i aktif temaya gore cizer: koyu temalarda eskisi gibi; karton temalarinda dis cizgili cikartma."""
    if STICKER:
        draw_byte_sticker(d, cx, cy, scale, pose, cursor, blink, cursor_w, pen=OUTLINE, shadow=SHADOW)
    else:
        draw_byte(d, cx, cy, scale, pose, cursor, blink, cursor_w)


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


def build_paper_bg():
    """Karton stilinin kagit zemini: ust-alt degrade + dusuk frekansli leke + ince tane + kenar kararmasi.
    Sabit tohum: ayni tema ayni kagidi verir (iki render birebir ayni)."""
    rng = np.random.default_rng(11)
    mott = rng.normal(0, 1, (H // 16 + 2, W // 16 + 2)).astype(np.float32)
    mott = np.asarray(Image.fromarray(np.clip(mott * 40 + 128, 0, 255).astype(np.uint8))
                      .resize((W, H), Image.BICUBIC), np.float32) - 128
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    arr = np.zeros((H, W, 3), dtype=np.float32)
    for i in range(3):
        arr[:, :, i] = BG0[i] + (BG1[i] - BG0[i]) * y
    arr += (mott / 128.0)[..., None] * 4.0 + rng.normal(0, 0.9, (H, W, 1)).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    arr *= (1 - 0.05 * r)[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def build_bg():
    if TEXTURE == "paper":
        return build_paper_bg()
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
    d.rectangle((0, 0, W, 6), fill=TRACK)
    d.rectangle((0, 0, W * p, 6), fill=VIOLET)
    draw_byte_badge(d, 72, 150, badge_font, 0.15, B_MINT)


# ── CTA (begen / takip) ──────────────────────────────────────────────────────
HEART = (255, 104, 132)       # tema paletinden bagimsiz: "begen" her yerde ayni kirmizimsi


def heart(d, cx, cy, w, fill):
    """Kalp simgesi: iki daire + ucgen. w = genislik, (cx, cy) = merkez."""
    r = w / 4
    d.ellipse((cx - w / 2, cy - w * 0.46, cx, cy - w * 0.46 + 2 * r), fill=fill)
    d.ellipse((cx, cy - w * 0.46, cx + w / 2, cy - w * 0.46 + 2 * r), fill=fill)
    d.polygon([(cx - w * 0.495, cy - w * 0.14), (cx + w * 0.495, cy - w * 0.14), (cx, cy + w * 0.46)],
              fill=fill)


def plus(d, cx, cy, w, fill, thick=None):
    th = thick or max(3, int(w * 0.16))
    d.rounded_rectangle((cx - w / 2, cy - th / 2, cx + w / 2, cy + th / 2), radius=th / 2, fill=fill)
    d.rounded_rectangle((cx - th / 2, cy - w / 2, cx + th / 2, cy + w / 2), radius=th / 2, fill=fill)


def cta_pill(d, box, kind, label, fnt, a, filled, track=4):
    """Tek chip: simge + yazi. a = gorunurluk (0-1); filled = 'basildi' hali."""
    x0, y0, x1, y1 = box
    cy = (y0 + y1) / 2
    accent = HEART if kind == "like" else VIOLET
    d.rounded_rectangle(box, radius=(y1 - y0) / 2, fill=fade(accent if filled else PANEL, a),
                        outline=fade(accent, a), width=3)
    ink = fade(ON_ACCENT if filled else INK, a)
    icon = fade(ON_ACCENT if filled else accent, a)
    sz = (y1 - y0) * 0.40
    ix = x0 + (y1 - y0) * 0.55
    if kind == "like":
        heart(d, ix, cy + 2, sz, icon)
    else:
        plus(d, ix, cy, sz, icon)
    tracked(d, (ix + sz * 0.9, cy), label, fnt, ink, track=track, anchor="lm")


def cta_row_width(d, labels, fnt, h, gap, track=4):
    ws = []
    for lb in labels:
        tw = sum(d.textlength(ch, font=fnt) for ch in lb) + track * (len(lb) - 1)
        ws.append(h * 0.55 + h * 0.40 * 0.9 + tw + h * 0.55)
    return ws, sum(ws) + gap * (len(ws) - 1)


def draw_cta_corner(d, t, window, text, origin=(72, 214)):
    """Videonun ortasinda sessiz kucuk etiket: sol ust, BYTE rozetinin altinda (guvenli alan:
    ust ~300px sahnelere kapali, Shorts arayuzu sag ustte). window = (bas, bit) saniye."""
    if not window or not text:
        return
    t0, t1 = window
    a = min(clamp01((t - t0) / 0.35), clamp01((t1 - t) / 0.35))
    if a <= 0.01:
        return
    fnt = F_SEMI(26)
    track = 4
    tw = sum(d.textlength(ch, font=fnt) for ch in text) + track * (len(text) - 1)
    h = 54
    x0, y0 = origin[0], origin[1] + (1 - a) * 10
    x1 = x0 + h * 0.55 + 28 + tw + h * 0.5
    d.rounded_rectangle((x0, y0, x1, y0 + h), radius=h / 2, fill=fade(PANEL2, a),
                        outline=fade(MUTE, a * 0.8), width=2)
    heart(d, x0 + h * 0.55, y0 + h / 2 + 1, 22, fade(HEART, a))
    tracked(d, (x0 + h * 0.55 + 22, y0 + h / 2), text, fnt, fade(INK, a), track=track, anchor="lm")
