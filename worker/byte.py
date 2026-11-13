#!/usr/bin/env python3
"""
BYTE -- kanalin anlaticisi.

Tasarim kararlari ve SEBEPLERI:

1. YUZ YOK, TEK IMLEC VAR. Yuz cizmek her karede tutarliligi bozar (referans
   hesaplarin yuzsuz karakter kullanmasinin sebebi de bu). BYTE'in tum ifadesi
   ekranindaki tek imlecin RENGI ve GENISLIGI ile tasiniyor:
     nane  = normal/onay      amber = pahali/dikkat
     kirmizi = uyari/yanlis   genis = vurgu
2. ACIKCA MAKINE. YouTube'un Temmuz 2026 politikasi "uzman gibi konusan yapay
   kisilikleri" eliyor. BYTE insan taklidi yapmiyor; verileri okuyan bir bot.
   Konu da AI araclari oldugu icin karakter konuyla birebir ortusuyor.
3. KODLA CIZILIYOR. AI ile uretilen karakter kare kare kayar (drift). Burada
   her poz ayni matematikten cikiyor -- 10.000 videoda da ayni.
4. IRI KAFA (toplam boyun ~%48'i). Thumbnail boyutunda okunmasi icin.
"""
import math

from PIL import Image, ImageDraw, ImageFilter

BODY = (26, 30, 40)
BODY_HI = (46, 52, 68)
SCREEN = (9, 12, 18)
MINT = (74, 222, 128)
AMBER = (255, 176, 32)
RED = (248, 92, 92)
VIOLET = (139, 139, 255)

POSES = ("idle", "point_r", "point_l", "point_up", "shrug", "alert", "cheer", "think", "wave")
GLYPHS = ("", "!", "?", "star")        # ekrandaki imlecin yerine gecen simgeler (yuz DEGIL: yazi karakteri)


def _limb(d, p0, p1, w, fill, rim=None):
    """Uzuv = yuvarlak uclu kalin cizgi. Capsule'u elle hesaplamak yerine
    bunu kullaniyoruz: her acida dogru baglaniyor, omuzda bosluk birakmiyor.

    rim: govde rengi arka plana cok yakin oldugu icin buyuk olceklerde siluet
    kayboluyordu. Once biraz kalin bir rim cizip uzerine govdeyi koyuyoruz."""
    if rim:
        d.line([p0, p1], fill=rim, width=int(max(3, w + 6)), joint="curve")
        r2 = (w + 6) / 2
        for (x, y) in (p0, p1):
            d.ellipse((x - r2, y - r2, x + r2, y + r2), fill=rim)
    d.line([p0, p1], fill=fill, width=int(max(2, w)), joint="curve")
    r = w / 2
    for (x, y) in (p0, p1):
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


# poz -> (sol el, sag el) govde-merkezli koordinat
_HANDS = {
    "idle":     ((-112, 78), (112, 78)),
    "point_r":  ((-104, 74), (170, -42)),
    "point_l":  ((-170, -42), (104, 74)),
    "point_up": ((-104, 74), (166, -178)),
    "shrug":    ((-152, -58), (152, -58)),
    "alert":    ((-136, -32), (136, -32)),
    "cheer":    ((-150, -128), (150, -128)),     # iki kol havada
    "think":    ((-104, 74), (86, -28)),         # el cenenin altinda
    "wave":     ((-104, 74), (156, -112)),       # sag el sallaniyor (anim ile)
}


def _hands(pose: str, anim: float):
    """Poz -> (sol el, sag el). anim (sn) verilirse 'wave' ve 'cheer' kollari oynar; digerleri sabit."""
    lh, rh = _HANDS[pose]
    if pose == "wave":
        w = math.sin(anim * math.tau * 2.4)
        rh = (rh[0] + 24 * w, rh[1] - 10 * abs(w))
    elif pose == "cheer":
        w = math.sin(anim * math.tau * 2.0)
        lh, rh = (lh[0], lh[1] + 18 * w), (rh[0], rh[1] - 18 * w)
    return lh, rh


def draw_byte(d: ImageDraw.ImageDraw, cx: float, cy: float, scale: float = 1.0,
              pose: str = "idle", cursor=MINT, blink: bool = True,
              cursor_w: float = 1.0, glyph: str = "", anim: float = 0.0) -> None:
    """cy = govdenin DIKEY MERKEZI. Toplam yukseklik ~ 400*scale.
    glyph: imlec yerine ekranda bir simge ('!', '?', 'star'); anim: saniye, 'wave'/'cheer' kollarini oynatir."""
    s = scale

    def P(x, y):
        return (cx + x * s, cy + y * s)

    rim = BODY_HI

    # ── bacaklar ──
    for x0, x1 in ((-48, -16), (16, 48)):
        _limb(d, P((x0 + x1) / 2, 100), P((x0 + x1) / 2, 158), 32 * s, BODY, rim)

    # ── kollar (govdenin ALTINA cizilir ki omuz temiz dursun) ──
    lh, rh = _hands(pose, anim)
    for (hx, hy), sx in ((lh, -66), (rh, 66)):
        _limb(d, P(sx, 6), P(hx, hy), 28 * s, BODY, rim)
        p = P(hx, hy)
        r = 21 * s
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=BODY_HI)

    # ── govde ──
    d.rounded_rectangle((*P(-74, -16), *P(74, 104)), radius=34 * s, fill=BODY,
                        outline=rim, width=int(max(2, 4 * s)))

    # ── boyun ──
    d.rounded_rectangle((*P(-19, -44), *P(19, -10)), radius=9 * s, fill=BODY)

    draw_byte_head(d, cx, cy - 130 * s, scale, cursor, blink, cursor_w, glyph)


def draw_byte_sticker(d: ImageDraw.ImageDraw, cx: float, cy: float, scale: float = 1.0,
                      pose: str = "idle", cursor=MINT, blink: bool = True, cursor_w: float = 1.0,
                      pen=(28, 26, 34), shadow=None, shadow_off: int = 5, px: int = 5, k: int = 2,
                      glyph: str = "", anim: float = 0.0) -> None:
    """Karton stili: BYTE kalin dis cizgili 'cikartma' olarak (k kat asiri ornekleme, yumusak kenar) +
    sert ofset golge. Ayni cizim, ustune dis cizgi: koyu govde lacivert zeminde de okunur.
    d'nin bagli oldugu resme dogrudan yapistirir."""
    img = d._image                                                   # ImageDraw'in resmi
    s = scale * k
    wl, hl = int(480 * s), int(470 * s)
    cl, ch = wl / 2, 240 * s
    sp = Image.new("RGBA", (wl, hl), (0, 0, 0, 0))
    draw_byte(ImageDraw.Draw(sp), cl, ch, s, pose, cursor, blink, cursor_w, glyph, anim)
    m = int(px * k + 8 + shadow_off * k)
    base = Image.new("RGBA", (wl + 2 * m, hl + 2 * m), (0, 0, 0, 0))
    base.paste(sp, (m, m))
    g = base.split()[3].filter(ImageFilter.GaussianBlur(px * k / 1.64)).point(lambda v: 255 if v > 12 else 0)
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    if shadow is not None and shadow_off:
        out.paste(Image.new("RGBA", base.size, tuple(shadow) + (255,)), (shadow_off * k, shadow_off * k), g)
    out.paste(Image.new("RGBA", base.size, tuple(pen) + (255,)), (0, 0), g)
    out.alpha_composite(base)
    out = out.resize((max(1, out.width // k), max(1, out.height // k)), Image.LANCZOS)
    img.paste(out.convert("RGB"), (int(round(cx - (cl + m) / k)), int(round(cy - (ch + m) / k))),
              out.split()[3])


def _glyph(d, P, s, glyph, cursor) -> None:
    """Ekrandaki simge: imlecin yerine gecer. Yuz cizmiyoruz; bunlar yazi karakteri ('!', '?') ve bir kivilcim."""
    if glyph == "!":
        d.rounded_rectangle((*P(-11, -46), *P(11, 8)), radius=9 * s, fill=cursor)
        d.ellipse((*P(-12, 22), *P(12, 46)), fill=cursor)
    elif glyph == "?":
        w = int(max(3, 15 * s))
        d.arc((*P(-27, -50), *P(27, 4)), start=180, end=90, fill=cursor, width=w)
        d.line([P(0, 4), P(0, 12)], fill=cursor, width=w)
        d.ellipse((*P(-11, 26), *P(11, 48)), fill=cursor)
    elif glyph == "star":
        pts = [(0, -50), (11, -11), (50, 0), (11, 11), (0, 50), (-11, 11), (-50, 0), (-11, -11)]
        d.polygon([P(x, y) for x, y in pts], fill=cursor)


def draw_byte_head(d: ImageDraw.ImageDraw, cx: float, cy: float, scale: float = 1.0,
                   cursor=MINT, blink: bool = True, cursor_w: float = 1.0, glyph: str = "") -> None:
    """Sadece CRT kafa. cy = kafanin DIKEY MERKEZI. Yukseklik ~184*scale.
    Avatar/ikon icin bunu kullan: 32 pikselde govde okunmuyor, kafa okunuyor.
    glyph verilirse imlec yerine o simge (hep gorunur, yanip sonmez)."""
    s = scale

    def P(x, y):
        return (cx + x * s, cy + y * s)

    d.rounded_rectangle((*P(-116, -92), *P(116, 92)), radius=48 * s, fill=BODY)
    d.rounded_rectangle((*P(-116, -92), *P(116, 92)), radius=48 * s,
                        outline=BODY_HI, width=int(max(2, 5 * s)))
    d.rounded_rectangle((*P(-94, -72), *P(94, 72)), radius=32 * s, fill=SCREEN)
    if glyph in ("!", "?", "star"):
        _glyph(d, P, s, glyph, cursor)
    elif blink:
        w = 15 * cursor_w
        d.rounded_rectangle((*P(-w, -28), *P(w, 28)), radius=6 * s, fill=cursor)


def draw_byte_pointing(d: ImageDraw.ImageDraw, cx: float, cy: float,
                       target: tuple, scale: float = 1.0, cursor=MINT,
                       blink: bool = True, reach: float = 1.0) -> None:
    """BYTE elinde bir cubukla ekrandaki bir noktayi gosteriyor.

    Yuz cizmedigimiz icin "suraya bak" diyebilmenin tek yolu bu. Yuz
    cizmemek bilincli: her karede tutarlilik + YouTube'un "uzman gibi
    konusan yapay kisilik" maddesinden uzak durmak.

    target: cubugun ucunun isaret edecegi mutlak (x, y). reach 0..1 ile
    cubuk hedefe dogru aciliyor (beat basinda uzaniyor).
    """
    import math
    s = scale

    def P(x, y):
        return (cx + x * s, cy + y * s)

    rim = BODY_HI
    # bacaklar
    for x0, x1 in ((-48, -16), (16, 48)):
        _limb(d, P((x0 + x1) / 2, 100), P((x0 + x1) / 2, 158), 32 * s, BODY, rim)

    # bos el
    _limb(d, P(-66, 6), P(-112, 78), 28 * s, BODY, rim)
    p = P(-112, 78)
    r = 21 * s
    d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=BODY_HI)

    # gosteren kol: omuzdan hedefe dogru, sabit uzunlukta
    sh = P(66, 6)
    dx, dy = target[0] - sh[0], target[1] - sh[1]
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    arm = 96 * s
    hand = (sh[0] + ux * arm, sh[1] + uy * arm)
    _limb(d, sh, hand, 28 * s, BODY, rim)
    d.ellipse((hand[0] - r, hand[1] - r, hand[0] + r, hand[1] + r), fill=BODY_HI)

    # cubuk: elden hedefe. Ucu imlec rengiyle -- goz once oraya gidiyor.
    tipx = hand[0] + ux * (L - arm) * reach
    tipy = hand[1] + uy * (L - arm) * reach
    d.line([hand, (tipx, tipy)], fill=BODY_HI, width=int(max(3, 9 * s)))
    tr = max(5, 11 * s)
    d.ellipse((tipx - tr, tipy - tr, tipx + tr, tipy + tr), fill=cursor)

    # govde + boyun + kafa
    d.rounded_rectangle((*P(-74, -16), *P(74, 104)), radius=34 * s, fill=BODY,
                        outline=rim, width=int(max(2, 4 * s)))
    d.rounded_rectangle((*P(-19, -44), *P(19, -10)), radius=9 * s, fill=BODY)
    draw_byte_head(d, cx, cy - 130 * s, s, cursor, blink)


def draw_byte_badge(d: ImageDraw.ImageDraw, x: float, y: float, font,
                    scale: float = 0.17, cursor=MINT) -> None:
    """Kose imzasi: kucuk BYTE + wordmark. Her videoda ayni yerde."""
    draw_byte(d, x + 34, y + 10, scale, "idle", cursor)
    d.text((x + 78, y - 12), "BYTE", font=font, fill=(150, 150, 176), anchor="lt")


if __name__ == "__main__":
    # Poz sayfasi: gozle kontrol icin
    from PIL import Image, ImageFont
    W, H = 1600, 620
    img = Image.new("RGB", (W, H), (10, 10, 16))
    dr = ImageDraw.Draw(img)
    f = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", 26)
    cols = {"idle": MINT, "point_r": MINT, "point_l": VIOLET,
            "point_up": MINT, "shrug": AMBER, "alert": RED}
    for i, p in enumerate(POSES):
        x = 140 + i * 255
        draw_byte(dr, x, 300, 0.55, p, cols[p])
        dr.text((x, 520), p, font=f, fill=(130, 130, 155), anchor="mt")
    draw_byte_badge(dr, 60, 580, f)
    img.save("out/byte_poses.png")
    print("out/byte_poses.png")
