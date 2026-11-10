"""
Yayin metinleri: her platform icin AYRI aciklama + manifest.

Ayni metni uc yere yapistirmak uc yerde de kotu sonuc verir:
  YouTube    uzun aciklama, kaynak listesi, en fazla 5 hashtag
  Instagram  ilk satir akista gorunen TEK satir; link tiklanmiyor
  TikTok     kisa; disari cikan baglanti dagitimi dusuruyor

Metni Gemini yaziyor (editorial/roles.py -> copywriter) ama SON birlestirmeyi
ve dogrulamayi burasi yapiyor: Gemini'nin yazdigi parca, kodun kurdugu iskele
icine yerlesiyor. Boylece Gemini kaynak listesini silemiyor, hashtag sayisini
sisiremiyor, linki aciklamaya sokusturamiyor.

Gemini calismazsa compose(parts=None) sablonlu metni uretir: hat durmaz.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HASHTAG = re.compile(r"^#[A-Za-z][A-Za-z0-9_]{1,29}$")
# platform basina en fazla hashtag. YouTube 15'ten fazlasini birden yok
# sayiyor; Instagram ve TikTok'ta 30 tane spam sinyali.
LIMITS = {"youtube": 5, "instagram": 5, "tiktok": 4}
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿]")
URL = re.compile(r"https?://|www\.", re.I)


def load_brand(root: Path = ROOT) -> dict:
    f = root / "brand.json"
    return json.loads(f.read_text()) if f.exists() else {}


def clean_tags(raw, n: int) -> list[str]:
    """Gemini'nin verdigi hashtag listesini duzeltir. Gecersizleri atar."""
    out: list[str] = []
    for t in raw or []:
        t = str(t).strip().replace(" ", "")
        if not t.startswith("#"):
            t = "#" + t
        if HASHTAG.match(t) and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:n]


def default_tags(brand: dict, spec: dict, n: int) -> list[str]:
    """Gemini'siz hashtag: marka cekirdegi + seri + senaryo etiketleri.
    Rastgele degil, deterministik."""
    h = brand.get("hashtags", {})
    raw = list(h.get("core", []))
    raw += h.get("per_series", {}).get(spec.get("series", ""), [])
    raw += [t.replace(" ", "") for t in spec.get("tags", [])]
    return clean_tags(raw, n)


def _sources(spec: dict) -> str:
    return "\n".join(f"- {s}" for s in spec.get("sources", []))


def compose(brand: dict, spec: dict, parts: dict | None = None) -> dict:
    """Son metinler. parts = Gemini'nin ham ciktisi (ya da None = sablon).

    parts bicimi:
      {"title": str, "alt_titles": [str],
       "youtube": {"hook": str}, "instagram": {"caption": str},
       "tiktok": {"caption": str},
       "hashtags": {"youtube": [...], "instagram": [...], "tiktok": [...]}}
    """
    parts = parts or {}
    handle = brand.get("handle", "")
    title = (parts.get("title") or spec["title"]).strip()
    summary = spec.get("summary", spec["title"])
    ht = parts.get("hashtags") or {}
    tags = {p: clean_tags(ht.get(p), n) or default_tags(brand, spec, n)
            for p, n in LIMITS.items()}

    hook = ((parts.get("youtube") or {}).get("hook") or summary).strip()
    ig_cap = ((parts.get("instagram") or {}).get("caption")
              or f"{title}\n\n{summary}").strip()
    tt_cap = ((parts.get("tiktok") or {}).get("caption") or title).strip()

    youtube = (f"{hook}\n\n"
               f"Sources / method:\n{_sources(spec)}\n\n"
               f"{brand.get('description_footer', '').strip()}\n\n"
               f"{' '.join(tags['youtube'])}").strip()
    instagram = (f"{ig_cap}\n\n"
                 f"Sources and method: YouTube, {handle}.\n"
                 f"{' '.join(tags['instagram'])}").strip()
    tiktok = f"{tt_cap} {' '.join(tags['tiktok'])}".strip()

    return {"title": title,
            "alt_titles": [str(t) for t in parts.get("alt_titles", [])][:5],
            "youtube": youtube, "instagram": instagram, "tiktok": tiktok}


def validate_copy(copy: dict, brand: dict) -> list[str]:
    """Yayin metni kurallari. Bos liste = temiz."""
    p: list[str] = []
    rules = brand.get("title_rules", {})
    title = copy.get("title", "")
    mx = rules.get("max_chars", 60)

    if not title:
        p.append("baslik yok")
    if len(title) > mx:
        p.append(f"baslik {len(title)} karakter > {mx}")
    for bad in rules.get("ban", []):
        if bad.lower() in title.lower():
            p.append(f"baslikta clickbait isareti: {bad!r}")
    letters = [c for c in title if c.isalpha()]
    if len(letters) > 8 and sum(c.isupper() for c in letters) / len(letters) > .6:
        p.append("baslik BUYUK HARFLE bagiriyor")
    if "!!" in title or "?!" in title:
        p.append("baslikta '!!' / '?!'")

    for plat, text in (("youtube", copy.get("youtube", "")),
                       ("instagram", copy.get("instagram", "")),
                       ("tiktok", copy.get("tiktok", ""))):
        if not text:
            p.append(f"{plat} metni bos")
            continue
        if EMOJI.search(text):
            p.append(f"{plat}: emoji var (BYTE bir makine, kuru bir ses)")
        n_tags = len(re.findall(r"(?<!\w)#\w+", text))
        if n_tags > LIMITS[plat]:
            p.append(f"{plat}: {n_tags} hashtag > {LIMITS[plat]}")
        if plat != "youtube" and URL.search(text):
            p.append(f"{plat}: baglanti var -- dagitimi dusuruyor")

    if len(copy.get("youtube", "")) > 4900:
        p.append("youtube aciklamasi 5000 karakter sinirina dayandi")
    if len(copy.get("tiktok", "")) > 300:
        p.append(f"tiktok metni {len(copy['tiktok'])} karakter > 300")
    if len(copy.get("instagram", "")) > 1500:
        p.append("instagram metni cok uzun")
    if "Sources" not in copy.get("youtube", ""):
        p.append("youtube aciklamasinda kaynak bolumu yok")
    return p


HASHTAG_START = re.compile(r"(?<!\w)#\w")


def with_cta(copy: dict, brand: dict, cfg: dict) -> dict:
    """Aciklamalara platforma ozel CTA satiri: YouTube/Instagram'da ilk paragrafin (kanca) hemen
    arkasina, TikTok'ta hashtag'lerin onune. Zaten varsa ya da TikTok 300 karakteri asacaksa
    eklemez (hat durmasin, metin bozulmasin)."""
    from worker.cta import line_for
    out = dict(copy)
    for plat in ("youtube", "instagram", "tiktok"):
        line, text = line_for(cfg, plat, brand), out.get(plat, "")
        if not line or line in text:
            continue
        if plat == "tiktok":
            m = HASHTAG_START.search(text)
            new = (f"{text[:m.start()].rstrip()} {line} {text[m.start():]}" if m
                   else f"{text} {line}").strip()
            if len(new) > 300:
                continue
        else:
            head, sep, rest = text.partition("\n\n")
            new = f"{head}\n\n{line}{sep}{rest}" if sep else f"{text}\n\n{line}"
        out[plat] = new
    return out


def build_manifest(spec: dict, tl: dict, video: Path,
                   root: Path = ROOT) -> dict:
    """Yayin adiminin okuyacagi metadata."""
    brand = load_brand(root)
    copy = spec.get("copy") or compose(brand, spec, spec.get("copy_parts"))
    cta_on = bool(spec.get("_cta"))
    if cta_on:
        from worker.cta import settings as cta_settings
        cfg = cta_settings(brand)
        copy = with_cta(copy, brand, cfg)
    tags = [t for t in brand.get("tags_base", []) + spec.get("tags", [])
            if len(t) <= 30]
    man = {
        "id": spec["id"],
        "series": spec["series"],
        "title": copy["title"],
        "description": copy["youtube"],
        "tags": list(dict.fromkeys(tags))[:15],
        "duration": tl["duration"],
        "video": video.name,
        "theme": spec.get("_theme", ""),
        "privacy": "private",
        "captions": {"youtube": copy["youtube"],
                     "instagram": copy["instagram"],
                     "tiktok": copy["tiktok"]},
    }
    if cta_on:       # YouTube sabitlenmis yorumu API ile pinlenemiyor: panelde/captions.md'de kopyala, elle sabitle
        man["cta"] = {"pinned_comment": cfg["pinned_comment"]}
    return man


def _pinned_section(man: dict) -> str:
    pc = (man.get("cta") or {}).get("pinned_comment", "")
    if not pc:
        return ""
    return ("\n## YouTube sabitlenecek yorum (elle)\n\n"
            "Yayinlandiktan sonra YouTube'da yorum olarak yaz, uc nokta > Sabitle. "
            "API yorum sabitlemeye izin vermiyor.\n\n"
            f"```\n{pc}\n```\n")


def captions_markdown(man: dict) -> str:
    """Instagram/TikTok'a elle yuklerken kopyalanacak metinler. Release
    notu olarak da kullaniliyor: telefondan tek dokunusla kopyalanir."""
    c = man["captions"]
    return (f"# {man['title']}\n\n"
            f"_{man['duration']:.0f} sn, tema: {man.get('theme') or '-'}_\n\n"
            f"## Instagram\n\n```\n{c['instagram']}\n```\n\n"
            f"## TikTok\n\n```\n{c['tiktok']}\n```\n\n"
            f"## YouTube\n\n```\n{c['youtube']}\n```\n"
            + _pinned_section(man))
