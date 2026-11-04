"""
Seri B -- "Did You Know". Olculmus tek bir gercek, tavsiye yok.
Gorsel imzasi: yan yana karsilastirma + BAYT KUTUSU ders sahnesi.
A'dan kasitli olarak ayri; ayni kanalda donen seriler birbirine benzerse
"birbirinin yerine gecebilir video" tarifine dusuyoruz.
"""
from PIL import ImageDraw, ImageFont

from .draw import (W, H, INK, MUTE, MINT, AMBER, VIOLET, LINE, TONE,
                   F_HUGE, F_DISP, F_SEMI, F_MED, F_REG,
                   clamp01, ease_out, appear, punch, countup, mix, fade,
                   tracked, pill, bob, blink_on, cjk_font)
from .byte import draw_byte, MINT as B_MINT, AMBER as B_AMBER

def glyph_font(ch, size):
    return cjk_font(size) if ord(ch) > 0x2000 else F_HUGE(size)


# ───────────────────────── sahneler ─────────────────────────
def scene_hook(d, t, S, spec):
    t0 = S["b1"][0]
    # kaynak cumle: "bu cumle" derken neyi kastettigimiz gorunsun
    for i, ln in enumerate(["All human beings are born free and equal",
                            "in dignity and rights..."]):
        d.text((W / 2, 360 + i * 44), ln, font=F_REG(34), fill=(96, 96, 120), anchor="mt")

    # ILK KARE YUKLU: iki sayi da bastan ekranda, yan yana (A dikey kullaniyor)
    ign = clamp01((t - (t0 + 1.05)) / 0.30)
    for x, val, lang, col, lit in ((W * 0.28, "170", "ENGLISH", MINT, 1.0),
                                  (W * 0.72, "497", "HINDI", AMBER, ign)):
        sc = punch(t, t0 + 1.10, 0.22, 0.07) if lit is ign else 1.0
        d.text((x, 640), val, font=F_HUGE(int(168 * sc)),
               fill=mix((66, 60, 44), col, lit), anchor="mm")
        tracked(d, (x, 740), "BYTES", F_SEMI(28), fade(MUTE, lit), track=7, anchor="mt")
        tracked(d, (x, 782), lang, F_DISP(34), mix((60, 58, 48), col, lit), track=3, anchor="mt")
    d.text((W / 2, 640), "vs", font=F_MED(44), fill=(70, 70, 92), anchor="mm")

    a2 = appear(t, S["b2"][0])
    if a2 > 0:
        bw, bh = 300, 110
        bx, by = (W - bw) / 2, 900
        pill(d, (bx, by, bx + bw, by + bh), bh / 2, fade((40, 30, 12), a2))
        d.text((W / 2, by + bh / 2 + 2), "3×", font=F_HUGE(72), fill=fade(AMBER, a2), anchor="mm")
        tracked(d, (W / 2, 1040), "SAME SENTENCE", F_SEMI(34), fade(MUTE, a2), track=9, anchor="mt")

    e = ease_out(clamp01((t - t0 - 0.05) / 0.40))
    draw_byte(d, W + 180 - 400 * e, 1270 + bob(t), 0.44, "alert",
              mix(B_MINT, B_AMBER, ign), blink_on(t))


def scene_mech(d, t, S, spec):
    a0 = appear(t, S["b3"][0])
    tracked(d, (W / 2, 330), "MODELS READ BYTES", F_SEMI(40), fade(MUTE, a0), track=8, anchor="mt")
    tracked(d, (W / 2, 392), "NOT LETTERS", F_MED(30), fade((80, 80, 104), a0), track=6, anchor="mt")

    # BAYT KUTUSU: serinin imza gorseli. Harf solda, kutular sagda.
    top = 560
    for i, g in enumerate(spec["glyphs"]):
        a = appear(t, S["b4"][0] + i * 0.42, 0.34)
        if a <= 0:
            continue
        y = top + i * 230
        col = (MINT, VIOLET, AMBER)[i]
        d.text((160, y + 60), g["ch"], font=glyph_font(g["ch"], 112),
               fill=fade(INK, a), anchor="mm")
        for b in range(g["bytes"]):
            ba = appear(t, S["b4"][0] + i * 0.42 + b * 0.09, 0.26)
            bx = 330 + b * 86
            d.rounded_rectangle((bx, y + 20, bx + 68, y + 88), radius=14,
                                fill=fade(col, ba * 0.85))
        d.text((W - 78, y + 18), f"{g['bytes']} BYTE" + ("S" if g["bytes"] > 1 else ""),
               font=F_DISP(40), fill=fade(col, a), anchor="rt")
        d.text((W - 78, y + 72), g["note"], font=F_REG(30), fill=fade(MUTE, a * 0.9), anchor="rt")


def scene_data(d, t, S, spec):
    rows = spec["rows"]
    a0 = appear(t, S["b5"][0])
    tracked(d, (W / 2, 320), "SAME PARAGRAPH, 8 LANGUAGES", F_SEMI(38),
            fade(MUTE, a0), track=6, anchor="mt")
    tracked(d, (W / 2, 380), "UTF-8 BYTES, MEASURED", F_MED(28),
            fade((80, 80, 104), a0), track=6, anchor="mt")

    maxb = max(r["bytes"] for r in rows)
    top, rh = 500, 186
    for i, r in enumerate(rows):
        t_in = S[r["beat"]][0]
        a = appear(t, t_in, 0.34)
        y = top + i * rh
        col = TONE[r["tone"]]

        if a <= 0:
            # YER TUTUCU: Japonca satiri bos durur, donus aninda dolar.
            if a0 > 0.4:
                d.rounded_rectangle((78, y + 10, W - 78, y + 112), radius=16,
                                    outline=fade(LINE, a0 * 0.8), width=2)
                tracked(d, (W / 2, y + 48), "...", F_DISP(34),
                        fade((64, 64, 84), a0), track=10, anchor="mt")
            continue

        d.text((78, y), r["name"], font=F_DISP(46), fill=fade(INK, a), anchor="lt")
        nb = countup(t, t_in, 0.55, 0, r["bytes"])
        d.text((W - 78, y - 4), f"{nb:.0f}", font=F_DISP(52), fill=fade(col, a), anchor="rt")
        d.text((W - 78, y + 58), f"{r['ratio']:.2f}× EN", font=F_MED(30),
               fill=fade(MUTE, a * 0.9), anchor="rt")

        grow = ease_out(clamp01((t - t_in) / 0.62))
        bw = (W - 156) * (r["bytes"] / maxb) * grow
        by = y + 112
        pill(d, (78, by, W - 78, by + 12), 6, fade((22, 22, 36), a))
        if bw > 12:
            pill(d, (78, by, 78 + bw, by + 12), 6, fade(col, a))



def scene_turn(d, t, S, spec):
    a1 = appear(t, S["b11"][0])
    a2 = appear(t, S["b12"][0])
    a3 = appear(t, S["b13"][0])
    tracked(d, (W / 2, 350), "THE JAPANESE PARADOX", F_SEMI(40), fade(MUTE, appear(t, S["b10"][0])),
            track=8, anchor="mt")

    cards = [("3.00", "BYTES / CHAR", "the highest", AMBER, a1),
             ("85", "CHARACTERS", "half of English", VIOLET, a2)]
    y = 520
    for big, label, note, col, a in cards:
        if a <= 0:
            y += 250
            continue
        yy = y + (1 - ease_out(clamp01(a))) * 24
        pill(d, (78, yy, W - 78, yy + 200), 30, fade((17, 17, 29), a))
        d.rounded_rectangle((78, yy, W - 78, yy + 200), radius=30,
                            outline=fade(col, a * 0.45), width=3)
        d.text((126, yy + 34), big, font=F_HUGE(84), fill=fade(col, a), anchor="lt")
        d.text((W - 126, yy + 52), label, font=F_SEMI(34), fill=fade(MUTE, a), anchor="rt")
        d.text((W - 126, yy + 104), note, font=F_REG(30), fill=fade((104, 104, 128), a), anchor="rt")
        y += 250

    if a3 > 0:
        sc = punch(t, S["b13"][0] + 0.30, 0.24, 0.08)
        d.text((W / 2, 1090), "=", font=F_MED(54), fill=fade((74, 74, 96), a3), anchor="mm")
        d.text((W / 2, 1210), "1.50×", font=F_HUGE(int(118 * sc)), fill=fade(MINT, a3), anchor="mm")
    draw_byte(d, W - 160, 1330 + bob(t), 0.40, "shrug", B_AMBER, blink_on(t, 1.5, 0.22))


def scene_close(d, t, S, spec):
    t0 = S["b14"][0]
    a = appear(t, t0)
    for i, ln in enumerate(["IT'S NOT THE", "LANGUAGE."]):
        ai = appear(t, t0 + i * 0.09, 0.30)
        d.text((W / 2, 600 + i * 124), ln, font=F_HUGE(104), fill=fade(INK, ai), anchor="mt")
    a2 = appear(t, t0 + 0.70)
    if a2 > 0:
        sc = punch(t, t0 + 0.86, 0.24, 0.06)
        for i, ln in enumerate(["IT'S THE", "ALPHABET."]):
            d.text((W / 2, 900 + i * 124), ln, font=F_HUGE(int(104 * sc)),
                   fill=fade(MINT, a2), anchor="mt")
    tracked(d, (W / 2, 1200), "MEASURED: UDHR ARTICLE 1, UTF-8", F_MED(26),
            fade((78, 78, 100), a), track=5, anchor="mt")
    if appear(t, t0 + 0.5) > 0:
        draw_byte(d, W / 2, 1420 + bob(t), 0.48, "idle", B_MINT, blink_on(t, 2.0, 0.2))

STAGES = [
    ("b1", "b2", scene_hook),
    ("b3", "b4", scene_mech),
    ("b5", "b9", scene_data),
    ("b10", "b13", scene_turn),
    ("b14", None, scene_close),
]
