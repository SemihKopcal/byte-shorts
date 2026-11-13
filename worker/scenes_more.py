"""
Sahne katalogu, ikinci tur: scenes.py'deki dokuz sahneye eklenen on bes sahne.

Ayri dosya cunku scenes.py zaten dokuz sahne + yardimcilarla dolu; buradakiler
ayni imzayi kullanir ve scenes.py'nin sonunda CATALOG'a eklenir:

    fn(d, t, t0, t1, data) -> None

Kurallar scenes.py ile ayni:
  * guvenli alan TOP..BOT (330..1430), yerlesim MID (880) etrafinda;
  * uzun metin tasmaz, kuculur ya da satira bolunur;
  * bos ya da eksik data PATLAMAZ (sahne bos kalir). Senaryo yazani Gemini de
    olabilir; bir eksik alan yuzunden 4 dakikalik render'in sonunda kirmizi
    yanmak istemiyoruz;
  * bir sahne birden fazla beat boyunca ekranda kalabilir (t1 - t0 uzun olabilir),
    o yuzden hareketler t0'a gore zaman asimina degil, mutlak sureye bagli.

Ses/altyazi/BYTE rozeti bu dosyanin isi degil (build.render ekliyor).
"""
import math
import random
import re

from . import draw as D
from . import scenes as S


# ─────────────────────────── yardimcilar ───────────────────────────
def _dim():
    """Cizgi/iz rengi: LINE'dan belirgin, MUTE'tan koyu."""
    return D.mix(D.LINE, D.MUTE, 0.45)


def _panel():
    """Kart/balon zemini: arka plana hafifce yaklasan beyaz."""
    return D.mix(D.BG0, D.INK, 0.075)


def _wrap(d, text, font, max_w):
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if not cur or d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _wrap_fit(d, text, mk, size, max_w, max_lines=3, min_size=30):
    """(font, satirlar): en fazla max_lines satira, her satir max_w icine."""
    while True:
        f = mk(size)
        lines = _wrap(d, text, f, max_w)
        if (len(lines) <= max_lines
                and all(d.textlength(ln, font=f) <= max_w for ln in lines)) or size <= min_size:
            return f, lines
        size -= 2


def _items(data, key, n):
    """data[key] listesinden ilk n SOZLUK (baska tur ogeler atlanir)."""
    v = data.get(key)
    return [x for x in v if isinstance(x, dict)][:n] if isinstance(v, list) else []


def _int(v, default, lo, hi):
    """Bozuk girdide patlamayan tam sayi: sinirlar icinde, olmazsa default."""
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError, OverflowError):
        return default


def _num(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _mono(d, x, y, text, size, fill, pitch, anchor_y="m"):
    """Sabit aralikli yazi. Mono font dosyasina bagimli olmamak icin Inter'i
    harf harf, ayni adimla diziyoruz (font bulunamazsa videoyu sessizce
    bozmak yerine patlamak kuraldi; burada bulunacak font zaten Inter)."""
    f = D.F_SEMI(size)
    for k, ch in enumerate(text):
        if ch != " ":
            d.text((x + k * pitch + pitch / 2, y), ch, font=f, fill=fill, anchor="m" + anchor_y)


def _pow10(d, cx, y, k, fill, size=30):
    """10^k: ussu kucuk, taban cizgisine oturan."""
    f, f2 = D.F_SEMI(size), D.F_SEMI(int(size * 0.66))
    base, sup = "10", str(k)
    w = d.textlength(base, font=f) + d.textlength(sup, font=f2) + 2
    x = cx - w / 2
    d.text((x, y), base, font=f, fill=fill, anchor="ls")
    d.text((x + d.textlength(base, font=f) + 2, y - size * 0.45), sup, font=f2, fill=fill, anchor="ls")


# ─────────────────────────── sahneler ───────────────────────────
def steps(d, t, t0, t1, data):
    """Numarali adimlar, ust uste. timeline'dan farki: yatay zaman degil, dikey islem sirasi.
    data: {steps:[{label, sub?, tone?}]  (en cok 4)}"""
    items = _items(data, "steps", 4)
    n = len(items)
    if not n:
        return
    h = min(260, (S.BOT - S.TOP - 80) / n)
    y0 = S.MID - n * h / 2
    cx = S.MARGIN + 52
    prog = D.clamp01((t - t0 - 0.1) / (0.35 * n + 0.2))
    if n > 1:
        ya, yb = y0 + h / 2, y0 + (n - 1) * h + h / 2
        d.rectangle((cx - 2, ya, cx + 2, ya + (yb - ya) * prog), fill=_dim())
    for i, it in enumerate(items):
        a = D.appear(t, t0 + 0.1 + i * 0.35)
        if a <= 0.01:
            continue
        col = S._tone(it.get("tone", "base"))
        yc = y0 + i * h + h / 2
        r = 46
        d.ellipse((cx - r, yc - r, cx + r, yc + r), fill=D.fade(col, 0.2 * a),
                  outline=D.fade(col, a), width=5)
        d.text((cx, yc - 2), str(i + 1), font=D.F_DISP(52), fill=D.fade(col, a), anchor="mm")
        tx = cx + 90 - (1 - a) * 24
        mw = D.W - S.MARGIN - (cx + 90)
        sub = it.get("sub")
        f = S._fit(d, str(it.get("label", "")), D.F_DISP, 60, mw)
        d.text((tx, yc - (26 if sub else 0)), str(it.get("label", "")), font=f,
               fill=D.fade(D.INK, a), anchor="lm")
        if sub:
            f2 = S._fit(d, str(sub), D.F_MED, 38, mw)
            d.text((tx, yc + 38), str(sub), font=f2, fill=D.fade(D.MUTE, a), anchor="lm")


def flow(d, t, t0, t1, data):
    """Kutular ve oklar: girdi -> islem -> cikti. Oklar uzerinde bir paket akar.
    data: {nodes:[{label, sub?, tone?}] (2-4), arrows?:[okun yanindaki kisa yazilar]}"""
    nodes = _items(data, "nodes", 4)
    n = len(nodes)
    if not n:
        return
    bh = 150 if n <= 3 else 136
    gap = min(130.0, (S.BOT - S.TOP - 80 - n * bh) / (n - 1)) if n > 1 else 0.0
    y0 = S.MID - (n * bh + (n - 1) * gap) / 2
    bw = 780
    x0 = S.MIDX - bw / 2
    labels = data.get("arrows") if isinstance(data.get("arrows"), list) else []
    icons = S.ICONS.pick_many([str(nd.get("label", "")) for nd in nodes])   # etiketten otomatik ikon
    shift = 52 if any(icons) else 0                  # ikon varsa yazi biraz saga kayar (hepsinde ayni: hizali)
    for i, nd in enumerate(nodes):
        a = D.appear(t, t0 + 0.1 + i * 0.4)
        yy = y0 + i * (bh + gap)
        if a > 0.01:
            col = S._tone(nd.get("tone", "base"))
            yo = yy - (1 - a) * 20
            d.rounded_rectangle((x0, yo, x0 + bw, yo + bh), radius=28,
                                fill=D.fade(col, 0.13 * a), outline=D.fade(col, a), width=4)
            if icons[i]:
                S.ICONS.paste(d, icons[i], x0 + 84, yo + bh / 2, 88, col, a, t)
            sub = nd.get("sub")
            tx = S.MIDX + shift
            f = S._fit(d, str(nd.get("label", "")), D.F_DISP, 58, bw - 80 - 2 * shift)
            d.text((tx, yo + bh / 2 - (24 if sub else 0)), str(nd.get("label", "")),
                   font=f, fill=D.fade(D.INK, a), anchor="mm")
            if sub:
                f2 = S._fit(d, str(sub), D.F_MED, 36, bw - 80 - 2 * shift)
                d.text((tx, yo + bh / 2 + 36), str(sub), font=f2,
                       fill=D.fade(D.MUTE, a), anchor="mm")
        if i < n - 1:
            b = D.appear(t, t0 + 0.1 + (i + 0.55) * 0.4, dur=0.35)
            if b <= 0.01:
                continue
            ya, yb = yy + bh + 8, yy + bh + gap - 8
            tip = ya + (yb - ya) * b
            d.rectangle((S.MIDX - 3, ya, S.MIDX + 3, tip), fill=D.fade(D.MUTE, b))
            if b > 0.9:
                d.polygon([(S.MIDX - 20, tip - 22), (S.MIDX + 20, tip - 22), (S.MIDX, tip + 4)],
                          fill=D.MUTE)
            if i < len(labels) and labels[i]:
                D.tracked(d, (S.MIDX + 44, (ya + yb) / 2), str(labels[i]).upper(), D.F_SEMI(30),
                          D.fade(D.MUTE, b), track=5, anchor="lm")
            if b > 0.99 and gap > 40:
                fr = ((t - t0) * 0.9 + i * 0.3) % 1.0
                py = ya + (yb - ya - 24) * fr + 4
                d.ellipse((S.MIDX - 11, py, S.MIDX + 11, py + 22), fill=D.MINT)


def equation(d, t, t0, t1, data):
    """Alt alta islem, ilkokuldaki gibi: 256 x 256 x 256 = 16,777,216.
    data: {terms:[{value, label?}] (en cok 4), op?:"×", ops?:[her satir icin], result:{value, label?, tone?}}"""
    terms = _items(data, "terms", 4)
    res = data.get("result") if isinstance(data.get("result"), dict) else {}
    n = len(terms)
    if not n and not res:
        return
    row_h = min(170.0, 560.0 / max(1, n))
    block = n * row_h + 40 + 220
    y0 = S.MID - block / 2
    right = D.W - S.MARGIN
    ops = data.get("ops") or [data.get("op", "×")] * max(1, n)
    for i, tm in enumerate(terms):
        a = D.appear(t, t0 + 0.1 + i * 0.3)
        if a <= 0.01:
            continue
        yc = y0 + i * row_h + row_h / 2 + (1 - a) * 18
        val = str(tm.get("value", ""))
        f = S._fit(d, val, D.F_HUGE, 104, D.W * 0.6)
        lab = tm.get("label")
        d.text((right, yc + (14 if lab else 0)), val, font=f, fill=D.fade(D.INK, a), anchor="rm")
        if lab:
            D.tracked(d, (right, yc - 40), str(lab).upper(), D.F_SEMI(28), D.fade(D.MUTE, a),
                      track=5, anchor="rb")
        if i > 0:
            o = str(ops[i] if i < len(ops) else ops[-1])
            d.text((S.MARGIN, yc), o, font=D.F_DISP(88), fill=D.fade(D.MUTE, a), anchor="lm")
    ry = y0 + n * row_h + 14
    ta = t0 + 0.1 + n * 0.3
    p = D.appear(t, ta, dur=0.4)
    if p > 0.01:
        d.rectangle((right - (D.W - 2 * S.MARGIN) * p, ry, right, ry + 6), fill=D.fade(D.MUTE, 0.9))
    ra = D.appear(t, ta + 0.45)
    if ra > 0.01 and res:
        col = S._tone(res.get("tone", "good"))
        yc = ry + 120 + (1 - ra) * 18
        val = str(res.get("value", ""))
        f = S._fit(d, val, D.F_HUGE, 150, D.W - 2 * S.MARGIN - 110)
        lab = res.get("label")
        d.text((right, yc + (16 if lab else 0)), val, font=f, fill=D.fade(col, ra), anchor="rm")
        if lab:
            D.tracked(d, (right, yc - 62), str(lab).upper(), D.F_SEMI(28), D.fade(D.MUTE, ra),
                      track=5, anchor="rb")
        d.text((S.MARGIN, yc), "=", font=D.F_DISP(88), fill=D.fade(D.MUTE, ra), anchor="lm")


def ring(d, t, t0, t1, data):
    """Yuzde halkasi: icinde sayi sayarak yukselir.
    data: {value, of?:100, label, sub?, tone?, suffix?, dp?}  suffix verilmezse of=100 icin '%'"""
    val = _num(data.get("value", 0))
    mx = _num(data.get("of", 100), 100.0) or 100.0
    frac = max(0.0, min(1.0, val / mx))
    r, wd = 290, 64
    cx, cy = S.MIDX, S.MID - 70
    a = D.appear(t, t0)
    col = S._tone(data.get("tone", "good"))
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, 0, 360, fill=D.fade(D.mix(D.LINE, D.MUTE, 0.3), a), width=wd)
    prog = D.ease_out(D.clamp01((t - t0 - 0.2) / 1.3))
    sweep = 360 * frac * prog
    if sweep > 0.8:
        d.arc(box, -90, -90 + sweep, fill=col, width=wd)
        rc = r - wd / 2
        for ang in (-90, -90 + sweep):
            px = cx + rc * math.cos(math.radians(ang))
            py = cy + rc * math.sin(math.radians(ang))
            d.ellipse((px - wd / 2, py - wd / 2, px + wd / 2, py + wd / 2), fill=col)
    dp = _int(data.get("dp", 0), 0, 0, 4)
    v = D.countup(t, t0 + 0.2, 1.3, 0.0, val)
    suffix = str(data.get("suffix", "%" if mx == 100 else ""))
    txt = f"{v:,.{dp}f}{suffix}"
    f = S._fit(d, txt, D.F_HUGE, 150, 2 * (r - wd) - 50)
    d.text((cx, cy), txt, font=f, fill=D.fade(D.INK, a), anchor="mm")
    la = D.appear(t, t0 + 0.5)
    if la > 0.01 and data.get("label"):
        f2 = S._fit(d, str(data["label"]), D.F_DISP, 60, D.W - 2 * S.MARGIN)
        d.text((cx, cy + r + 70), str(data["label"]), font=f2, fill=D.fade(D.INK, la), anchor="mt")
        if data.get("sub"):
            f3 = S._fit(d, str(data["sub"]), D.F_MED, 40, D.W - 2 * S.MARGIN)
            d.text((cx, cy + r + 150), str(data["sub"]), font=f3, fill=D.fade(D.MUTE, la), anchor="mt")


def dots(d, t, t0, t1, data):
    """Yuz nokta, altisi yanar: 'yuzde alti' yerine GORULEN oran.
    data: {total?:100, hit, cols?:10, label?, sub?, tone?, scatter?:true}"""
    total = _int(data.get("total", 100), 100, 1, 200)
    hit = _int(data.get("hit", 0), 0, 0, total)
    cols = _int(data.get("cols", 10), 10, 2, 20)
    rows = math.ceil(total / cols)
    pitch = min(88.0, (D.W - 2 * S.MARGIN) / cols, 740.0 / rows)
    r = pitch * 0.33
    gw, gh = pitch * cols, pitch * rows
    gx, gy = S.MIDX - gw / 2, S.MID - gh / 2 - 90
    col = S._tone(data.get("tone", "good"))
    rng = random.Random(total * 131 + hit)
    chosen = rng.sample(range(total), hit) if data.get("scatter", True) else list(range(hit))
    order = {idx: k for k, idx in enumerate(chosen)}
    base = _dim()
    for i in range(total):
        a = D.appear(t, t0 + i / total * 0.5, dur=0.25)
        if a <= 0.01:
            continue
        cx = gx + (i % cols + 0.5) * pitch
        cy = gy + (i // cols + 0.5) * pitch
        c, rr = D.fade(base, a), r * a
        if i in order:
            lit = D.appear(t, t0 + 0.8 + order[i] * (1.0 / max(1, hit)), dur=0.25)
            c = D.mix(c, col, lit)
            rr = r * (a + 0.28 * lit)
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=c)
    la = D.appear(t, t0 + 0.9)
    if la > 0.01:
        lab = str(data.get("label") or f"{hit} of {total}")
        f = S._fit(d, lab, D.F_HUGE, 120, D.W - 2 * S.MARGIN)
        d.text((S.MIDX, gy + gh + 60), lab, font=f, fill=D.fade(col, la), anchor="mt")
        if data.get("sub"):
            f2 = S._fit(d, str(data["sub"]), D.F_MED, 42, D.W - 2 * S.MARGIN)
            d.text((S.MIDX, gy + gh + 60 + 140), str(data["sub"]), font=f2,
                   fill=D.fade(D.MUTE, la), anchor="mt")


def chat(d, t, t0, t1, data):
    """Sohbet balonlari: kullanici sagda, bot solda; bot yazmadan once uc nokta.
    data: {messages:[{who:'user'|'bot', text, name?, tone?}] (en cok 4)}  tone:'bad' balona amber cerceve"""
    msgs = _items(data, "messages", 4)
    if not msgs:
        return
    pad, maxw, size = 32, 740, 46
    lay = []
    for m in msgs:
        f, lines = _wrap_fit(d, m.get("text", ""), D.F_MED, size, maxw - 2 * pad, 4, 34)
        w = max(d.textlength(ln, font=f) for ln in lines) + 2 * pad
        h = len(lines) * f.size * 1.25 + 2 * pad
        lay.append((f, lines, w, h))
    gap, lab_h = 34, 40
    total = sum(h + lab_h for _, _, _, h in lay) + gap * (len(lay) - 1)
    y = S.MID - total / 2
    for i, (m, (f, lines, w, h)) in enumerate(zip(msgs, lay)):
        user = str(m.get("who", "bot")).lower() == "user"
        start = t0 + 0.15 + i * 0.85
        typing = (not user) and start <= t < start + 0.4
        a = D.appear(t, start + (0 if user else 0.4), dur=0.3)
        ytop = y + lab_h
        if a > 0.01 or typing:
            xr = D.W - S.MARGIN if user else S.MARGIN
            name = str(m.get("name") or ("YOU" if user else "BOT")).upper()
            D.tracked(d, (xr, y + 6), name, D.F_SEMI(26), D.fade(D.MUTE, max(a, 0.6 if typing else 0)),
                      track=5, anchor=("rt" if user else "lt"))
        if typing:
            bw, bh = 170, 84
            x0 = S.MARGIN
            d.rounded_rectangle((x0, ytop, x0 + bw, ytop + bh), radius=42, fill=_panel())
            for k in range(3):
                pulse = 0.5 + 0.5 * math.sin((t - start) * 11 - k * 0.9)
                cxx = x0 + 46 + k * 39
                d.ellipse((cxx - 9, ytop + bh / 2 - 9, cxx + 9, ytop + bh / 2 + 9),
                          fill=D.mix(_dim(), D.INK, pulse))
        elif a > 0.01:
            x0 = (D.W - S.MARGIN - w) if user else S.MARGIN
            yo = ytop - (1 - a) * 16
            fill = D.fade(D.VIOLET, 0.34 * a) if user else D.fade(_panel(), a)
            ol = D.fade(D.AMBER, a) if m.get("tone") == "bad" else None
            d.rounded_rectangle((x0, yo, x0 + w, yo + h), radius=34, fill=fill,
                                outline=ol, width=4 if ol else 0)
            for k, ln in enumerate(lines):
                d.text((x0 + pad, yo + pad + k * f.size * 1.25), ln, font=f,
                       fill=D.fade(D.INK, a), anchor="lt")
        y = ytop + h + gap


def terminal(d, t, t0, t1, data):
    """Komut satiri penceresi: komutlar harf harf yazilir, ciktilar sonra gelir.
    data: {title?, lines:[str | {text, kind?:'cmd'|'out'|'err'|'hl', tone?}] (en cok 7)}
    str satiri: '$ ' ile baslarsa komut, yoksa cikti."""
    raw = data.get("lines") if isinstance(data.get("lines"), list) else []
    lines = []
    for ln in raw[:7]:
        if isinstance(ln, str):
            lines.append({"text": ln[2:] if ln.startswith("$ ") else ln,
                          "kind": "cmd" if ln.startswith("$ ") else "out"})
        elif isinstance(ln, dict):
            lines.append({"text": str(ln.get("text", "")), "kind": ln.get("kind", "out"),
                          "tone": ln.get("tone", "good")})
    if not lines:
        return
    longest = max(len(x["text"]) + (2 if x["kind"] == "cmd" else 0) for x in lines)
    pitch = min(30.0, (D.W - 2 * S.MARGIN - 80) / max(1, longest))
    size = int(pitch / 0.6)
    lh = 100
    head = 104
    H = head + len(lines) * lh + 56
    x0, x1 = S.MARGIN, D.W - S.MARGIN
    y0 = S.MID - H / 2
    a = D.appear(t, t0)
    d.rounded_rectangle((x0, y0, x1, y0 + H), radius=28, fill=D.fade(_panel(), a),
                        outline=D.fade(_dim(), a), width=3)
    for k, c in enumerate((D.AMBER, D.MUTE, D.MINT)):
        cx = x0 + 44 + k * 36
        d.ellipse((cx - 10, y0 + head / 2 - 10, cx + 10, y0 + head / 2 + 10), fill=D.fade(c, 0.8 * a))
    if data.get("title"):
        D.tracked(d, (D.W / 2, y0 + head / 2), str(data["title"]).upper(), D.F_SEMI(26),
                  D.fade(D.MUTE, a), track=5, anchor="mm")
    d.rectangle((x0 + 3, y0 + head, x1 - 3, y0 + head + 2), fill=D.fade(_dim(), a))
    cps = 34.0
    cur = t0 + 0.3
    last_end = (x0 + 40, y0 + head + lh / 2)
    for i, ln in enumerate(lines):
        yc = y0 + head + i * lh + lh / 2 + 6
        text, kind = ln["text"], ln["kind"]
        if kind == "cmd":
            start, dur = cur, len(text) / cps
            cur = start + dur + 0.3
            shown = max(0, min(len(text), int((t - start) * cps)))
            if t < start:
                continue
            _mono(d, x0 + 40, yc, "$", size, D.MINT, pitch)
            _mono(d, x0 + 40 + 2 * pitch, yc, text[:shown], size, D.INK, pitch)
            last_end = (x0 + 40 + (2 + shown) * pitch, yc)
        else:
            start = cur
            cur = start + 0.2
            if t < start:
                continue
            if kind == "hl":
                col = S._tone(ln.get("tone", "good"))
                d.rounded_rectangle((x0 + 20, yc - lh / 2 + 8, x1 - 20, yc + lh / 2 - 8), radius=14,
                                    fill=D.fade(col, 0.16))
            col = {"err": D.AMBER, "hl": S._tone(ln.get("tone", "good"))}.get(kind, D.MUTE)
            _mono(d, x0 + 40, yc, text, size, col, pitch)
            last_end = (x0 + 40 + len(text) * pitch, yc)
    if D.blink_on(t, 1.0, 0.45) and t > t0 + 0.3:
        cx, cy = last_end
        d.rectangle((cx + 4, cy - size * 0.55, cx + 4 + pitch * 0.6, cy + size * 0.55), fill=D.fade(D.INK, 0.85))


def tokens(d, t, t0, t1, data):
    """Metin parcalara bolunuyor: renkli cipler ve alta sayac.
    data: {tokens:[str] (en cok 24), note?, tone?}  note verilmezse 'N tokens'"""
    toks = [str(x).strip() or "_" for x in (data.get("tokens") if isinstance(data.get("tokens"), list) else [])][:24]
    if not toks:
        return
    f = D.F_DISP(64)
    pad, gap, ch = 26, 14, 112
    maxw = D.W - 2 * S.MARGIN
    rows, cur, x = [], [], 0.0
    for tk in toks:
        w = d.textlength(tk, font=f) + 2 * pad
        if cur and x + w > maxw:
            rows.append(cur)
            cur, x = [], 0.0
        cur.append((tk, w))
        x += w + gap
    rows.append(cur)
    block = len(rows) * (ch + gap)
    total = block + 230
    y0 = S.MID - total / 2
    pal = [D.MINT, D.VIOLET, D.AMBER, D.INK]
    k = 0
    for r_i, row in enumerate(rows):
        rw = sum(w for _, w in row) + gap * (len(row) - 1)
        x = S.MIDX - rw / 2
        for tk, w in row:
            a = D.appear(t, t0 + 0.1 + k * 0.11, dur=0.3)
            if a > 0.01:
                col = pal[k % len(pal)]
                yy = y0 + r_i * (ch + gap) + (1 - a) * 14
                d.rounded_rectangle((x, yy, x + w, yy + ch), radius=22,
                                    fill=D.fade(col, 0.17 * a), outline=D.fade(col, 0.9 * a), width=3)
                d.text((x + w / 2, yy + ch / 2 - 2), tk, font=f, fill=D.fade(col, a), anchor="mm")
            x += w + gap
            k += 1
    seen = sum(1 for j in range(len(toks)) if D.appear(t, t0 + 0.1 + j * 0.11, dur=0.3) > 0.5)
    la = D.appear(t, t0 + 0.1 + len(toks) * 0.11 + 0.1)
    if la > 0.01:
        txt = str(data.get("note") or f"{len(toks)} tokens")
        ff = S._fit(d, txt, D.F_HUGE, 120, D.W - 2 * S.MARGIN)
        d.text((S.MIDX, y0 + block + 50 + (1 - la) * 14), txt, font=ff,
               fill=D.fade(S._tone(data.get("tone", "base")), la), anchor="mt")
    elif seen:
        d.text((S.MIDX, y0 + block + 50), str(seen), font=D.F_HUGE(120), fill=D.fade(D.MUTE, 0.7), anchor="mt")


def probs(d, t, t0, t1, data):
    """Siradaki kelimenin olasiliklari: bosluga en olasi kelime oturur.
    data: {prompt?, rows:[{word, p, tone?}] (en cok 5), pick?:0}  p: 0..1 ya da 0..100"""
    rows = _items(data, "rows", 5)
    n = len(rows)
    if not n:
        return
    ps = [max(0.0, _num(r.get("p", 0))) for r in rows]
    scale = 100.0 if max(ps) <= 1.0 else 1.0
    pmax = max(max(ps), 1e-9)
    pick = _int(data.get("pick", 0), 0, 0, 10 ** 6) % n
    y = S.TOP + 70
    prompt = str(data.get("prompt") or "")
    fp = S._fit(d, prompt + " ______", D.F_DISP, 64, D.W - 2 * S.MARGIN)
    slot_w = d.textlength("______", font=fp)
    pw = d.textlength(prompt + " ", font=fp)
    x = S.MIDX - (pw + slot_w) / 2
    pa = D.appear(t, t0)
    if prompt:
        d.text((x, y + 20), prompt, font=fp, fill=D.fade(D.INK, pa), anchor="lm")
    sx = x + pw
    d.rectangle((sx, y + 56, sx + slot_w, y + 61), fill=D.fade(D.MUTE, pa))
    fill_t = t0 + 0.5 + n * 0.15 + 1.0
    fa = D.appear(t, fill_t)
    word = str(rows[pick].get("word", ""))
    if fa > 0.01:
        fw = S._fit(d, word, D.F_DISP, 64, slot_w + 40)
        d.text((sx + slot_w / 2, y + 20 - (1 - fa) * 16), word, font=fw,
               fill=D.fade(D.MINT, fa), anchor="mm")
    top = S.TOP + 230
    h = min(150.0, (S.BOT - top - 40) / n)
    lx, bx = S.MARGIN, S.MARGIN + 300
    bmax = D.W - S.MARGIN - bx - 150
    for i, r in enumerate(rows):
        a = D.appear(t, t0 + 0.5 + i * 0.15, dur=0.5)
        if a <= 0.01:
            continue
        yc = top + i * h + h / 2
        col = S._tone(r.get("tone", "good" if i == pick else "base"))
        txtc = D.INK if i == pick else D.MUTE
        fw = S._fit(d, str(r.get("word", "")), D.F_DISP, 52, 270)
        d.text((lx, yc), str(r.get("word", "")), font=fw, fill=D.fade(txtc, a), anchor="lm")
        bl = max(10.0, bmax * ps[i] / pmax) * a
        d.rounded_rectangle((bx, yc - 26, bx + bl, yc + 26), radius=14,
                            fill=D.fade(col, 0.9 if i == pick else 0.5))
        pct = ps[i] * scale
        d.text((bx + bl + 18, yc), f"{pct:.0f}%", font=D.F_DISP(46), fill=D.fade(txtc, a), anchor="lm")


def layers(d, t, t0, t1, data):
    """Katmanlar alttan uste dizilir (her biri yukaridan duser).
    data: {layers:[{label, sub?, tone?}] (en cok 5, ALTTAN USTE), total?}"""
    items = _items(data, "layers", 5)
    n = len(items)
    if not n:
        return
    gap = 14
    h = min(150.0, (S.BOT - S.TOP - 160) / n - gap)
    stack = n * h + (n - 1) * gap
    ybot = S.MID + stack / 2 + (30 if data.get("total") else 0)
    w = 800
    x0 = S.MIDX - w / 2
    for i, it in enumerate(items):
        a = D.appear(t, t0 + 0.1 + i * 0.35, dur=0.4)
        if a <= 0.01:
            continue
        col = S._tone(it.get("tone", "base" if i < n - 1 else "good"))
        yb = ybot - i * (h + gap)
        yt = yb - h - (1 - a) * 60
        d.rounded_rectangle((x0, yt, x0 + w, yt + h), radius=22,
                            fill=D.fade(col, 0.14 * a), outline=D.fade(col, a), width=3)
        d.rectangle((x0 + 22, yt + 3, x0 + w - 22, yt + 6), fill=D.fade(col, 0.55 * a))
        sub = it.get("sub")
        lw = (w - 72) * (0.62 if sub else 1.0)
        f = S._fit(d, str(it.get("label", "")), D.F_DISP, 56, lw)
        d.text((x0 + 36, yt + h / 2), str(it.get("label", "")), font=f, fill=D.fade(D.INK, a), anchor="lm")
        if sub:
            f2 = S._fit(d, str(sub), D.F_MED, 36, (w - 72) * 0.38)
            d.text((x0 + w - 36, yt + h / 2), str(sub), font=f2, fill=D.fade(D.MUTE, a), anchor="rm")
    ta = D.appear(t, t0 + 0.1 + n * 0.35 + 0.2)
    if ta > 0.01 and data.get("total"):
        f = S._fit(d, str(data["total"]), D.F_HUGE, 84, D.W - 2 * S.MARGIN)
        d.text((S.MIDX, ybot - stack - 60 - (1 - ta) * 12), str(data["total"]), font=f,
               fill=D.fade(D.MINT, ta), anchor="mb")


def checklist(d, t, t0, t1, data):
    """Dogru / yanlis satirlari; isaretler cizilerek gelir.
    data: {rows:[{text, ok?:true, tone?}] (en cok 5)}"""
    rows = _items(data, "rows", 5)
    n = len(rows)
    if not n:
        return
    h = min(190.0, (S.BOT - S.TOP - 80) / n)
    y0 = S.MID - n * h / 2
    cx = S.MARGIN + 52
    tx = cx + 90
    for i, r in enumerate(rows):
        start = t0 + 0.1 + i * 0.4
        a = D.appear(t, start)
        if a <= 0.01:
            continue
        ok = bool(r.get("ok", True))
        col = S._tone(r.get("tone", "good" if ok else "bad"))
        yc = y0 + i * h + h / 2
        d.rectangle((S.MARGIN, y0 + (i + 1) * h - 2, D.W - S.MARGIN, y0 + (i + 1) * h),
                    fill=D.fade(D.LINE, a)) if i < n - 1 else None
        rr = 44
        d.ellipse((cx - rr, yc - rr, cx + rr, yc + rr), fill=D.fade(col, 0.16 * a),
                  outline=D.fade(col, a), width=4)
        p = D.clamp01((t - (start + 0.15)) / 0.3)
        if ok:
            pts = [(cx - 19, yc + 2), (cx - 5, yc + 16), (cx + 21, yc - 15)]
            seg1 = D.clamp01(p / 0.4)
            seg2 = D.clamp01((p - 0.4) / 0.6)
            if seg1 > 0:
                e = (pts[0][0] + (pts[1][0] - pts[0][0]) * seg1, pts[0][1] + (pts[1][1] - pts[0][1]) * seg1)
                d.line([pts[0], e], fill=col, width=9, joint="curve")
            if seg2 > 0:
                e = (pts[1][0] + (pts[2][0] - pts[1][0]) * seg2, pts[1][1] + (pts[2][1] - pts[1][1]) * seg2)
                d.line([pts[1], e], fill=col, width=9, joint="curve")
        else:
            s1 = D.clamp01(p / 0.5)
            s2 = D.clamp01((p - 0.5) / 0.5)
            if s1 > 0:
                d.line([(cx - 17, yc - 17), (cx - 17 + 34 * s1, yc - 17 + 34 * s1)], fill=col, width=9)
            if s2 > 0:
                d.line([(cx + 17, yc - 17), (cx + 17 - 34 * s2, yc - 17 + 34 * s2)], fill=col, width=9)
        f, lines = _wrap_fit(d, r.get("text", ""), D.F_DISP, 54, D.W - S.MARGIN - tx, 2, 36)
        top = yc - len(lines) * f.size * 1.15 / 2
        for k, ln in enumerate(lines):
            d.text((tx - (1 - a) * 20, top + k * f.size * 1.15), ln, font=f,
                   fill=D.fade(D.INK, a), anchor="lt")


def headline(d, t, t0, t1, data):
    """Haber karti: kaynak adi, tarih ve buyuk baslik. Hikaye anlatirken 'bir yerde yazdi' demenin gorseli.
    data: {source, date?, headline, kicker?, tone?}  (kaynak adi yazi olarak durur, logo/taklit yok)"""
    text = str(data.get("headline") or "")
    if not text:
        return
    x0, x1 = S.MARGIN, D.W - S.MARGIN
    inner = x1 - x0 - 110
    f, lines = _wrap_fit(d, text, D.F_DISP, 76, inner, 5, 44)
    lh = f.size * 1.16
    kicker = data.get("kicker")
    H = 120 + (50 if kicker else 0) + len(lines) * lh + 90
    y0 = S.MID - H / 2
    a = D.appear(t, t0)
    d.rounded_rectangle((x0, y0, x1, y0 + H), radius=24, fill=D.fade(_panel(), a),
                        outline=D.fade(_dim(), a), width=3)
    D.tracked(d, (x0 + 50, y0 + 58), str(data.get("source", "")).upper(), D.F_SEMI(30),
              D.fade(D.INK, a), track=6, anchor="lm")
    if data.get("date"):
        D.tracked(d, (x1 - 50, y0 + 58), str(data["date"]).upper(), D.F_SEMI(28),
                  D.fade(D.MUTE, a), track=5, anchor="rm")
    for k in (0, 7):
        d.rectangle((x0 + 50, y0 + 100 + k, x1 - 50, y0 + 102 + k), fill=D.fade(_dim(), a))
    col = S._tone(data.get("tone", "mid"))
    y = y0 + 140
    if kicker:
        ka = D.appear(t, t0 + 0.2)
        D.tracked(d, (x0 + 76, y + 8), str(kicker).upper(), D.F_SEMI(28), D.fade(col, ka),
                  track=6, anchor="lm")
        y += 50
    bar_h = len(lines) * lh
    bp = D.appear(t, t0 + 0.25, dur=0.5)
    d.rectangle((x0 + 50, y + 4, x0 + 56, y + 4 + bar_h * bp), fill=col)
    for i, ln in enumerate(lines):
        la = D.appear(t, t0 + 0.3 + i * 0.16)
        if la > 0.01:
            d.text((x0 + 76, y + i * lh + (1 - la) * 16), ln, font=f, fill=D.fade(D.INK, la), anchor="lt")


def scale(d, t, t0, t1, data):
    """Logaritmik cetvel: cok farkli buyuklukler 10'un kuvvetleriyle ayni cizgide.
    data: {items:[{label, value | exp, text?, tone?}] (2-4)}  value > 0 ise exp=log10(value); text: ekranda yazan sayi"""
    raw = _items(data, "items", 4)
    items = []
    for it in raw:
        try:
            e = float(it["exp"]) if "exp" in it else math.log10(float(it["value"]))
        except (KeyError, TypeError, ValueError):
            continue
        items.append((e, it))
    if len(items) < 1:
        return
    items.sort(key=lambda x: x[0])
    lo = math.floor(min(e for e, _ in items)) - 1
    hi = math.ceil(max(e for e, _ in items)) + 1
    if hi - lo < 3:
        hi = lo + 3
    x0, x1 = S.MARGIN + 30, D.W - S.MARGIN - 30
    ay = S.MID + 150

    def X(e):
        return x0 + (e - lo) / (hi - lo) * (x1 - x0)

    pa = D.clamp01((t - t0) / 0.8)
    d.rectangle((x0, ay - 3, x0 + (x1 - x0) * D.ease_out(pa), ay + 3), fill=_dim())
    # etiketler birbirine binmesin: en az ~100 px arayla
    need = 100.0 * (hi - lo) / (x1 - x0)
    step = next((s_ for s_ in (1, 2, 5, 10, 20, 50, 100) if s_ >= need), 100)
    k = int(math.ceil(lo / step) * step)
    while k <= hi:
        if X(k) <= x0 + (x1 - x0) * D.ease_out(pa) + 1:
            d.rectangle((X(k) - 2, ay - 12, X(k) + 2, ay + 12), fill=_dim())
            _pow10(d, X(k), ay + 70, k, D.fade(D.MUTE, 0.9), 32)
        k += step
    for i, (e, it) in enumerate(items):
        a = D.appear(t, t0 + 0.6 + i * 0.5)
        if a <= 0.01:
            continue
        col = S._tone(it.get("tone", "good" if i == len(items) - 1 else "base"))
        px = X(e)
        level = i % 2
        top = ay - 190 - level * 230
        drop = (1 - a) * 40
        d.rectangle((px - 2, top + 142 - drop, px + 2, ay - 14), fill=D.fade(col, 0.7 * a))
        d.ellipse((px - 18, ay - 18, px + 18, ay + 18), fill=D.fade(col, a))
        val = str(it.get("text") or f"10^{e:.0f}")
        m = re.fullmatch(r"10\^(-?\d+)", val.strip())
        lab = str(it.get("label", ""))
        fl = S._fit(d, lab, D.F_MED, 38, 460)
        if m:
            vw = d.textlength("10", font=D.F_HUGE(78)) + d.textlength(m.group(1), font=D.F_HUGE(52)) + 4
        else:
            fw = S._fit(d, val, D.F_HUGE, 78, 460)
            vw = d.textlength(val, font=fw)
        wv = max(vw, d.textlength(lab, font=fl))
        cx = min(max(px, S.MARGIN + wv / 2), D.W - S.MARGIN - wv / 2)
        if m:
            _pow10(d, cx, top + 78 - drop, int(m.group(1)), D.fade(col, a), 78)
        else:
            d.text((cx, top - drop), val, font=fw, fill=D.fade(col, a), anchor="mt")
        d.text((cx, top + 98 - drop), lab, font=fl, fill=D.fade(D.MUTE, a), anchor="mt")


def cycle(d, t, t0, t1, data):
    """Dongu: A -> B -> C -> A. Sira sira bir dugum yanar.
    data: {nodes:[{label, tone?}] (3-4), center?}"""
    nodes = _items(data, "nodes", 4)
    n = len(nodes)
    if n < 3:
        return
    R = 300 if n == 3 else 280
    cx, cy = S.MIDX, S.MID
    ang = [-90 + i * 360.0 / n for i in range(n)]
    pos = [(cx + R * math.cos(math.radians(a_)), cy + R * math.sin(math.radians(a_))) for a_ in ang]
    maxw = 330
    fonts = [S._fit(d, str(nd.get("label", "")), D.F_DISP, 46, maxw) for nd in nodes]
    ws = [d.textlength(str(nd.get("label", "")), font=f) + 64 for nd, f in zip(nodes, fonts)]
    reveal_end = t0 + 0.1 + n * 0.35 + 0.3
    active = int((t - reveal_end) / 0.9) % n if t >= reveal_end else -1
    delta = 25.0 if n == 3 else 28.0
    for i in range(n):
        b = D.appear(t, t0 + 0.1 + (i + 0.6) * 0.35, dur=0.4)
        if b <= 0.01:
            continue
        a0 = ang[i] + delta
        a1 = ang[i] + 360.0 / n - delta
        end = a0 + (a1 - a0) * b
        pts = [(cx + R * math.cos(math.radians(a_)), cy + R * math.sin(math.radians(a_)))
               for a_ in [a0 + (end - a0) * k / 24 for k in range(25)]]
        d.line(pts, fill=D.fade(D.MUTE, 0.85 * b), width=7, joint="curve")
        if b > 0.92:
            th = math.radians(end)
            tx, ty = -math.sin(th), math.cos(th)
            nx, ny = math.cos(th), math.sin(th)
            px, py = cx + R * math.cos(th), cy + R * math.sin(th)
            bx, by = px - tx * 34, py - ty * 34
            d.polygon([(px + tx * 6, py + ty * 6), (bx + nx * 20, by + ny * 20), (bx - nx * 20, by - ny * 20)],
                      fill=D.MUTE)
    for i, nd in enumerate(nodes):
        a = D.appear(t, t0 + 0.1 + i * 0.35)
        if a <= 0.01:
            continue
        col = S._tone(nd.get("tone", "base"))
        on = i == active
        px, py = pos[i]
        w, h = ws[i], 100
        d.rounded_rectangle((px - w / 2, py - h / 2, px + w / 2, py + h / 2), radius=50,
                            fill=D.fade(col, (0.34 if on else 0.14) * a),
                            outline=D.fade(col, a), width=6 if on else 3)
        d.text((px, py - 2), str(nd.get("label", "")), font=fonts[i],
               fill=D.fade(D.INK, a), anchor="mm")
    if data.get("center"):
        ca = D.appear(t, t0 + 0.1)
        f, lines = _wrap_fit(d, data["center"], D.F_HUGE, 64, 300, 2, 36)
        top = cy - len(lines) * f.size * 1.1 / 2
        for k, ln in enumerate(lines):
            d.text((cx, top + k * f.size * 1.1), ln, font=f, fill=D.fade(D.MUTE, ca), anchor="mt")


def bits(d, t, t0, t1, data):
    """Bitler ve bir tasma: yanip eski degerden yeni degere doner.
    data: {bits:'0111...' (en cok 32; bosluk yok sayilir), flip_to?:'1000...', label?, flip_label?, tone?}
    flip_to varsa 1,8 sn'de farkli bitler amber yanip yeni degeri alir."""
    b = [c for c in str(data.get("bits", "")) if c in "01"][:32]
    if not b:
        return
    to = [c for c in str(data.get("flip_to", "")) if c in "01"][:len(b)]
    to = to + b[len(to):] if to else None
    per = 8 if len(b) >= 8 else len(b)
    nrows = math.ceil(len(b) / per)
    cell, g = 84, 12
    rw = per * cell + (per - 1) * g
    rh = cell + 16
    block = nrows * rh
    y0 = S.MID - block / 2 + 50
    x_start = S.MIDX - rw / 2
    tf = t0 + 1.8
    col_on = S._tone(data.get("tone", "good"))
    flipped = to is not None and t >= tf
    # etiket
    lab = data.get("flip_label") if flipped and data.get("flip_label") else data.get("label")
    if lab:
        la = D.appear(t, tf + 0.1) if flipped else D.appear(t, t0 + 0.2)
        c = S._tone("bad") if flipped else D.INK
        f = S._fit(d, str(lab), D.F_DISP, 64, D.W - 2 * S.MARGIN)
        d.text((S.MIDX, y0 - 90), str(lab), font=f, fill=D.fade(c, max(la, 0.001)), anchor="mm")
    for i, bit in enumerate(b):
        a = D.appear(t, t0 + 0.1 + i * 0.02, dur=0.3)
        if a <= 0.01:
            continue
        r_i, c_i = divmod(i, per)
        x = x_start + c_i * (cell + g)
        y = y0 + r_i * rh
        cur, col = bit, col_on
        if to is not None and to[i] != bit and t >= tf:
            cur = to[i]
            # degisen bit once amber parlar, sonra normal rengine doner
            col = D.mix(col_on, S._tone("bad"), D.clamp01(1 - (t - tf) / 0.6)) if t - tf < 0.6 else S._tone("bad")
        if cur == "1":
            d.rounded_rectangle((x, y, x + cell, y + cell), radius=14, fill=D.fade(col, a))
            d.text((x + cell / 2, y + cell / 2 - 2), "1", font=D.F_DISP(58), fill=D.BG0, anchor="mm")
        else:
            d.rounded_rectangle((x, y, x + cell, y + cell), radius=14, outline=D.fade(_dim(), a), width=4)
            d.text((x + cell / 2, y + cell / 2 - 2), "0", font=D.F_DISP(58), fill=D.fade(D.MUTE, a), anchor="mm")


def guess_reveal(t0, t1):
    """Cevabin acildigi an: sahnenin ~%62'si, en gec bitisten 0.35 sn once, en erken baslangictan 0.9 sn sonra.
    (cartoon.Toon.sfx_events de ding'i buradan zamanlar.)"""
    rv = min(t0 + max(1.6, (t1 - t0) * 0.62), t1 - 0.35)
    return max(rv, t0 + 0.9)


def guess(d, t, t0, t1, data):
    """"Sen tahmin et": soru + 2-4 sik; sure dolunca dogru sik yesile doner, digerleri soner.
    data: {q, options:[metin | {text}] (2-4), answer: dogru sikkin SIRASI (0'dan), note?}
    Zamanlama: sikler sirayla gelir; sahnenin ~%62'sinde cevap acilir (en gec bitisten 0.35 sn once).
    Cevap acilmadan once soru kartinin altinda azalan bir sure cubugu var: izleyici dusunur, sonra bilir."""
    q = str(data.get("q", "")).strip()
    raw = data.get("options") if isinstance(data.get("options"), list) else []
    opts = []
    for o in raw[:4]:
        txt = o.get("text") if isinstance(o, dict) else o
        if isinstance(txt, (str, int, float)) and not isinstance(txt, bool) and str(txt).strip():
            opts.append(str(txt).strip())
    n = len(opts)
    if not q and not n:
        return
    av = data.get("answer")
    ans = -1 if isinstance(av, bool) else _int(av, -1, -1, 99)   # True int sayilir: dogru sik sanilmasin
    if ans >= n:
        ans = -1                                           # gecersiz sira: cevap acilmaz, hicbir sik "dogru" olmaz
    rv = guess_reveal(t0, t1)
    revealed = ans >= 0 and t >= rv
    a_q = D.appear(t, t0)
    gap = 26.0
    f, lines = _wrap_fit(d, q, D.F_DISP, 64, D.W - 2 * S.MARGIN, 3, 40) if q else (None, [])
    q_h = (len(lines) * f.size * 1.16 + 26) if q else 0.0
    h = max(96.0, min(150.0, (S.BOT - S.TOP - q_h - 44 - 150 - (max(n, 1) - 1) * gap) / max(n, 1)))
    note_s = data.get("note") if isinstance(data.get("note"), str) and data.get("note").strip() else ""
    block = q_h + 44 + (n * h + max(0, n - 1) * gap) + (110 if note_s else 0)
    y = max(S.TOP + 10, S.MID - block / 2)                  # blok dikeyde sahne bandinin ortasinda (diger sahneler gibi)
    if q:
        for k, ln in enumerate(lines):
            d.text((S.MIDX, y + k * f.size * 1.16 - (1 - a_q) * 18), ln, font=f,
                   fill=D.fade(D.INK, a_q), anchor="mt")
        y += q_h
    if ans >= 0 and not revealed and a_q > 0.5:            # sure cubugu
        frac = D.clamp01(1 - (t - (t0 + 0.6)) / max(0.4, rv - t0 - 0.6))
        bw = D.W - 2 * S.MARGIN
        d.rounded_rectangle((S.MARGIN, y, S.MARGIN + bw, y + 12), radius=6, fill=D.fade(_dim(), a_q))
        if frac > 0.01:
            d.rounded_rectangle((S.MARGIN, y, S.MARGIN + bw * frac, y + 12), radius=6, fill=D.fade(D.VIOLET, a_q))
    y += 44
    if not n:
        return
    letters = "ABCD"
    for i, txt in enumerate(opts):
        a = D.appear(t, t0 + 0.35 + i * 0.3)
        if a <= 0.01:
            continue
        top = y + i * (h + gap) + (1 - a) * 24
        right = revealed and i == ans
        wrong = revealed and i != ans
        k = 0.34 if wrong else 1.0
        col = D.MINT if right else (D.MUTE if wrong else D.VIOLET)
        pop = 1.0
        if right:
            pop = 1.0 + 0.035 * math.sin(D.clamp01((t - rv) / 0.5) * math.pi)
        grow = (h * (pop - 1)) / 2
        d.rounded_rectangle((S.MARGIN - grow, top - grow, D.W - S.MARGIN + grow, top + h + grow), radius=26,
                            fill=D.fade(col, (0.22 if right else 0.10) * a * k), outline=D.fade(col, a * k), width=5 if right else 4)
        cx, cy = S.MARGIN + 66, top + h / 2
        d.ellipse((cx - 34, cy - 34, cx + 34, cy + 34), fill=D.fade(col, a * k * (1.0 if right else 0.22)))
        d.text((cx, cy + 1), letters[i], font=D.F_DISP(40), anchor="mm",
               fill=D.fade(D.BG0 if right else col, a * k))
        tx = cx + 64
        f2, ls = _wrap_fit(d, txt, D.F_DISP, 52, D.W - S.MARGIN - 70 - tx, 2, 32)
        t_top = cy - len(ls) * f2.size * 1.12 / 2
        for j, ln in enumerate(ls):
            d.text((tx, t_top + j * f2.size * 1.12), ln, font=f2, fill=D.fade(D.INK, a * (0.5 if wrong else 1.0)), anchor="lt")
        if right:                                           # cizilerek gelen tik
            p = D.clamp01((t - rv - 0.1) / 0.35)
            ex = D.W - S.MARGIN - 62
            pts = [(ex - 22, cy + 2), (ex - 6, cy + 18), (ex + 24, cy - 16)]
            s1, s2 = D.clamp01(p / 0.45), D.clamp01((p - 0.45) / 0.55)
            if s1 > 0:
                e = (pts[0][0] + (pts[1][0] - pts[0][0]) * s1, pts[0][1] + (pts[1][1] - pts[0][1]) * s1)
                d.line([pts[0], e], fill=D.MINT, width=11, joint="curve")
            if s2 > 0:
                e = (pts[1][0] + (pts[2][0] - pts[1][0]) * s2, pts[1][1] + (pts[2][1] - pts[1][1]) * s2)
                d.line([pts[1], e], fill=D.MINT, width=11, joint="curve")
    if revealed and note_s:
        b = D.appear(t, rv + 0.35)
        f3, ls = _wrap_fit(d, note_s, D.F_MED, 42, D.W - 2 * S.MARGIN, 2, 30)
        ny = y + n * (h + gap) + 8
        for j, ln in enumerate(ls):
            d.text((S.MIDX, ny + j * f3.size * 1.2 - (1 - b) * 14), ln, font=f3, fill=D.fade(D.MUTE, b), anchor="mt")


NAMES_MORE = ("steps", "flow", "equation", "ring", "dots", "chat", "terminal", "tokens",
              "probs", "layers", "checklist", "headline", "scale", "cycle", "bits", "guess")

CATALOG = {n: globals()[n] for n in NAMES_MORE}
