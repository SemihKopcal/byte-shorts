"""
Sahne katalogu.

Her sahne KODLA ciziliyor -- stok gorsel, AI gorseli, video yok. Cesitlilik
"farkli gorsel kaynagi"ndan degil, "farkli anlatim bicimi"nden geliyor:
ayni palet, ayni tipografi, ayni BYTE, ama her beat'te baska bir sunum.

Bu neden onemli: YouTube'un Temmuz 2026 kurallari birbirinin ayni kaliptan
cikmis videolari eliyor. Gorsel dili sabit tutup DIZILIMI degistirmek, hem
o kurala takilmamanin hem de kanalin taninir kalmasinin yolu.

Her sahne ayni imzaya sahip:
    fn(d, t, t0, t1, data) -> None
        d     : ImageDraw
        t     : su anki saniye
        t0,t1 : sahnenin baslangic/bitis saniyesi
        data  : senaryodaki beat["data"] sozlugu

Senaryo yazan (ben ya da Gemini) sadece sahnenin ADINI ve data'sini veriyor.
Yeni sahne eklemek = bu dosyaya bir fonksiyon + CATALOG'a bir satir.
"""
from . import draw as D
from .byte import draw_byte, MINT as B_MINT, AMBER as B_AMBER, RED as B_RED, VIOLET as B_VIOLET

# Guvenli icerik alani: ust 300px baslik/chrome, alt 1430'dan sonrasi altyazi
TOP = 420
BOT = 1400
MARGIN = 90
MIDX = D.W / 2

_CURSOR = {"mint": B_MINT, "amber": B_AMBER, "red": B_RED, "violet": B_VIOLET}


def _tone(name):
    return D.TONE.get(name, D.INK)


def _fit(d, text, mk, size, max_w, min_size=28):
    """Metni kutuya sigdiran font. Uzun baslikta tasma yerine kuculme."""
    while size > min_size and d.textlength(text, font=mk(size)) > max_w:
        size -= 2
    return mk(size)


def _lines(d, lines, y, mk, size, fill, gap=1.18, t=None, t0=None, stagger=0.09):
    """Satirlari ortalayarak yazar; t verilirse satir satir beliriyor."""
    for i, ln in enumerate(lines):
        a = 1.0 if t is None else D.appear(t, t0 + i * stagger)
        if a <= 0.01:
            continue
        f = _fit(d, ln, mk, size, D.W - 2 * MARGIN)
        yy = y + i * size * gap - (1 - a) * 18
        d.text((MIDX, yy), ln, font=f, fill=D.fade(fill, a), anchor="mt")
    return y + len(lines) * size * gap


# ─────────────────────────── sahneler ───────────────────────────
def title(d, t, t0, t1, data):
    """Buyuk baslik. Hook ve gecis cumleleri icin.
    data: {kicker?, lines[], accent?}"""
    y = TOP + 160
    if data.get("kicker"):
        a = D.appear(t, t0)
        D.tracked(d, (MIDX, y - 110), data["kicker"].upper(), D.F_SEMI(34),
                  D.fade(D.MUTE, a), track=7, anchor="mt")
    accent = _tone(data.get("accent", "base"))
    lines = data.get("lines", [])
    # son satir vurgulu: goz nereye bakacagini bilsin
    for i, ln in enumerate(lines):
        a = D.appear(t, t0 + 0.10 + i * 0.12)
        if a <= 0.01:
            continue
        last = i == len(lines) - 1
        f = _fit(d, ln, D.F_HUGE if last else D.F_DISP, 104 if last else 86,
                 D.W - 2 * MARGIN)
        col = accent if last else D.INK
        s = D.punch(t, t0 + 0.10 + i * 0.12) if last else 1.0
        d.text((MIDX, y + i * 118 - (1 - a) * 22), ln, font=f,
               fill=D.fade(col, a), anchor="mt")


def contrast(d, t, t0, t1, data):
    """Iki sayi yan yana; biri digerini eziyor. Hook'un en guclu bicimi.
    data: {left:{label,value}, right:{label,value}, verdict?}"""
    a = D.appear(t, t0)
    b = D.appear(t, t0 + 0.28)
    cy = TOP + 300
    for side, al, x in (("left", a, D.W * 0.27), ("right", b, D.W * 0.73)):
        it = data.get(side, {})
        if al <= 0.01:
            continue
        big = side == "right"
        col = _tone(it.get("tone", "bad" if big else "base"))
        f = _fit(d, str(it.get("value", "")), D.F_HUGE, 150 if big else 112,
                 D.W * 0.42)
        s = D.punch(t, t0 + (0.28 if big else 0.0), amt=0.08)
        d.text((x, cy - (1 - al) * 20), str(it.get("value", "")), font=f,
               fill=D.fade(col, al), anchor="mm")
        D.tracked(d, (x, cy + 110), str(it.get("label", "")).upper(),
                  D.F_SEMI(32), D.fade(D.MUTE, al), track=6, anchor="mt")
    # ayirici
    if b > 0.1:
        d.rectangle((MIDX - 2, cy - 110, MIDX + 2, cy + 90), fill=D.fade(D.LINE, b))
    if data.get("verdict"):
        v = D.appear(t, t0 + 0.75)
        if v > 0.01:
            f = _fit(d, data["verdict"], D.F_DISP, 62, D.W - 2 * MARGIN)
            d.text((MIDX, cy + 250), data["verdict"], font=f,
                   fill=D.fade(D.INK, v), anchor="mt")


def table(d, t, t0, t1, data):
    """Satir satir acilan tablo. Olculmus veriyi gostermenin en net yolu.
    data: {unit?, rows:[{name,value,ratio?,tone?,beat_at?}]}"""
    rows = data.get("rows", [])[:6]
    y = TOP + 60
    if data.get("unit"):
        D.tracked(d, (MARGIN, y - 56), str(data["unit"]).upper(), D.F_SEMI(30),
                  D.fade(D.MUTE, D.appear(t, t0)), track=7)
    h = min(150, (BOT - y - 60) / max(1, len(rows)))
    maxr = max([float(r.get("ratio", 1) or 1) for r in rows] + [1.0])
    for i, r in enumerate(rows):
        a = D.appear(t, t0 + 0.12 + i * 0.16)
        if a <= 0.01:
            continue
        yy = y + i * h + (1 - a) * 16
        col = _tone(r.get("tone", "base"))
        # oran cubugu: sayiyi okumadan da buyuklugu gorunur yapiyor
        bw = (D.W - 2 * MARGIN) * (float(r.get("ratio", 1) or 1) / maxr) * a
        d.rounded_rectangle((MARGIN, yy + h - 26, MARGIN + bw, yy + h - 16),
                            radius=5, fill=D.fade(col, 0.55 * a))
        D.tracked(d, (MARGIN, yy), str(r.get("name", "")).upper(), D.F_SEMI(44),
                  D.fade(D.INK, a), track=3)
        f = _fit(d, str(r.get("value", "")), D.F_DISP, 56, D.W * 0.38)
        d.text((D.W - MARGIN, yy - 4), str(r.get("value", "")), font=f,
               fill=D.fade(col, a), anchor="rt")
        d.rectangle((MARGIN, yy + h - 8, D.W - MARGIN, yy + h - 7),
                    fill=D.fade(D.LINE, a))


def bars(d, t, t0, t1, data):
    """Buyuyen cubuklar. Tablodan farki: karsilastirma GORSEL, sayi ikincil.
    data: {unit?, rows:[{name,v,label?,tone?}]}"""
    rows = data.get("rows", [])[:5]
    vals = [float(r.get("v", 0) or 0) for r in rows] or [1.0]
    mx = max(vals) or 1.0
    y = TOP + 80
    h = min(190, (BOT - y - 40) / max(1, len(rows)))
    for i, r in enumerate(rows):
        a = D.appear(t, t0 + 0.15 + i * 0.22, dur=0.55)
        if a <= 0.01:
            continue
        yy = y + i * h
        col = _tone(r.get("tone", "base"))
        full = (D.W - 2 * MARGIN) * (float(r.get("v", 0) or 0) / mx)
        D.tracked(d, (MARGIN, yy), str(r.get("name", "")).upper(), D.F_SEMI(38),
                  D.fade(D.MUTE, min(1, a * 2)), track=5)
        d.rounded_rectangle((MARGIN, yy + 52, MARGIN + max(8, full * a), yy + 116),
                            radius=10, fill=D.fade(col, 0.9))
        # Etiket cubugun sagina yazilir; sigmiyorsa ICINE alinir. Aksi halde
        # en uzun cubugun etiketi ekranin disina tasiyor ("$7.." gibi).
        lab = str(r.get("label", r.get("v", "")))
        if a > 0.6:
            la = (a - 0.6) / 0.4
            lw = d.textlength(lab, font=D.F_DISP(44))
            bx = MARGIN + max(8, full * a)
            if bx + 20 + lw < D.W - MARGIN:
                d.text((bx + 20, yy + 58), lab, font=D.F_DISP(44),
                       fill=D.fade(col, la), anchor="lt")
            else:
                d.text((bx - 20, yy + 58), lab, font=D.F_DISP(44),
                       fill=D.fade((10, 10, 16), la), anchor="rt")


def counter(d, t, t0, t1, data):
    """Sayarak yukselen sayi; esikte renk degistiriyor.
    data: {prefix?,suffix?,from,to,threshold?,note?,secs?}"""
    dur = float(data.get("secs", min(1.6, max(0.8, (t1 - t0) * 0.6))))
    v = D.countup(t, t0 + 0.15, dur, float(data.get("from", 0)),
                  float(data.get("to", 0)))
    thr = data.get("threshold")
    col = _tone(data.get("tone", "base"))
    if thr is not None and v >= float(thr):
        col = _tone(data.get("tone_over", "bad"))
    txt = f"{data.get('prefix','')}{v:,.{int(data.get('dp',0))}f}{data.get('suffix','')}"
    f = _fit(d, txt, D.F_HUGE, 190, D.W - 2 * MARGIN)
    a = D.appear(t, t0)
    d.text((MIDX, TOP + 300), txt, font=f, fill=D.fade(col, a), anchor="mm")
    if data.get("note"):
        n = D.appear(t, t0 + 0.4)
        f2 = _fit(d, data["note"], D.F_DISP, 58, D.W - 2 * MARGIN)
        d.text((MIDX, TOP + 430), data["note"], font=f2,
               fill=D.fade(D.MUTE, n), anchor="mt")


def split(d, t, t0, t1, data):
    """Ekran ikiye bolunuyor. 'Bu mu, su mu' anlarinda.
    data: {a:{label,sub?,tone?}, b:{label,sub?,tone?}}"""
    a0 = D.appear(t, t0)
    a1 = D.appear(t, t0 + 0.22)
    midy = (TOP + BOT) / 2
    d.rectangle((MARGIN, midy - 2, D.W - MARGIN, midy + 2),
                fill=D.fade(D.LINE, a1))
    for key, al, cy in (("a", a0, midy - 190), ("b", a1, midy + 190)):
        it = data.get(key, {})
        if al <= 0.01:
            continue
        col = _tone(it.get("tone", "base" if key == "a" else "bad"))
        f = _fit(d, str(it.get("label", "")), D.F_HUGE, 96, D.W - 2 * MARGIN)
        d.text((MIDX, cy - (1 - al) * 14), str(it.get("label", "")), font=f,
               fill=D.fade(col, al), anchor="mm")
        if it.get("sub"):
            D.tracked(d, (MIDX, cy + 76), str(it["sub"]).upper(), D.F_SEMI(32),
                      D.fade(D.MUTE, al), track=6, anchor="mt")


def timeline(d, t, t0, t1, data):
    """Soldan saga akan adimlar. 'Once su oldu, sonra bu' icin.
    data: {steps:[{at,label,tone?}]}"""
    steps = data.get("steps", [])[:5]
    if not steps:
        return
    x0, x1 = MARGIN + 30, D.W - MARGIN - 30
    y = TOP + 260
    prog = D.clamp01((t - t0 - 0.2) / max(0.6, (t1 - t0) * 0.55))
    d.rectangle((x0, y - 2, x1, y + 2), fill=D.fade(D.LINE, D.appear(t, t0)))
    d.rectangle((x0, y - 3, x0 + (x1 - x0) * prog, y + 3),
                fill=D.fade(D.VIOLET, 1.0))
    n = len(steps)
    for i, s in enumerate(steps):
        px = x0 + (x1 - x0) * (i / max(1, n - 1))
        a = D.clamp01((prog - i / max(1, n - 1)) * 6)
        if a <= 0.01:
            continue
        col = _tone(s.get("tone", "base"))
        r = 13 + 5 * a
        d.ellipse((px - r, y - r, px + r, y + r), fill=D.fade(col, a))
        D.tracked(d, (px, y - 70), str(s.get("at", "")).upper(), D.F_SEMI(30),
                  D.fade(D.MUTE, a), track=5, anchor="mb")
        lab = str(s.get("label", ""))
        f = _fit(d, lab, D.F_DISP, 40, (x1 - x0) / max(1, n) + 60)
        d.text((px, y + 46), lab, font=f, fill=D.fade(D.INK, a), anchor="mt")


def byte_says(d, t, t0, t1, data):
    """BYTE buyuk, tek satir. Vurgu ve nefes icin -- her videoda 1-2 kez.
    data: {line?, pose?, cursor?}"""
    a = D.appear(t, t0)
    # 1.25 olcek ~ 500px govde: dikey karede BYTE'in okunur oldugu en kucuk boy.
    # 0.72'de thumbnail boyutunda silik bir leke oluyordu.
    cy = TOP + 300 + D.bob(t)
    draw_byte(d, MIDX, cy, 1.25 * (0.92 + 0.08 * a), data.get("pose", "point_up"),
              _CURSOR.get(data.get("cursor", "mint"), B_MINT),
              D.blink_on(t), 1.0)
    if data.get("line"):
        l = D.appear(t, t0 + 0.3)
        f = _fit(d, data["line"], D.F_DISP, 64, D.W - 2 * MARGIN)
        d.text((MIDX, cy + 300), data["line"], font=f,
               fill=D.fade(D.INK, l), anchor="mt")


def close(d, t, t0, t1, data):
    """Kapanis karti. Altyazi burada kapaniyor, metin zaten ekranda.
    data: {line?, lines?, handle?}"""
    lines = data.get("lines") or ([data["line"]] if data.get("line") else [])
    y = TOP + 220
    for i, ln in enumerate(lines[:3]):
        a = D.appear(t, t0 + 0.1 + i * 0.18)
        if a <= 0.01:
            continue
        last = i == len(lines) - 1
        f = _fit(d, ln, D.F_HUGE if last else D.F_DISP, 96 if last else 74,
                 D.W - 2 * MARGIN)
        col = _tone(data.get("accent", "base")) if last else D.MUTE
        d.text((MIDX, y + i * 120), ln, font=f, fill=D.fade(col, a), anchor="mt")
    h = D.appear(t, t0 + 0.9)
    # BYTE once, handle en altta: ikisi de 1400'un (altyazi bandi) ustunde kalmali
    draw_byte(d, MIDX, y + 480 + D.bob(t, 4), 0.62, "idle", B_MINT, D.blink_on(t))
    if h > 0.01 and data.get("handle"):
        D.tracked(d, (MIDX, y + 690), str(data["handle"]).upper(), D.F_SEMI(36),
                  D.fade(D.MUTE, h), track=8, anchor="mt")


CATALOG = {
    "title": title,
    "contrast": contrast,
    "table": table,
    "bars": bars,
    "counter": counter,
    "split": split,
    "timeline": timeline,
    "byte_says": byte_says,
    "close": close,
}

# Senaryo yazarina verilen liste. qc.py bunu dogrulamada kullaniyor.
NAMES = tuple(CATALOG)
