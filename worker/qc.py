"""
Yayin oncesi otomatik kontrol.

Burasi "guzel mi" diye bakmiyor -- ona sen bakacaksin. Burasi, FARK ETMEDEN
yayinlanirsa kanali yakabilecek seyleri ariyor:

  * 60 saniyeyi gecen video     -> Shorts rafindan duser, uzun video olur
  * 1080x1920 disi en-boy       -> kenarlarda siyah bant
  * sessiz veya kisik ses       -> izleyici 2 saniyede cikar
  * tekrar eden baslik/konu     -> Temmuz 2026 "sablon icerik" maddesi
  * kaynaksiz sayi iddiasi      -> kanalin tek savunmasi kaynak gostermek

Son iki madde en onemlisi: YouTube'un 2026 kurallari birbirinin ayni kaliptan
cikmis videolari eliyor. Yayinlanan her videoyu content/published.json'a
yaziyoruz ve yeni videoyu ona karsi kontrol ediyoruz.
"""
import json
import re
import subprocess
from pathlib import Path

MAX_SECONDS = 59.0
MIN_SECONDS = 15.0
W, H = 1080, 1920
# Shorts fiili standardi -14 LUFS. +-2 LU disi = belirgin sekilde kisik/yuksek.
TARGET_LUFS = -14.0
LUFS_TOL = 2.0


def _ffprobe(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(video)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _loudness(video: Path) -> float | None:
    """ffmpeg'in loudnorm olcum gecisi JSON'u stderr'e yaziyor."""
    r = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(video), "-af",
         "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"\{[^{]*input_i[^}]*\}", r.stderr, re.S)
    if not m:
        return None
    try:
        return float(json.loads(m.group(0))["input_i"])
    except Exception:
        return None


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def check(video: Path, tl: dict, spec: dict, published: Path) -> list[str]:
    p: list[str] = []

    # ── sure ──
    d = tl["duration"]
    if d > MAX_SECONDS:
        p.append(f"sure {d:.1f}s > {MAX_SECONDS}s -- Shorts rafindan duser")
    if d < MIN_SECONDS:
        p.append(f"sure {d:.1f}s cok kisa; izlenme orani olcumu anlamsizlasiyor")

    # ── konteyner ──
    if not video.exists():
        return p + ["video dosyasi yok"]
    info = _ffprobe(video)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        p.append("video akisi yok")
    else:
        if (v["width"], v["height"]) != (W, H):
            p.append(f"cozunurluk {v['width']}x{v['height']} != {W}x{H}")
        if v.get("pix_fmt") != "yuv420p":
            p.append(f"pix_fmt {v.get('pix_fmt')} -- bazi cihazlarda oynamaz")
    if not a:
        p.append("ses akisi yok")
    else:
        lu = _loudness(video)
        if lu is None:
            p.append("ses seviyesi olculemedi")
        elif abs(lu - TARGET_LUFS) > LUFS_TOL:
            p.append(f"ses {lu:.1f} LUFS, hedef {TARGET_LUFS} (+-{LUFS_TOL})")

    size_mb = video.stat().st_size / 1e6
    if size_mb > 120:
        p.append(f"dosya {size_mb:.0f} MB -- artifact kotasini hizla yer")

    # ── metin / politika ──
    bf = Path(__file__).resolve().parent.parent / "brand.json"
    brand = json.loads(bf.read_text()) if bf.exists() else {}
    rules = brand.get("title_rules", {})
    title = spec.get("title", "")
    if not title:
        p.append("baslik yok")
    if len(title) > rules.get("max_chars", 60):
        p.append(f"baslik {len(title)} karakter > {rules.get('max_chars', 60)}")
    for bad in rules.get("ban", []):
        if bad.lower() in title.lower():
            p.append(f"baslikta clickbait isareti: {bad!r}")

    # sahne adlari katalogda var mi (Gemini uydurmus olabilir)
    from .scenes import CATALOG
    seen = []
    for b in spec.get("beats", []):
        s = b.get("scene")
        if s and s not in CATALOG and spec.get("series") == "G":
            p.append(f"bilinmeyen sahne {s!r} (beat {b.get('id')})")
        if s:
            seen.append(s)
    # tek sahneyle cekilmis video = slideshow; politika tarafinda riskli
    if spec.get("series") == "G" and len(set(seen)) < 3:
        p.append(f"sadece {len(set(seen))} farkli sahne tipi -- en az 3 olmali")

    if not spec.get("sources"):
        p.append("kaynak listesi bos -- ekranda sayi varsa kaynak zorunlu")

    # ekranda gecen her sayi icin en az bir kaynak satiri bekliyoruz
    caps = " ".join(b.get("cap", "") for b in spec.get("beats", []))
    if re.search(r"\d", caps) and len(spec.get("sources", [])) == 0:
        p.append("ekranda sayi var ama kaynak yok")

    # ── tekrar (sablon icerik maddesi) ──
    if published.exists():
        prev = json.loads(published.read_text())
        tw = _words(title)
        for old in prev[-40:]:
            if old.get("id") == spec["id"]:
                p.append(f"bu id zaten yayinlanmis: {spec['id']}")
            ow = _words(old.get("title", ""))
            if tw and ow and len(tw & ow) / len(tw | ow) > 0.6:
                p.append(f"baslik onceki bir videoya cok benziyor: {old.get('title')!r}")
        recent = [o.get("series") for o in prev[-3:]]
        if len(recent) == 3 and all(r == spec["series"] for r in recent):
            p.append(f"son 3 video da seri {spec['series']} -- seriyi degistir")

    return p
