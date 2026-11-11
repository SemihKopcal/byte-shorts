#!/usr/bin/env python3
"""
Klon ses icin: hangi senaryolara ses uretilecek ve her birinde HANGI cumleler okunacak.

Colab not defteri (colab/byte_colab_ses_uret.ipynb) bunu cagirir. Cumleler build'in synth'e verdigi
haliyle verilir: CTA cumlesi (brand.json) dahil. Ses bu cumlelerle uretilirse render onu bulur.

    python tools/voice_lines.py --next 10     sirada bekleyen ilk 10 senaryonun kimligi (satir satir)
    python tools/voice_lines.py <id|dosya>    {"id": ..., "beats": [{"id": "b1", "say": "..."}, ...], "sha": {...}}
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pick_script as PICK                       # noqa: E402
from publish.manifest import load_brand          # noqa: E402
from worker import cta as CTA                    # noqa: E402
from worker import voiceover as CLONE            # noqa: E402


def spec_for(arg: str) -> dict:
    """Senaryo kimligi ya da dosya yolu -> render'in gorecegi spec (CTA eklenmis)."""
    p = Path(arg)
    if not p.is_file():
        p = PICK.SCRIPTS / (arg if arg.endswith(".json") else arg + ".json")
    if not p.is_file():
        cands = sorted(PICK.SCRIPTS.glob(arg + "*.json"))
        if len(cands) != 1:
            sys.exit(f"senaryo bulunamadi (ya da birden fazla eslesti): {arg}")
        p = cands[0]
    spec = json.loads(p.read_text())
    CTA.apply(spec, load_brand(ROOT), ROOT)
    return spec


def describe(spec: dict) -> dict:
    return {"id": spec["id"], "beats": CLONE.lines(spec), "manifest": CLONE.make_manifest(spec)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?", default="")
    ap.add_argument("--next", type=int, default=0, metavar="N")
    a = ap.parse_args(argv)
    if a.next:
        done = PICK._ids(PICK.PUBLISHED) | PICK._ids(PICK.BUILT)
        for f in PICK.queue(done)[: max(0, a.next)]:
            print(PICK._spec_id(f))
        return 0
    if not a.script:
        ap.error("senaryo kimligi ya da --next N gerekli")
    print(json.dumps(describe(spec_for(a.script)), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
