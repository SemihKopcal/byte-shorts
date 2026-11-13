"""
Harekete cagri (CTA): "begen, takip et / abone ol".

Bu modul SAF mantik: ne zaman, hangi metinle, nereye. Cizim worker/scenes.py (kapanis karti)
ve worker/draw.py (kose etiketi) icinde; metin ekleme publish/manifest.py icinde.

KURALLAR
  * CTA'yi HAT ekler (brand.json "cta"); senaryo yazarken yazilmaz. editorial/rules.py hala
    senaryo metnindeki "subscribe / like and / follow me" kaliplarini yasaklar, yoksa iki kez
    soylenirdi.
  * Karar YALNIZ senaryonun kendisine ve depodaki dosyalara bagli (id, seri, brand.json,
    content/experiments.json). Zamana, built.json'a ya da rastgeleye DEGIL: publish.yml bazi
    akislarda videoyu yeniden uretiyor ve iki render birebir ayni cikmali.
  * A/B deneyindeki videolar da CTA'li cikar: CTA IKI KOLA DA ayni eklenir (+~3 sn) ve deneyin ana
    olcutu ("stayed" = ilk saniyelerde kaydirmama) videonun SONUNDAKI CTA'dan etkilenmez. Temiz
    (CTA'siz) kol istersen brand.json'da skip_experiment_scripts=true yap: kollarin senaryolari
    CTA almaz.
"""
from __future__ import annotations

import json
from pathlib import Path

BEAT_ID = "cta"

DEFAULTS: dict = {
    "enabled": False,
    "skip_experiment_scripts": False,
    # spoken=False: videonun sonunda konusulan cumle YOK; kapanis karti chip'leri ve kose etiketi yine
    # cikar (son cumle konusulurken). Gerekce: konusulan cumle son ~3 saniyeyi olu zamana ceviriyor,
    # izleyici tam orada kaydiriyor ve video basa donerken (dongu) ses bitmeden kesilmiyor.
    "spoken": True,
    "voice": "Like it, and follow Byte for more.",
    "card": {"like": "LIKE", "follow": "FOLLOW BYTE"},
    "corner": {"enabled": True, "text": "LIKE · FOLLOW", "at": 0.42, "seconds": 2.6},
    "description": {},
    "pinned_comment": "",
}


def settings(brand: dict) -> dict:
    """brand.json'daki cta bloku, eksik anahtarlar varsayilanla doldurulmus ve DOGRULANMIS."""
    raw = brand.get("cta") if isinstance(brand.get("cta"), dict) else {}
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in raw.items():
        if k in ("card", "corner", "description") and isinstance(v, dict):
            cfg[k].update(v)
        elif k in cfg and not isinstance(cfg[k], dict):
            cfg[k] = v
    cfg["enabled"] = cfg["enabled"] is True
    cfg["skip_experiment_scripts"] = cfg["skip_experiment_scripts"] is True
    cfg["spoken"] = cfg["spoken"] is not False          # yalniz gercek False sesi kapatir
    cfg["voice"] = " ".join(str(cfg["voice"]).split())[:120]
    cfg["pinned_comment"] = str(cfg["pinned_comment"]).strip()[:500]
    c = cfg["corner"]
    try:
        c["at"] = min(0.9, max(0.1, float(c.get("at", 0.42))))
        c["seconds"] = min(5.0, max(1.0, float(c.get("seconds", 2.6))))
    except (TypeError, ValueError):
        c["at"], c["seconds"] = 0.42, 2.6
    c["enabled"] = c.get("enabled") is not False
    c["text"] = " ".join(str(c.get("text", "")).split())[:30]
    for k, mx in (("like", 12), ("follow", 16)):      # iki chip + bosluk 920 px'e sigmali
        cfg["card"][k] = " ".join(str(cfg["card"].get(k, "")).split())[:mx].upper()
    return cfg


def experiment_ids(root: Path) -> set[str]:
    """content/experiments.json'daki TUM kol listelerindeki senaryo id'leri. Dosya yok/bozuksa bos."""
    f = root / "content" / "experiments.json"
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return set()
    out: set[str] = set()
    for exp in data.values() if isinstance(data, dict) else []:
        arms = exp.get("arms") if isinstance(exp, dict) else None
        for ids in arms.values() if isinstance(arms, dict) else []:
            out |= {x for x in ids if isinstance(x, str)} if isinstance(ids, list) else set()
    return out


def applies(spec: dict, brand: dict, root: Path) -> bool:
    cfg = settings(brand)
    if not cfg["enabled"] or (cfg["spoken"] and not cfg["voice"]):
        return False
    if spec.get("_cta"):                              # zaten eklenmis (sessiz kipte beat yok, isaret bu)
        return False
    if spec.get("series") != "G":                     # yalniz senaryodan okuyan seri (kapanis karti garantili)
        return False
    beats = spec.get("beats") or []
    if not beats or beats[-1].get("scene") != "close":
        return False
    if beats[-1].get("id") == BEAT_ID:                # zaten eklenmis
        return False
    if cfg["skip_experiment_scripts"] and spec.get("id") in experiment_ids(root):
        return False
    return True


def apply(spec: dict, brand: dict, root: Path) -> bool:
    """Gerekiyorsa senaryoya (bellekte; dosyaya yazilmaz) kapanis kartina chip verisini koyar ve,
    `spoken` aciksa, kisa bir son cumle ekler. True = CTA'li."""
    if not applies(spec, brand, root):
        return False
    cfg = settings(brand)
    spec["beats"][-1].setdefault("data", {})["cta"] = dict(cfg["card"])
    if cfg["spoken"]:
        spec["beats"].append({"id": BEAT_ID, "role": "resolve", "say": cfg["voice"], "cap": cfg["voice"]})
    spec["_cta"] = {"corner": dict(cfg["corner"]), "spoken": cfg["spoken"]}
    return True


def active(spec: dict) -> bool:
    return bool(spec.get("_cta"))


def corner_window(duration: float, close_t0: float, cfg: dict) -> tuple[float, float] | None:
    """Kose etiketinin (baslangic, bitis) saniyesi; kapanis kartiyla ya da videonun ilk 3 sn'siyle
    cakisacaksa None."""
    if not cfg.get("enabled"):
        return None
    start = cfg["at"] * duration
    end = start + cfg["seconds"]
    if end > close_t0 - 0.6:
        start = close_t0 - 0.6 - cfg["seconds"]
        end = close_t0 - 0.6
    if start < 3.0:
        return None
    return round(start, 3), round(end, 3)


def line_for(cfg: dict, platform: str, brand: dict) -> str:
    """Aciklamaya eklenecek platforma ozel satir; {handle} marka dosyasindan dolar."""
    tpl = str(cfg.get("description", {}).get(platform, "")).strip()
    handle = (brand.get("handles") or {}).get(platform) or brand.get("handle", "")
    return tpl.replace("{handle}", handle).strip()
