"""
Tema paleti -- her videonun rengi ve dokusu.

SORUN: tek koyu mor-siyah her videoda aynıydı. 30 video sonra izleyici
"hep ayni video" hissi aliyor, ve politika tarafinda da "ayni kaliptan
cikmis icerik" suclamasina yaklasiyoruz.

COZUM: renk degisiyor, BYTE degismiyor. Karakter her videoda birebir ayni
kaliyor (taninirlik), arka plan ve vurgu rengi degisiyor (cesitlilik).
Ikisini karistirmak ikisini de bozar.

KOYU KALIYOR -- parlaklik degil renk degisiyor. Shorts cogunlukla telefonda
ve cogu gece izleniyor; acik arka plan hem goz yoruyor hem de ustundeki
beyaz metnin kontrastini dusuruyor.

STOK GORSEL YOK. Doku da kodla ciziliyor: izgara, nokta matrisi, tarama
cizgisi. Fotograf koymak "AI slop" gorunumune geri donus olurdu.
"""

# bg0  : ust kenar rengi (degrade baslangici)
# bg1  : alt kenar rengi
# glow : ust orta parlama -- sahneye derinlik veren tek sey
# ink  : ana metin
# mute : ikincil metin
# line : ayirici cizgiler
# good/mid/bad : tone degerlerinin karsiligi (TONE tablosu)
# tex  : doku  -> none | grid | dots | scan | contour
THEMES = {
    "midnight": {                     # varsayilan: mor-siyah, nane vurgu
        "bg0": (7, 7, 12), "bg1": (15, 15, 26), "glow": (139, 139, 255),
        "ink": (244, 244, 248), "mute": (124, 124, 148), "line": (34, 34, 52),
        "good": (74, 222, 128), "mid": (139, 139, 255), "bad": (255, 176, 32),
        "tex": "none",
    },
    "ember": {                        # fiyat/maliyet konulari
        "bg0": (14, 6, 8), "bg1": (30, 12, 14), "glow": (255, 120, 80),
        "ink": (250, 242, 238), "mute": (156, 126, 122), "line": (56, 28, 30),
        "good": (120, 222, 150), "mid": (255, 150, 90), "bad": (255, 86, 86),
        "tex": "scan",
    },
    "deep": {                         # hiz, gecikme, performans
        "bg0": (5, 9, 20), "bg1": (10, 20, 42), "glow": (80, 180, 255),
        "ink": (238, 246, 252), "mute": (116, 140, 168), "line": (24, 40, 64),
        "good": (90, 230, 200), "mid": (80, 180, 255), "bad": (255, 170, 70),
        "tex": "grid",
    },
    "moss": {                         # verimlilik, kaynak kullanimi
        "bg0": (7, 13, 10), "bg1": (14, 26, 20), "glow": (120, 220, 140),
        "ink": (240, 248, 242), "mute": (118, 146, 128), "line": (26, 48, 36),
        "good": (190, 240, 90), "mid": (120, 220, 160), "bad": (255, 180, 60),
        "tex": "dots",
    },
    "slate": {                        # karsilastirma, notr
        "bg0": (10, 11, 13), "bg1": (22, 24, 28), "glow": (150, 160, 180),
        "ink": (245, 246, 248), "mute": (132, 138, 150), "line": (42, 46, 54),
        "good": (110, 225, 160), "mid": (170, 180, 200), "bad": (255, 128, 110),
        "tex": "grid",
    },
    "plum": {                         # "sasirtici" konular, donus anlari
        "bg0": (12, 6, 16), "bg1": (26, 13, 34), "glow": (200, 110, 255),
        "ink": (247, 240, 250), "mute": (146, 124, 160), "line": (48, 28, 60),
        "good": (120, 230, 180), "mid": (210, 130, 255), "bad": (255, 150, 90),
        "tex": "contour",
    },
    "rust": {                         # limitler, kisitlar, hatalar
        "bg0": (14, 9, 6), "bg1": (28, 19, 12), "glow": (230, 150, 70),
        "ink": (250, 245, 238), "mute": (152, 134, 112), "line": (52, 38, 24),
        "good": (150, 220, 120), "mid": (235, 170, 80), "bad": (255, 110, 80),
        "tex": "dots",
    },
    "ice": {                          # veri, olcum, tablo agirlikli
        "bg0": (6, 12, 16), "bg1": (12, 24, 32), "glow": (110, 210, 230),
        "ink": (240, 250, 252), "mute": (118, 148, 158), "line": (24, 46, 56),
        "good": (120, 235, 190), "mid": (110, 210, 230), "bad": (255, 165, 100),
        "tex": "scan",
    },
}

NAMES = tuple(THEMES)

# ── karton / cizgi film stili (worker/cartoon.py) ────────────────────────────
# Bu temalar NAMES'e GIRMEZ: editorial'in sanat yonetmeni ve pick() sadece koyu paletten secer; karton
# stili brand.json "cartoon" blogundan acilir ve temayi kendisi koyar. Iki yuz: acik kagit ve koyu lacivert
# (referans videoda sahneler ikisi arasinda gidip geliyor).
#   panel/panel2/on_accent/track : CTA hapi, kose etiketi, vurgu ustu yazi, ilerleme izi
#   shadow  : sprite'larin sert ofset golgesi      outline : sprite dis cizgisi
TOON_THEMES = {
    "paper": {
        "bg0": (244, 236, 212), "bg1": (237, 227, 199), "glow": (255, 248, 228),
        "ink": (28, 26, 34), "mute": (112, 106, 100), "line": (204, 192, 160),
        "good": (28, 148, 84), "mid": (46, 84, 196), "bad": (214, 48, 48),
        "tex": "paper",
        "panel": (252, 250, 242), "panel2": (252, 250, 242), "on_accent": (252, 250, 242),
        "track": (220, 208, 176), "shadow": (208, 195, 160), "outline": (28, 26, 34),
    },
    "ink": {
        "bg0": (24, 31, 52), "bg1": (19, 25, 44), "glow": (90, 110, 170),
        "ink": (244, 240, 226), "mute": (150, 158, 184), "line": (52, 62, 92),
        "good": (88, 214, 141), "mid": (126, 172, 255), "bad": (255, 196, 64),
        "tex": "none",
        "panel": (36, 46, 74), "panel2": (36, 46, 74), "on_accent": (20, 24, 40),
        "track": (44, 54, 84), "shadow": (11, 15, 30), "outline": (244, 240, 226),
    },
}
ALL_THEMES = {**THEMES, **TOON_THEMES}


def colors(name: str) -> dict:
    """Tema renkleri (koyu paletler + karton temalari)."""
    return ALL_THEMES.get(name, {})

# Konu -> tema egilimi. Gemini senaryoda "theme" alani verebiliyor; vermezse
# etiketlerden tahmin ediyoruz. Rastgele degil, cunku renk anlam tasiyor:
# para konusu sicak, hiz konusu soguk.
BY_TAG = {
    "pricing": "ember", "cost": "ember", "price": "ember", "billing": "ember",
    "speed": "deep", "latency": "deep", "performance": "deep", "benchmark": "deep",
    "efficiency": "moss", "memory": "moss", "energy": "moss",
    "comparison": "slate", "versus": "slate", "vs": "slate",
    "surprising": "plum", "myth": "plum", "weird": "plum",
    "limit": "rust", "failure": "rust", "error": "rust", "quota": "rust",
    "data": "ice", "measurement": "ice", "tokens": "ice", "context": "ice",
}


def pick(spec: dict, recent: list[str] | None = None) -> str:
    """Senaryoya gore tema. Son 3 videonun temasi tekrarlanmiyor."""
    recent = [r for r in (recent or []) if r in THEMES][-3:]

    want = spec.get("theme")
    if want in THEMES and want not in recent:
        return want

    for tag in [t.lower() for t in spec.get("tags", [])] + \
               spec.get("title", "").lower().split():
        t = BY_TAG.get(tag.strip(".,:"))
        if t and t not in recent:
            return t

    # Hic eslesme yoksa: id'den deterministik sec. Rastgele DEGIL -- publish
    # adimi videoyu yeniden uretiyor, iki render ayni cikmali.
    pool = [n for n in NAMES if n not in recent] or list(NAMES)
    return pool[sum(map(ord, spec.get("id", "x"))) % len(pool)]
