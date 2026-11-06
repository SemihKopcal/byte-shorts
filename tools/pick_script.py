#!/usr/bin/env python3
"""
Siradaki senaryoyu secer ve GITHUB_OUTPUT formatinda yazar.

Ayri bir dosya, cunku workflow icine gomulu Python YAML girintisiyle kavga
ediyor: `run: |` blogunda sifir sutundan baslayan bir satir blogu bitiriyor
ve dosyayi gecersiz kiliyor.

IKI defter tutuluyor:
  content/built.json      uretilmis olanlar  (daily yaziyor)
  content/published.json  yayinlanmis olanlar (publish yaziyor)

Ikisi de atlaniyor. Sadece published'a bakmak bir hataydi: yayinlamayi
bekledigin surece daily her gece AYNI videoyu uretiyordu.

Kullanim:
    python tools/pick_script.py                 -> path=content/scripts/xxx.json
    python tools/pick_script.py xxx.json        -> o dosyayi secer
    python tools/pick_script.py --newest        -> SIRADAKI en yeni olani secer
    python tools/pick_script.py --dir xxx.json  -> dir=out/<id>
    python tools/pick_script.py --mark xxx.json -> built.json'a isler
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "content/scripts"
PUBLISHED = ROOT / "content/published.json"
BUILT = ROOT / "content/built.json"


def _ids(p: pathlib.Path) -> set:
    if not p.exists():
        return set()
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError:
        return set()
    return {x["id"] if isinstance(x, dict) else x for x in d}


def _spec_id(f: pathlib.Path) -> str:
    return json.loads(f.read_text())["id"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", default="")
    ap.add_argument("--newest", action="store_true",
                    help="en eski yerine en yeni islenmemis senaryoyu sec "
                         "(az once Gemini'nin yazdigi senaryo icin)")
    ap.add_argument("--dir", action="store_true",
                    help="path= yerine dir=out/<id> yazar")
    ap.add_argument("--mark", action="store_true",
                    help="verilen senaryoyu built.json'a isler")
    ap.add_argument("--needs-cjk", action="store_true",
                    help="CJK fontu gerekiyorsa 'yes' yazar")
    a = ap.parse_args()

    if a.name:
        f = SCRIPTS / a.name
        if not f.exists():
            sys.exit(f"script bulunamadi: {f}")
    else:
        done = _ids(PUBLISHED) | _ids(BUILT)
        todo = [c for c in sorted(SCRIPTS.glob("*.json"))
                if _spec_id(c) not in done]
        f = (todo[-1] if a.newest else todo[0]) if todo else None
        if f is None:
            print("path=")
            return

    if a.needs_cjk:
        # SADECE gercek CJK/Kana/Hangul araliklari. "ASCII disi" diye bakmak
        # fazla genis: × ve — gibi isaretler Inter'de zaten var, onlar icin
        # 60 MB'lik font paketi indirmenin anlami yok.
        txt = f.read_text()
        cjk = any(
            "぀" <= ch <= "ヿ" or      # kana
            "㐀" <= ch <= "䶿" or      # CJK ext A
            "一" <= ch <= "鿿" or      # CJK
            "가" <= ch <= "힯" or      # hangul
            "豈" <= ch <= "﫿"         # uyumluluk
            for ch in txt)
        print("yes" if cjk else "no")
        return

    if a.mark:
        prev = json.loads(BUILT.read_text()) if BUILT.exists() else []
        sid = _spec_id(f)
        if sid not in prev:
            prev.append(sid)
            BUILT.write_text(json.dumps(prev, indent=1, ensure_ascii=False))
        print(f"islendi: {sid}", file=sys.stderr)
        return

    if a.dir:
        print(f"dir=out/{_spec_id(f)}")
    else:
        print(f"path={f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
