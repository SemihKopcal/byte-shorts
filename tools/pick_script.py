#!/usr/bin/env python3
"""
Siradaki senaryoyu secer ve GITHUB_OUTPUT formatinda yazar.

Ayri bir dosya, cunku workflow icine gomulu Python YAML girintisiyle kavga
ediyor: `run: |` blogunda sifir sutundan baslayan bir satir blogu bitiriyor
ve dosyayi gecersiz kiliyor.

Kullanim:
    python tools/pick_script.py            -> path=content/scripts/xxx.json
    python tools/pick_script.py xxx.json   -> o dosyayi secer
    python tools/pick_script.py --dir xxx.json -> dir=out/<id>
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "content/scripts"
PUBLISHED = ROOT / "content/published.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", default="")
    ap.add_argument("--dir", action="store_true",
                    help="path= yerine dir=out/<id> yazar")
    a = ap.parse_args()

    if a.name:
        f = SCRIPTS / a.name
        if not f.exists():
            sys.exit(f"script bulunamadi: {f}")
    else:
        done = set()
        if PUBLISHED.exists():
            done = {x["id"] for x in json.loads(PUBLISHED.read_text())}
        f = None
        for cand in sorted(SCRIPTS.glob("*.json")):
            if json.loads(cand.read_text())["id"] not in done:
                f = cand
                break
        if f is None:
            print("path=")
            return

    if a.dir:
        print(f"dir=out/{json.loads(f.read_text())['id']}")
    else:
        print(f"path={f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
