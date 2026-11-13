"""
Elle cizilmis gibi cizgi ikonlar (garaj, kutu, bina, para, grafik, roket, telefon, kilit).

NEDEN: zaman cizelgesi ve akis sahnesi yalniz nokta + yazi idi; "garajdan ofise" gibi bir hikayede
gozun tutunacagi bir sey yoktu. Burada etiketteki kelimeden OTOMATIK bir ikon secilir ve adimin ustune
cizilir. Senaryo yazarinin (ya da Gemini'nin) hicbir sey eklemesi gerekmez, sema degismedi.

KURALLAR (testlerle kilitli):
  * KELIMEDEN, RASTGELE DEGIL: pick() etiketteki kelimelere bakar; eslesme yoksa None (ikon yok).
    Ayni kelime her zaman ayni ikon: iki render birebir ayni.
  * TUTARLILIK: bir sahnede en az IKI adim ikon alirsa ikonlar cizilir (tek basina duran ikon yersiz durur);
    ayni ikon ikinci kez tekrarlanmaz.
  * SPRITE ONBELLEKTE: her ikon 4x asiri ornekli cizilip kucultulur; kare basina yalniz yapistirma.
  * Resim/stok yok: hepsi cizgi + daire, kod cizer.
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

from PIL import Image, ImageDraw

SS = 4
NAMES = ("garage", "box", "building", "money", "chart", "rocket", "phone", "lock")

# Oncelik sirasi onemli: ilk eslesen kazanir. Kelime SINIRI (\b) kullanilir ki "ship" "relationship"e uymasin.
_RULES = (
    ("garage",   r"garage|basement|workshop|dorm|founded|founder|startup|start-up|prototype"),
    ("lock",     r"hack|hacked|breach|leak|leaked|password|security|encrypt|banned|blocked|privacy|attack|exploit"),
    ("rocket",   r"launch|launched|rocket|goes live|went live|debut|release|released|unveil|unveiled|beta|public"),
    ("money",    r"fund|funding|raise|raised|invest|investment|billion|million|revenue|price|cost|paid|fine|fined|"
                 r"lawsuit|sued|valuation|profit|loss|bankrupt|worth|deal"),
    ("chart",    r"grow|growth|sales|users|traffic|stock|shares|rise|rose|surge|drop|dropped|crash|record|trend|"
                 r"rank|ranked|score|benchmark|percent|%"),
    ("building", r"office|company|headquarter|headquarters|hq|corporate|ipo|bank|campus|acquire|acquired|merge|merged|"
                r"store|court|factory|plant"),
    ("box",      r"box|boxed|package|packages|deliver|delivered|delivery|parcel|order|orders|warehouse|shipped|shipping"),
    ("phone",    r"phone|app|apps|mobile|iphone|android|ios|download|downloads"),
)
_SYMBOLS = {"money": re.compile(r"[$€£]")}          # para birimi simgesi kelime siniri istemez ("$20M")
_RX = tuple((n, re.compile(r"(?<![a-z0-9])(?:" + p + r")(?![a-z0-9])", re.I)) for n, p in _RULES)


def pick(label) -> str | None:
    """Etiketteki kelimeden ikon adi; eslesme yoksa None."""
    if not isinstance(label, str) or not label.strip():
        return None
    low = label.lower()
    for name, rx in _RX:
        if rx.search(low) or (name in _SYMBOLS and _SYMBOLS[name].search(low)):
            return name
    return None


def pick_many(labels) -> list:
    """Bir sahnenin etiketleri icin ikon listesi (ayni uzunlukta). Kurallar: ikinci tekrar yok, <2 eslesme -> hepsi None."""
    seen, out = set(), []
    for lab in labels:
        n = pick(lab)
        if n in seen:
            n = None
        if n:
            seen.add(n)
        out.append(n)
    return out if sum(1 for n in out if n) >= 2 else [None] * len(out)


def _jit(seed: int, i: int, amp: float) -> float:
    h = hashlib.sha256(f"{seed}|{i}".encode()).digest()
    return (h[0] / 255 - 0.5) * 2 * amp


@lru_cache(maxsize=128)
def sprite(name: str, size: int, rgb: tuple, variant: int = 0) -> Image.Image:
    """RGBA sprite (size x size). Elle cizim titremesi icin iki varyant (0/1)."""
    if name not in NAMES:
        raise ValueError(f"bilinmeyen ikon: {name}")
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = tuple(rgb) + (255,)
    wd = max(4, int(S * 0.06))
    seed = sum(map(ord, name)) * 13 + size * 5 + variant * 97
    n = [0]

    def P(x, y):                       # 0..100 koordinat -> piksel (+ hafif titreme)
        k = n[0]
        n[0] += 2
        return (x * S / 100 + _jit(seed, k, S * 0.012), y * S / 100 + _jit(seed, k + 1, S * 0.012))

    def line(*pts, close=False):
        q = [P(*p) for p in pts]
        if close:
            q.append(q[0])
        d.line(q, fill=col, width=wd, joint="curve")
        for x, y in (q[0], q[-1]):
            d.ellipse((x - wd / 2, y - wd / 2, x + wd / 2, y + wd / 2), fill=col)

    def ring(cx, cy, r, steps=28):
        line(*[(cx + r * math.cos(a / steps * math.tau), cy + r * math.sin(a / steps * math.tau))
               for a in range(steps + 1)])

    if name == "garage":
        line((10, 46), (50, 14), (90, 46))                       # catı
        line((18, 40), (18, 88), (82, 88), (82, 40))             # duvarlar
        line((30, 88), (30, 54), (70, 54), (70, 88))             # kapı
        for y in (64, 74):
            line((30, y), (70, y))
    elif name == "box":
        line((50, 12), (88, 32), (88, 70), (50, 90), (12, 70), (12, 32), close=True)
        line((12, 32), (50, 52), (88, 32))
        line((50, 52), (50, 90))
        line((31, 22), (69, 42))                                 # bant
    elif name == "building":
        line((26, 90), (26, 14), (74, 14), (74, 90))
        line((10, 90), (90, 90))
        for r in range(3):
            for c in range(2):
                x, y = 36 + c * 18, 24 + r * 17
                line((x, y), (x + 8, y), (x + 8, y + 8), (x, y + 8), close=True)
        line((45, 90), (45, 74), (55, 74), (55, 90))
    elif name == "money":
        line((8, 28), (92, 28), (92, 72), (8, 72), close=True)
        ring(50, 50, 13)
        for x, y in ((19, 38), (81, 62)):
            ring(x, y, 2.5, 10)
    elif name == "chart":
        line((12, 10), (12, 88), (92, 88))
        for i, h in enumerate((24, 40, 58)):
            x = 26 + i * 22
            line((x, 88), (x, 88 - h), (x + 12, 88 - h), (x + 12, 88))
        line((20, 52), (46, 40), (62, 46), (88, 14))             # trend
        line((74, 14), (88, 14), (88, 28))
    elif name == "rocket":
        line((50, 8), (66, 30), (66, 62), (34, 62), (34, 30), close=True)
        ring(50, 38, 8, 16)
        line((34, 48), (20, 66), (34, 62))                       # kanatlar
        line((66, 48), (80, 66), (66, 62))
        line((42, 68), (50, 90), (58, 68))                       # alev
    elif name == "phone":
        line((30, 8), (70, 8), (70, 92), (30, 92), close=True)
        line((30, 20), (70, 20))
        line((30, 78), (70, 78))
        ring(50, 85, 2.5, 10)
    else:                                                        # lock
        line((24, 46), (76, 46), (76, 90), (24, 90), close=True)
        line((34, 46), (34, 30), (42, 16), (58, 16), (66, 30), (66, 46))
        ring(50, 66, 5, 12)
        line((50, 70), (50, 80))
    return img.resize((size, size), Image.LANCZOS)


def paste(d: ImageDraw.ImageDraw, name: str, cx: float, cy: float, size: int, rgb, a: float = 1.0,
          t: float = 0.0, boil_fps: int = 4) -> None:
    """d'nin resmine ikon yapistirir. a: 0..1 belirme (hem saydamlik hem kucuk "pop"); t: titreme icin zaman."""
    if not name or a <= 0.01:
        return
    a = min(1.0, a)
    s = max(8, int(size * (0.72 + 0.28 * a)))
    sp = sprite(name, s, tuple(int(c) for c in rgb), int(t * boil_fps) % 2)
    mask = sp.split()[3]
    if a < 1.0:
        mask = mask.point(lambda p: int(p * a))
    img = d._image                                                   # ImageDraw'in resmi (byte.py'de de boyle)
    img.paste(Image.new("RGB", sp.size, tuple(int(c) for c in rgb)),
              (int(round(cx - sp.width / 2)), int(round(cy - sp.height / 2))), mask)
