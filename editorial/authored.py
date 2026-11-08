"""
Elle (ya da Claude tarafindan) yazilmis senaryolar. Gemini YOK, kapi AYNI:

  * senaryo kurallari (sure, sahneler, sira, yasakli kaliplar): rules.validate_script
  * ekrandaki her anlamli sayi ya bir formulle (kod hesaplar) ya da bir kaynak
    numarasiyla eslesir: rules.check_claims
  * hikaye bicimi en az iki olay iddiasini kaynaga baglar: rules.fact_lookups
  * kaynaklar tiklanabilir https adresleri; hic kullanilmayan kaynak yazilmaz
  * yayin metni brand kurallarindan gecer

Arama destekli dogrulayici burada yok, onun yerine insan/yazar dogruluyor ve
bunu dosyada ISIMLENDIRIYOR: her kaynakli iddianin "note" alani sayfanin ne
dedigini yazar. Kod sayfayi acip okuyamaz; ama dosyada iddia + kaynak + not
olmadan senaryo kapidan gecmez.

Dosya: content/scripts/<id>.json, icinde "authored" anahtari olmali.

    python -m editorial.authored            # hepsini denetle, sorun varsa 1
    python -m editorial.authored p001-x     # yalniz birini
"""
import json
import re
import sys
from pathlib import Path

from publish import manifest as M

from . import rules

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = "content/scripts"
REQUIRED = ("id", "series", "lang", "format", "title", "summary", "tags",
            "sources", "beats", "claims", "facts", "copy_parts", "authored")
URL = re.compile(r"^https://[^\s/]+\.[^\s/]+\S*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def problems(spec: dict, scene_names, brand: dict, filename: str | None = None
             ) -> list[str]:
    """Bos liste = senaryo kapidan geciyor."""
    p: list[str] = []
    for k in REQUIRED:
        if k not in spec:
            p.append(f"eksik alan: {k}")
    if p:
        return p

    if filename and Path(filename).stem != spec["id"]:
        p.append(f"dosya adi ({Path(filename).stem}) id ile ({spec['id']}) ayni olmali")
    a = spec["authored"]
    if not isinstance(a, dict) or not a.get("by") or not DATE.match(str(a.get("date", ""))):
        p.append('"authored" {by, date: YYYY-MM-DD} olmali')

    src = spec["sources"]
    if not isinstance(src, list) or not 2 <= len(src) <= 6:
        return p + ["kaynak sayisi 2..6 olmali"]
    bad = [s for s in src if not (isinstance(s, str) and URL.match(s))]
    if bad:
        p.append(f"kaynaklar https adresi olmali: {bad[0]!r}")
    if len(set(src)) != len(src):
        p.append("kaynaklar tekrar ediyor")

    p += rules.validate_script(spec, scene_names)

    claim_p, lookups = rules.check_claims(spec, spec["claims"], len(src))
    fact_p, facts = rules.fact_lookups(spec, spec["facts"], len(src))
    p += claim_p + fact_p

    for c in lookups:
        if not str(c.get("note", "")).strip():
            p.append(f"'{c.get('shown')}': kaynakli iddianin 'note' alani bos "
                     "(sayfa ne diyor?)")
    for f in spec["facts"] if isinstance(spec["facts"], list) else []:
        if isinstance(f, dict) and f.get("claim") and not str(f.get("note", "")).strip():
            p.append(f"'{str(f['claim'])[:50]}': olay iddiasinin 'note' alani bos")

    used = {c["source"] for c in lookups} | {f["source"] for f in facts}
    for i, s in enumerate(src):
        if i not in used:
            p.append(f"kaynak #{i} hicbir iddiada kullanilmiyor: {s}")

    parts = spec["copy_parts"]
    if not isinstance(parts, dict):
        p.append("copy_parts bir nesne olmali")
    else:
        for path in (("youtube", "hook"), ("instagram", "caption"),
                     ("tiktok", "caption")):
            if not str((parts.get(path[0]) or {}).get(path[1], "")).strip():
                p.append(f"copy_parts.{path[0]}.{path[1]} yok")
        copy = M.compose(brand, spec, parts)
        p += [f"yayin metni: {x}" for x in M.validate_copy(copy, brand)]
    return p


def check_all(root: Path = ROOT, scene_names=None, only: str | None = None
              ) -> dict[str, list[str]]:
    """{dosya adi: sorunlar}. Yalniz "authored" anahtarli dosyalar."""
    if scene_names is None:
        from worker.scenes import NAMES as scene_names     # noqa: N811
    brand = M.load_brand(root)
    out: dict[str, list[str]] = {}
    seen_ids: dict[str, str] = {}
    seen_titles: dict[str, str] = {}
    for f in sorted((root / SCRIPTS).glob("*.json")):
        if only and f.stem != only:
            continue
        try:
            spec = json.loads(f.read_text())
        except ValueError as e:
            out[f.name] = [f"gecersiz JSON: {e}"]
            continue
        if not isinstance(spec, dict) or "authored" not in spec:
            continue
        p = problems(spec, scene_names, brand, f.name)
        if spec.get("id") in seen_ids:
            p.append(f"id {spec['id']} {seen_ids[spec['id']]} ile cakisiyor")
        t = str(spec.get("title", "")).lower()
        if t in seen_titles:
            p.append(f"baslik {seen_titles[t]} ile ayni")
        seen_ids.setdefault(spec.get("id"), f.name)
        seen_titles.setdefault(t, f.name)
        out[f.name] = p
    return out


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    only = args[0] if args else None
    res = check_all(only=only)
    bad = {k: v for k, v in res.items() if v}
    for name, ps in bad.items():
        print(f"\n{name}:")
        for x in ps:
            print(f"  - {x}")
    print(f"\n{len(res)} yazilmis senaryo, {len(bad)} sorunlu")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
