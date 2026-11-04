"""
Seri A -- "The Number". Veri tablosu: bir sayi etrafinda kurulu, satir satir
acilan karsilastirma. Gorsel imzasi dikey tablo + bar.
"""
from PIL import ImageDraw

from .draw import (W, H, INK, MUTE, MINT, AMBER, VIOLET, LINE, TONE,
                   F_HUGE, F_DISP, F_SEMI, F_MED, F_REG,
                   clamp01, ease_out, appear, punch, countup, mix, fade,
                   tracked, pill, bob, blink_on)
from .byte import draw_byte, MINT as B_MINT, AMBER as B_AMBER, RED as B_RED


def scene_hook(d, t, S, spec):
    t0 = S["b1"][0]
    # Ilk kare YUKLU: baslik ve iki sayi animasyonsuz, hemen ekranda.
    tracked(d, (W / 2, 430), "1 MINUTE OF AI VIDEO", F_SEMI(42), MUTE, track=7, anchor="mt")
    d.text((W / 2, 800), "$3", font=F_HUGE(260), fill=MINT, anchor="mm")
    d.line([(W * 0.24, 975), (W * 0.76, 975)], fill=LINE, width=3)

    # $24 ILK KAREDE OKUNUR durumda (sonuk), ses oraya gelince ateslenip punch
    # atiyor. Burada sayi SAYDIRMIYORUZ: hook'un tamami "3 mu 24 mu" celiskisi,
    # ilk karede 24 yazmiyorsa celiski yok demektir. (Sayma tabloda, dakika
    # tutarlarinda kullaniliyor -- orada okumayi yavaslatmak iyi.)
    ign = clamp01((t - (t0 + 0.95)) / 0.28)
    sc = punch(t, t0 + 1.00, 0.22, 0.08)
    d.text((W / 2, 1130), "$24", font=F_HUGE(int(260 * sc)),
           fill=mix((78, 68, 44), AMBER, ign), anchor="mm")

    a3 = appear(t, S["b2"][0])
    if a3 > 0:
        d.line([(W * 0.32, 1300), (W * 0.68, 1300)], fill=fade(VIOLET, a3 * 0.7), width=3)
        tracked(d, (W / 2, 1322), "SAME LENGTH", F_SEMI(34), fade(MUTE, a3), track=9, anchor="mt")

    # BYTE sagdan sert girer: ilk yarim saniyede desen kirilmasi.
    e = ease_out(clamp01((t - t0 - 0.05) / 0.38))
    bx = W + 200 - 420 * e
    draw_byte(d, bx, 1180 + bob(t), 0.46, "alert",
              mix(B_MINT, B_AMBER, ign), blink_on(t))


def scene_table(d, t, S, spec):
    rows = spec["rows"]
    dim = 1.0 - 0.72 * appear(t, S["b9"][0], 0.30)
    a0 = appear(t, S["b3"][0]) * dim
    tracked(d, (W / 2, 330), "API PRICE PER SECOND", F_SEMI(40), fade(MUTE, a0), track=8, anchor="mt")
    tracked(d, (W / 2, 392), "SEPTEMBER 2026", F_MED(30), fade((80, 80, 104), a0), track=6, anchor="mt")

    maxps = max(r["ps"] for r in rows)
    top, rh = 530, 192
    keys = ["b4", "b5", "b6", "b7"]
    for i, r in enumerate(rows):
        t_in = S[keys[i]][0]
        a = appear(t, t_in, 0.34) * dim
        if a <= 0:
            continue
        # giris cesitliligi: tek sayili satirlar soldan, cift sayililar sagdan
        slide = (1 - ease_out(clamp01((t - t_in) / 0.34))) * (38 if i % 2 == 0 else -38)
        y = top + i * rh
        col = TONE[r["tone"]]

        d.text((78 + slide, y), r["name"], font=F_DISP(50), fill=fade(INK, a), anchor="lt")
        d.text((78 + slide, y + 62), r["sub"], font=F_REG(31), fill=fade(MUTE, a * 0.9), anchor="lt")

        ps = f"${r['ps']:.3f}" if r["ps"] * 100 % 1 else f"${r['ps']:.2f}"
        d.text((W - 78, y + 2), f"{ps}/s", font=F_DISP(52), fill=fade(col, a), anchor="rt")
        # dakika tutari sayarak cikiyor
        per_min = countup(t, t_in + 0.10, 0.55, 0, r["ps"] * 60)
        d.text((W - 78, y + 66), f"${per_min:.2f} / min", font=F_MED(31),
               fill=fade(MUTE, a * 0.9), anchor="rt")

        grow = ease_out(clamp01((t - t_in) / 0.62))
        bw = (W - 156) * (r["ps"] / maxps) * grow
        by = y + 124
        pill(d, (78, by, W - 78, by + 12), 6, fade((22, 22, 36), a))
        if bw > 12:
            pill(d, (78, by, 78 + bw, by + 12), 6, fade(col, a))

    a8 = appear(t, S["b8"][0]) * dim
    if a8 > 0:
        y = top + 4 * rh + 14
        d.line([(78, y), (W - 78, y)], fill=fade(LINE, a8), width=2)
        d.text((78, y + 34), "SAME 60 SECONDS", font=F_SEMI(36), fill=fade(MUTE, a8), anchor="lt")
        d.text((W - 78, y + 28), "$3.00 → $24.00", font=F_DISP(44), fill=fade(INK, a8), anchor="rt")

    a9 = appear(t, S["b9"][0])
    if a9 > 0:
        sc = (0.7 + 0.3 * a9) * punch(t, S["b9"][0] + 0.30, 0.24, 0.08)
        bw = 420
        cxx, cyy = W / 2, 970
        d.ellipse((cxx - bw / 2 * sc, cyy - bw / 2 * sc, cxx + bw / 2 * sc, cyy + bw / 2 * sc),
                  fill=fade((16, 16, 28), a9), outline=fade(AMBER, a9 * 0.85), width=4)
        d.text((cxx, cyy), "8×", font=F_HUGE(int(210 * sc)), fill=fade(AMBER, a9), anchor="mm")
        draw_byte(d, 150, 1330 + bob(t), 0.40, "alert", B_RED, blink_on(t, 1.1, 0.3))
    elif a0 > 0.2:
        # tablo kurulurken BYTE kenarda, yukariyi gosteriyor
        draw_byte(d, 148, 1340 + bob(t), 0.38, "point_up", B_MINT, blink_on(t))


def scene_turn(d, t, S, spec):
    a1 = appear(t, S["b10"][0])
    a2 = appear(t, S["b11"][0])
    tracked(d, (W / 2, 560), "MOST PEOPLE", F_SEMI(44), fade(MUTE, a1), track=8, anchor="mt")
    tracked(d, (W / 2, 626), "GET THIS WRONG", F_SEMI(44), fade(MUTE, a1), track=8, anchor="mt")
    if a2 > 0:
        sc = punch(t, S["b11"][0] + 0.12, 0.20, 0.05)
        y = 800
        for i, ln in enumerate(["DON'T GENERATE", "THE WHOLE", "MINUTE."]):
            col = AMBER if i == 2 else INK
            d.text((W / 2, y + i * 132), ln, font=F_HUGE(int(112 * sc)),
                   fill=fade(col, a2), anchor="mt")
    draw_byte(d, W - 160, 1310 + bob(t), 0.42, "shrug", B_AMBER, blink_on(t, 1.4, 0.25))


def scene_fix(d, t, S, spec):
    a1 = appear(t, S["b12"][0])
    a2 = appear(t, S["b13"][0])
    tracked(d, (W / 2, 390), "DO THIS INSTEAD", F_SEMI(40), fade(MUTE, a1), track=8, anchor="mt")

    cards = [("3s", "AI HOOK", "$0.15", MINT, a1, S["b12"][0]),
             ("57s", "STILLS + MOTION", "$0.00", VIOLET, a2, S["b13"][0])]
    y = 540
    for dur_s, label, cost, col, a, t_in in cards:
        if a <= 0:
            y += 290
            continue
        slide = (1 - ease_out(clamp01((t - t_in) / 0.34))) * 44
        x0, x1 = 78 + slide, W - 78 + slide
        pill(d, (x0, y, x1, y + 240), 34, fade((17, 17, 29), a))
        d.rounded_rectangle((x0, y, x1, y + 240), radius=34, outline=fade(col, a * 0.5), width=3)
        d.text((x0 + 48, y + 40), dur_s, font=F_HUGE(92), fill=fade(col, a), anchor="lt")
        d.text((x0 + 48, y + 154), label, font=F_SEMI(38), fill=fade(MUTE, a), anchor="lt")
        d.text((x1 - 48, y + 86), cost, font=F_DISP(78), fill=fade(INK, a), anchor="rt")
        y += 290

    if a2 > 0:
        yy = 1140
        d.line([(78, yy), (W - 78, yy)], fill=fade(LINE, a2), width=2)
        d.text((78, yy + 36), "TOTAL", font=F_SEMI(40), fill=fade(MUTE, a2), anchor="lt")
        sc = punch(t, S["b13"][0] + 0.45, 0.22, 0.07)
        d.text((W - 78, yy + 24), "$0.15", font=F_HUGE(int(66 * sc)), fill=fade(MINT, a2), anchor="rt")
        d.text((W - 78, yy + 108), "was $3.00", font=F_MED(34), fill=fade((96, 96, 120), a2), anchor="rt")
    draw_byte(d, 150, 1340 + bob(t), 0.40, "point_r", B_MINT, blink_on(t))


def scene_payoff(d, t, S, spec):
    t0 = S["b14"][0]
    a = appear(t, t0)
    d.text((W / 2, 660), "SAME", font=F_HUGE(130), fill=fade(INK, a), anchor="mt")
    d.text((W / 2, 796), "RUNTIME", font=F_HUGE(130), fill=fade(INK, a), anchor="mt")
    a2 = appear(t, t0 + 0.72)
    if a2 > 0:
        sc = punch(t, t0 + 0.88, 0.24, 0.07)
        bw, bh = 700 * sc, 150 * sc
        bx, by = (W - bw) / 2, 1010
        pill(d, (bx, by, bx + bw, by + bh), bh / 2, fade((18, 40, 28), a2))
        d.text((W / 2, by + bh / 2 + 2), "90% CHEAPER", font=F_HUGE(int(80 * sc)),
               fill=fade(MINT, a2), anchor="mm")
    draw_byte(d, W - 165, 1330 + bob(t), 0.44, "idle", B_MINT, blink_on(t))


def scene_close(d, t, S, spec):
    t0 = S["b15"][0]
    a = appear(t, t0)
    lines = ["PRICE PER SECOND", "IS THE ONLY", "NUMBER THAT", "MATTERS."]
    y = 620
    for i, ln in enumerate(lines):
        ai = appear(t, t0 + i * 0.09, 0.30)
        col = MINT if i == 3 else INK
        size = 84 if i == 0 else 104
        d.text((W / 2, y + i * 126), ln, font=F_HUGE(size), fill=fade(col, ai), anchor="mt")
    tracked(d, (W / 2, 1200), "SOURCE: PUBLISHED API PRICE LISTS", F_MED(26),
            fade((78, 78, 100), a), track=5, anchor="mt")
    a2 = appear(t, t0 + 0.55)
    if a2 > 0:
        draw_byte(d, W / 2, 1420 + bob(t), 0.50, "idle", B_MINT, blink_on(t, 2.0, 0.2))

# beat id -> sahne. build.py bu tabloyu okuyup zaman araliklarini kuruyor.
STAGES = [
    ("b1", "b2", scene_hook),
    ("b3", "b9", scene_table),
    ("b10", "b11", scene_turn),
    ("b12", "b13", scene_fix),
    ("b14", "b14", scene_payoff),
    ("b15", None, scene_close),
]
