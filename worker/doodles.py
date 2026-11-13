"""
Hareketli karalama arka plani (karton stili).

NEDEN: kagit zemin duragandi; ekranin kenarlarinda hicbir sey olmuyordu ve video "sabit slayt" gibi
duruyordu. Burada zeminde yavasca suzulen, elle cizilmis gibi titreyen kucuk isaretler (arti, halka,
dalga, kıvılcım, ucgen, tire) var: dikkati cekmeden "canli" hissi verir.

KURALLAR (testlerle kilitli):
  * SOLUK: renk, temanin cizgi rengi ile soluk yazi rengi arasinda; yazinin okunurlugunu bozmaz. Sahne
    icerigi ustune cizilir, doodle her zaman ARKADA kalir.
  * KIMLIKTEN SABIT: konum, tur, hiz senaryo kimliginden (sha256) turetilir; iki render birebir ayni.
  * UST BANT BOS: BYTE sunucu ve fosforlu kelime y<330'da; doodle oraya girmez.
  * SPRITE ONBELLEKTE: her tur 3x asiri ornekli cizilip kucultulur (pürüzsüz kenar); kare basina yalniz
    yapistirma yapilir.
"""
from __future__ import annotations

import hashlib
import math
from functools import lru_cache

from PIL import Image, ImageDraw

W, H = 1080, 1920
TOP, BOT = 360, 1500                 # doodle'larin gorunebilecegi bant
KINDS = ("plus", "ring", "squiggle", "spark", "tri", "dash")
COUNT = 9
SS = 3                                # asiri ornekleme
BOIL_FPS = 5                          # elle cizim titremesi: saniyede kac kez baska varyanta gecer


def _u(sid: str, key: str) -> float:
    h = hashlib.sha256(f"{sid}|{key}|doodle1".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


@lru_cache(maxsize=512)
def layout(sid: str, k: int, n: int = COUNT) -> tuple:
    """Sahne k icin n doodle: tur, merkez, boyut, hareket genligi / hizi / fazi. Hepsi kimlikten."""
    out = []
    for j in range(n):
        key = f"{k}_{j}"
        # izgara hucresi + kayma: doodle'lar bir araya yigilmasin
        col, row = j % 3, j // 3
        x = (col + 0.15 + 0.7 * _u(sid, f"x{key}")) / 3 * (W - 80) + 40
        y = TOP + (row + 0.15 + 0.7 * _u(sid, f"y{key}")) / ((n + 2) // 3) * (BOT - TOP)
        out.append({"kind": KINDS[int(_u(sid, f"k{key}") * len(KINDS)) % len(KINDS)],
                    "x": x, "y": y, "size": int(46 + 40 * _u(sid, f"s{key}")),
                    "ax": 10 + 22 * _u(sid, f"ax{key}"), "ay": 8 + 20 * _u(sid, f"ay{key}"),
                    "speed": 0.07 + 0.10 * _u(sid, f"v{key}"), "phase": _u(sid, f"p{key}") * math.tau,
                    "tilt": int(_u(sid, f"t{key}") * 4) % 4})
    return tuple(out)


def _jit(seed: int, i: int, amp: float) -> float:
    h = hashlib.sha256(f"{seed}|{i}".encode()).digest()
    return (h[0] / 255 - 0.5) * 2 * amp


@lru_cache(maxsize=256)
def sprite(kind: str, size: int, rgb: tuple, variant: int) -> Image.Image:
    """RGBA sprite (size x size). variant 0/1: iki "elle cizim" varyanti (titreme icin)."""
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = tuple(rgb) + (255,)
    wd = max(3, int(S * 0.085))
    c = S / 2
    r = S * 0.34
    seed = sum(map(ord, kind)) * 31 + size * 7 + variant * 101

    def J(i, amp=0.035):
        return _jit(seed, i, S * amp)

    def line(pts):
        pts = [(x + J(2 * n), y + J(2 * n + 1)) for n, (x, y) in enumerate(pts)]
        d.line(pts, fill=col, width=wd, joint="curve")
        for x, y in (pts[0], pts[-1]):
            d.ellipse((x - wd / 2, y - wd / 2, x + wd / 2, y + wd / 2), fill=col)

    if kind == "plus":
        line([(c - r, c), (c + r, c)])
        line([(c, c - r), (c, c + r)])
    elif kind == "ring":
        pts = [(c + r * math.cos(a / 24 * math.tau), c + r * math.sin(a / 24 * math.tau)) for a in range(0, 26)]
        line(pts)
    elif kind == "squiggle":
        pts = [(c - r + 2 * r * i / 14, c + 0.35 * r * math.sin(i / 14 * math.tau * 1.5)) for i in range(15)]
        line(pts)
    elif kind == "spark":                      # dort uclu kivilcim: ince "yildiz"
        for a in (0, 90):
            ar = math.radians(a)
            line([(c - r * math.cos(ar), c - r * math.sin(ar)), (c + r * math.cos(ar), c + r * math.sin(ar))])
        line([(c - r * 0.5, c - r * 0.5), (c + r * 0.5, c + r * 0.5)])
        line([(c - r * 0.5, c + r * 0.5), (c + r * 0.5, c - r * 0.5)])
    elif kind == "tri":
        line([(c, c - r), (c + r, c + r * 0.8), (c - r, c + r * 0.8), (c, c - r)])
    else:                                      # dash: iki kisa tire
        line([(c - r, c - r * 0.25), (c + r * 0.2, c - r * 0.25)])
        line([(c - r * 0.4, c + r * 0.3), (c + r, c + r * 0.3)])
    out = img.resize((size, size), Image.LANCZOS)
    return out


def tone(line_rgb, mute_rgb, mix: float = 0.35) -> tuple:
    return tuple(int(round(a + (b - a) * mix)) for a, b in zip(line_rgb, mute_rgb))


def draw(img: Image.Image, t: float, sid: str, k: int, line_rgb, mute_rgb, alpha: float = 0.9) -> int:
    """Doodle'lari img'in uzerine (sahne ICERIGINDEN ONCE) yapistirir. Donus: cizilen sayi."""
    rgb = tone(line_rgb, mute_rgb)
    n = 0
    for dd in layout(sid, k):
        x = dd["x"] + dd["ax"] * math.sin(math.tau * dd["speed"] * t + dd["phase"])
        y = dd["y"] + dd["ay"] * math.cos(math.tau * dd["speed"] * 0.8 * t + dd["phase"])
        v = int(t * BOIL_FPS + dd["phase"] * 3) % 2
        sp = sprite(dd["kind"], dd["size"], rgb, v)
        if alpha < 1:
            a = sp.split()[3].point(lambda p: int(p * alpha))
        else:
            a = sp.split()[3]
        img.paste(Image.new("RGB", sp.size, rgb), (int(x - sp.width / 2), int(y - sp.height / 2)), a)
        n += 1
    return n
