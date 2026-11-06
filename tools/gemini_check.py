"""
Bu anahtar hangi Gemini modellerini GERCEKTEN calistiriyor?

    GEMINI_API_KEY=... python tools/gemini_check.py
    (ya da Actions > gemini-check > Run workflow; anahtar zaten secret'ta)

Her aday modele kucuk bir istek atar: cevap verdi mi, kac saniyede, 429 ise
nedeni ne (kota yok / gunluk / dakikalik). Cevap verenlere bir de arama
destekli (grounding) istek atar: hikaye/gundem bicimi aramayla dogrulama
gerektiriyor, arama yoksa o konular elenir.

Sonda "ONERI" satiri: pipeline zaten kosunun basinda ayni yoklamayi yapip ilk
saglikli modeli seciyor; bu arac sadece goz ile gormen icin.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editorial.llm import (BASE, LAST_RESORT, Gemini, gist,       # noqa: E402
                           quota_hint, rank_models)


def measure(key: str, model: str, grounded: bool = False, timeout: float = 25):
    """{'model','ok','secs','why'}"""
    g = Gemini(key, min_interval=0, log=lambda m: None)
    st, out, secs = g.probe(model, grounded=grounded, timeout=timeout)
    why = ""
    if st != 200:
        kind = quota_hint(out)[0] if st == 429 else ""
        msg = gist((out.get("error") or {}).get("message", ""), 110)
        why = f"{st} {kind}: {msg}".replace(" :", ":").strip()
    return {"model": model, "ok": st == 200, "secs": round(secs, 1), "why": why}


def recommend(rows: list[dict]) -> tuple[str | None, str]:
    """(model, aciklama). rows siralamasi = pipeline'in deneme sirasi.
    Ilk saglikli model pipeline'in zaten sececegi modeldir."""
    healthy = [r for r in rows if r["plain"]["ok"]]
    if not healthy:
        return None, "HICBIR model cevap vermedi. Anahtar gecersiz, kota yok " \
                     "ya da Gemini genel olarak kesintide."
    first = healthy[0]
    if first["grounded"] is not None and not first["grounded"]["ok"]:
        with_search = [r for r in healthy if r["grounded"] and r["grounded"]["ok"]]
        if with_search:
            return with_search[0]["model"], (
                f"{first['model']} calisiyor ama arama destegi yok; hikaye/"
                f"gundem icin aramasi olan {with_search[0]['model']} daha iyi. "
                f"Sabitlemek icin GEMINI_MODEL={with_search[0]['model']}")
        return first["model"], (
            f"{first['model']} calisiyor ama hicbir modelde arama yok: yalniz "
            "formullu (measured) konular yayina girer")
    return first["model"], (f"{first['model']} calisiyor; pipeline zaten bunu "
                            "secer, bir sey yapmana gerek yok")


def render(rows: list[dict]) -> str:
    lines = ["| model | cevap | sn | arama | not |", "|---|---|---|---|---|"]
    for r in rows:
        p, g = r["plain"], r["grounded"]
        gtxt = "-" if g is None else ("var" if g["ok"] else "YOK")
        note = p["why"] or ("" if g is None or g["ok"] else g["why"])
        lines.append(f"| {r['model']} | {'evet' if p['ok'] else 'HAYIR'} | "
                     f"{p['secs']} | {gtxt} | {note[:120]} |")
    return "\n".join(lines)


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY yok", file=sys.stderr)
        return 2
    g = Gemini(key, min_interval=0, log=lambda m: None)
    st, out = g.transport("GET", f"{BASE}/models?pageSize=200", key, timeout=30)
    if st != 200:
        msg = gist((out.get("error") or {}).get("message", ""))
        print(f"model listesi alinamadi: HTTP {st} {msg}", file=sys.stderr)
        return 1
    names = list(dict.fromkeys(rank_models(out.get("models", []))[:10]
                               + list(LAST_RESORT)))
    print(f"{len(names)} aday model olculuyor...", flush=True)

    with ThreadPoolExecutor(max_workers=4) as ex:
        plain = list(ex.map(lambda n: measure(key, n), names))
    rows = []
    for p in plain:
        gr = measure(key, p["model"], grounded=True) if p["ok"] else None
        rows.append({"model": p["model"], "plain": p, "grounded": gr})

    table = render(rows)
    best, why = recommend(rows)
    print("\n" + table + f"\n\nONERI: {why}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("## Gemini model yoklamasi\n\n" + table + f"\n\n**ONERI:** {why}\n")
    return 0 if best else 1


if __name__ == "__main__":
    sys.exit(main())
