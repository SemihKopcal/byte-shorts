#!/usr/bin/env python3
"""
A/B raporu: hangi videolar ne kadar tutuyor?

YouTube Studio'dan indirdigin tabloyu (CSV) senaryolarla birlestirir:
  * her senaryonun ozellikleri (sure tahmini, tema, sahne dizisi, beat sayisi)
  * content/experiments.json'daki deneyler: kol A'ya karsi kol B

Kullanim (Studio: Analytics > Advanced mode > Content > ust sagdaki "Export current
view" > Download .csv; tarih araligini deneyin baslangicindan bugune ayarla):

    python tools/ab_report.py studio.csv
    python tools/ab_report.py studio.csv --exp e1-length --md rapor.md
    python tools/ab_report.py --status            # hangi video uretildi/yayinlandi

Video <-> senaryo eslestirmesi: once YouTube kimligi (content/published.json ya da
--map dosyasi {"p031-...": "abc123..."}), bulunamazsa baslik. Panel modunda
published.json guncellenmez; o zaman ya --map ya da basliga guven.

DURUST NOT: kol basina 6-8 video ile yalniz BUYUK farklar ayirt edilir. Rapor kucuk
farklari "belirsiz" diye yazar; bunu yanlis okuma. Ayrica Shorts'ta "ortalama
izlenme yuzdesi" kisa videolarda kendiliginden yuksek cikar (ve donguyle %100'u
asabilir); sure deneyinde ana olcut "izlemeye devam" ve izlenme sayisidir.
"""
import argparse
import csv
import itertools
import json
import random
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editorial.rules import GAP, WORDS_PER_SEC            # noqa: E402

SCRIPTS = ROOT / "content" / "scripts"
PUBLISHED = ROOT / "content" / "published.json"
BUILT = ROOT / "content" / "built.json"
EXPERIMENTS = ROOT / "content" / "experiments.json"

METRICS = ("views", "stayed", "avg_pct", "avg_dur", "likes", "subs")
LABELS = {"views": "izlenme", "stayed": "izlemeye devam %", "avg_pct": "ort. izlenme %",
          "avg_dur": "ort. sure (sn)", "likes": "begeni", "subs": "abone"}

_TR = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosucgiosuaiu")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").translate(_TR).lower()).strip()


# ── CSV ────────────────────────────────────────────────────────────────────
def classify(header: str):
    """Studio sutun adi -> ic ad. Ingilizce ve Turkce arayuz."""
    h = norm(header)
    if not h:
        return None
    if h in ("content", "video id", "video", "id", "icerik", "video kimligi"):
        return "id"
    if h in ("video title", "title", "video basligi", "baslik"):
        return "title"
    if "average percentage" in h or ("ortalama" in h and "yuzde" in h):
        return "avg_pct"
    if "average view duration" in h or ("ortalama" in h and "sure" in h):
        return "avg_dur"
    if "stayed" in h or "swiped" in h or "kaydir" in h or "izlemeye devam" in h:
        return "stayed"
    if h in ("views", "goruntuleme", "goruntulenme", "izlenme"):
        return "views"
    if h in ("likes", "begeni", "begenme"):
        return "likes"
    if h in ("subscribers", "abone", "aboneler", "abone sayisi"):
        return "subs"
    return None


def parse_num(s):
    s = (s or "").strip().replace("%", "").replace(" ", "").replace(" ", "")
    if not s or s in ("-", "--"):
        return None
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_dur(s):
    s = (s or "").strip()
    if ":" in s:
        try:
            parts = [float(x) for x in s.split(":")]
        except ValueError:
            return None
        sec = 0.0
        for p in parts:
            sec = sec * 60 + p
        return sec
    return parse_num(s)


def read_studio(paths, overrides=None):
    """[{id, title, views, stayed, avg_pct, avg_dur, ...}] (Toplam satiri atilir)."""
    rows = []
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rd = csv.reader(fh, dialect)
            head = next(rd, [])
            cols = {}
            for i, h in enumerate(head):
                key = (overrides or {}).get(h) or classify(h)
                if key and key not in cols:
                    cols[key] = i
            if "id" not in cols and "title" not in cols:
                raise SystemExit(f"{path}: video kimligi ya da baslik sutunu bulunamadi "
                                 f"(basliklar: {head}); --col id=<sutun adi> ver")
            for r in rd:
                if not any(c.strip() for c in r):
                    continue
                rec = {}
                for k, i in cols.items():
                    v = r[i] if i < len(r) else ""
                    rec[k] = (v.strip() if k in ("id", "title")
                              else parse_dur(v) if k == "avg_dur" else parse_num(v))
                if norm(rec.get("id", "")) in ("total", "toplam") or \
                        norm(rec.get("title", "")) in ("total", "toplam"):
                    continue
                rows.append(rec)
    return rows


# ── senaryolar ─────────────────────────────────────────────────────────────
def load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def script_info(f: Path) -> dict:
    d = json.loads(f.read_text())
    beats = d.get("beats") or []
    words = sum(len((b.get("say") or "").split()) for b in beats if isinstance(b, dict))
    scenes = [b.get("scene") for b in beats if isinstance(b, dict) and b.get("scene")]
    est = words / WORDS_PER_SEC + GAP * max(len(beats) - 1, 0)
    hook = (beats[0].get("say") or "") if beats and isinstance(beats[0], dict) else ""
    return {"id": d["id"], "file": f.name, "title": d.get("title", ""),
            "series": d.get("series", ""), "format": d.get("format", ""),
            "theme": d.get("theme", ""), "beats": len(beats), "words": words,
            "est": est, "scenes": scenes, "first": scenes[0] if scenes else "",
            "hook_words": len(hook.split())}


def all_scripts(scripts_dir: Path = None) -> dict:
    out = {}
    for f in sorted((scripts_dir or SCRIPTS).glob("*.json")):
        try:
            info = script_info(f)
        except (ValueError, KeyError):
            continue
        out[info["id"]] = info
    return out


def youtube_ids(published, extra) -> dict:
    ids = {}
    for e in published or []:
        if isinstance(e, dict) and e.get("id") and e.get("youtube_id"):
            ids[e["id"]] = e["youtube_id"]
    ids.update({k: v for k, v in (extra or {}).items() if isinstance(v, str) and v})
    return ids


def title_key(t: str) -> str:
    return norm(re.sub(r"#\w+", "", t or ""))


def match(scripts: dict, studio: list, ids: dict) -> dict:
    """script_id -> Studio satiri (kimlikle, yoksa baslikla)."""
    by_id = {r["id"]: r for r in studio if r.get("id")}
    by_title = {}
    for r in studio:
        k = title_key(r.get("title", ""))
        if k:
            by_title.setdefault(k, r)
    out = {}
    for sid, info in scripts.items():
        r = by_id.get(ids.get(sid, ""))
        if r is None:
            k = title_key(info["title"])
            r = by_title.get(k)
            if r is None and len(k) >= 12:
                for tk, cand in by_title.items():
                    if tk.startswith(k) or k.startswith(tk):
                        r = cand
                        break
        if r is not None:
            out[sid] = r
    return out


# ── istatistik ─────────────────────────────────────────────────────────────
def med(xs):
    return statistics.median(xs) if xs else None


def perm_p(a, b, seed=7, cap=20000):
    """Iki yonlu permutasyon testi, siralama (Mann-Whitney) istatistigiyle: aykiri
    degerlere (bir video viral olursa) dayanikli, kucuk n'de KESIN."""
    if not a or not b:
        return None
    pool = list(a) + list(b)
    n, big = len(a), len(pool)
    order = sorted(range(big), key=lambda i: pool[i])
    rank = [0.0] * big
    i = 0
    while i < big:                       # esit degerlere ortalama sira
        j = i
        while j + 1 < big and pool[order[j + 1]] == pool[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rank[order[k]] = (i + j) / 2 + 1
        i = j + 1
    mid = n * (big + 1) / 2
    obs = abs(sum(rank[:n]) - mid)
    total = 1
    for k in range(n):
        total = total * (big - k) // (k + 1)
    if total <= cap:
        combos = itertools.combinations(range(big), n)
    else:
        rng = random.Random(seed)
        combos = (tuple(rng.sample(range(big), n)) for _ in range(cap))
    hit = cnt = 0
    for idx in combos:
        cnt += 1
        if abs(sum(rank[k] for k in idx) - mid) >= obs - 1e-9:
            hit += 1
    return hit / cnt


def verdict(p, na, nb, need):
    if na < need or nb < need:
        return f"yetersiz veri (kol basina en az {need} video lazim)"
    if p is None:
        return "hesaplanamadi"
    if p < 0.05:
        return "belirgin fark"
    if p < 0.15:
        return "isaret var ama kesin degil"
    return "fark ayirt edilemiyor"


def fmt(x, nd=1):
    return "-" if x is None else (f"{x:.{nd}f}" if abs(x) < 1000 else f"{x:,.0f}")


# ── rapor ──────────────────────────────────────────────────────────────────
def experiment_report(name, exp, scripts, matched) -> list:
    out = [f"## {name}: {exp.get('title', '')}"]
    if exp.get("hypothesis"):
        out.append(f"Soru: {exp['hypothesis']}")
    arms = exp.get("arms", {})
    primary = exp.get("primary", "views")
    need = int(exp.get("min_per_arm", 6))
    vals = {}
    for arm, ids in arms.items():
        vals[arm] = {m: [] for m in METRICS}
        for sid in ids:
            r = matched.get(sid)
            if r is None:
                continue
            for m in METRICS:
                v = r.get(m)
                if v is not None:
                    vals[arm][m].append(v)
        n = sum(1 for sid in ids if sid in matched)
        out.append(f"- kol {arm}: {len(ids)} video planli, {n} tanesinin verisi var")
    out.append("")
    out.append("| olcut | " + " | ".join(f"{a} (medyan)" for a in arms) + " | p | yorum |")
    out.append("|---|" + "---|" * (len(arms) + 2))
    names = list(arms)
    for m in METRICS:
        if not any(vals[a][m] for a in names):
            continue
        meds = [med(vals[a][m]) for a in names]
        p = res = None
        if len(names) == 2:
            a, b = (vals[names[0]][m], vals[names[1]][m])
            p = perm_p(a, b)
            res = verdict(p, len(a), len(b), need)
        star = " (ana olcut)" if m == primary else ""
        out.append(f"| {LABELS[m]}{star} | " + " | ".join(fmt(x) for x in meds) +
                   f" | {fmt(p, 2)} | {res or ''} |")
    note = exp.get("note")
    if note:
        out += ["", f"Not: {note}"]
    return out


def attribute_report(scripts, matched) -> list:
    rows = [(scripts[sid], r) for sid, r in matched.items() if sid in scripts]
    out = ["## Ne tutuyor? (ozelliklere gore, tum videolar)", ""]
    if len(rows) < 4:
        return out + ["Henuz yeterli veri yok (en az 4 video)."]

    def bucket_len(i):
        return "<28 sn" if i["est"] < 28 else "28-36 sn" if i["est"] < 36 else ">=36 sn"

    groups = {"sure": bucket_len, "tema": lambda i: i["theme"] or "-",
              "ilk sahne": lambda i: i["first"] or "-",
              "bicim": lambda i: i["format"] or "-"}
    key_metric = "stayed" if any(r.get("stayed") is not None for _, r in rows) else "views"
    for gname, fn in groups.items():
        by = {}
        for i, r in rows:
            by.setdefault(fn(i), []).append(r)
        multi = {k: v for k, v in by.items() if len(v) >= 2}
        if len(multi) < 2:
            continue
        out.append(f"### {gname}")
        out.append("| grup | video | medyan izlenme | medyan " + LABELS[key_metric] + " |")
        out.append("|---|---|---|---|")
        for k, v in sorted(multi.items()):
            views = [x["views"] for x in v if x.get("views") is not None]
            km = [x[key_metric] for x in v if x.get(key_metric) is not None]
            out.append(f"| {k} | {len(v)} | {fmt(med(views), 0)} | {fmt(med(km))} |")
        out.append("")
    # sahne turu: o sahneyi iceren / icermeyen
    kinds = sorted({s for i, _ in rows for s in i["scenes"]})
    lines = []
    for s in kinds:
        have = [r for i, r in rows if s in i["scenes"]]
        miss = [r for i, r in rows if s not in i["scenes"]]
        if len(have) >= 3 and len(miss) >= 3:
            a = [x[key_metric] for x in have if x.get(key_metric) is not None]
            b = [x[key_metric] for x in miss if x.get(key_metric) is not None]
            if a and b:
                lines.append(f"| {s} | {len(have)} | {fmt(med(a))} | {len(miss)} | {fmt(med(b))} |")
    if lines:
        out += ["### sahne turu (var / yok)",
                f"| sahne | var (n) | medyan {LABELS[key_metric]} | yok (n) | medyan |",
                "|---|---|---|---|---|"] + lines + [""]
    out.append("Tek bir ozellige bakarak karar verme: konu, yayin saati ve sans da "
               "sonucu etkiler. Bunlar ipucu, kanit degil.")
    return out


def status_report(scripts, ids, built, exps) -> list:
    out = ["## Durum", "", "| deney | kol | senaryo | uretildi | YouTube |", "|---|---|---|---|---|"]
    for name, exp in exps.items():
        for arm, lst in exp.get("arms", {}).items():
            for sid in lst:
                out.append(f"| {name} | {arm} | {sid}"
                           f"{'' if sid in scripts else ' (DOSYA YOK)'} | "
                           f"{'evet' if sid in built else 'hayir'} | {ids.get(sid, '-')} |")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="*", help="YouTube Studio'dan indirilen CSV(ler)")
    ap.add_argument("--exp", default="", help="yalniz bu deney (bos = hepsi)")
    ap.add_argument("--map", default="", help='{"senaryo-id": "youtube-id"} JSON dosyasi')
    ap.add_argument("--col", action="append", default=[],
                    help="sutun adi eslestir: ic_ad=Studio_sutun_adi (views, avg_pct, ...)")
    ap.add_argument("--md", default="", help="raporu bu dosyaya da yaz")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)

    scripts = all_scripts()
    exps = load_json(EXPERIMENTS, {})
    if a.exp:
        if a.exp not in exps:
            print(f"deney yok: {a.exp} (var olanlar: {', '.join(exps) or '-'})", file=sys.stderr)
            return 2
        exps = {a.exp: exps[a.exp]}
    extra = load_json(Path(a.map), {}) if a.map else {}
    ids = youtube_ids(load_json(PUBLISHED, []), extra)
    built = set(x["id"] if isinstance(x, dict) else x for x in load_json(BUILT, []))

    if a.status or not a.csv:
        text = "\n".join(status_report(scripts, ids, built, exps))
        print(text)
        if not a.csv:
            print("\nStudio CSV'si ver: python tools/ab_report.py studio.csv", file=sys.stderr)
            return 0

    over = {}
    for item in a.col:
        k, _, v = item.partition("=")
        if k not in METRICS + ("id", "title") or not v:
            print(f"--col {item!r}: ic_ad=Studio_sutunu bekleniyordu ({', '.join(METRICS)}, id, title)",
                  file=sys.stderr)
            return 2
        over[v] = k
    studio = read_studio(a.csv, over)
    matched = match(scripts, studio, ids)
    lines = [f"# A/B raporu", "",
             f"Studio satiri: {len(studio)}, senaryolarla eslesen: {len(matched)}", ""]
    unmatched = [r for r in studio if r not in matched.values()]
    if unmatched:
        lines.append("Eslesmeyen Studio satirlari (senaryo degil ya da kimlik/baslik farkli): "
                     + ", ".join((r.get("title") or r.get("id") or "?")[:40] for r in unmatched[:6])
                     + (" ..." if len(unmatched) > 6 else ""))
        lines.append("")
    for name, exp in exps.items():
        lines += experiment_report(name, exp, scripts, matched) + [""]
    lines += attribute_report(scripts, matched)
    text = "\n".join(lines)
    print(text)
    if a.md:
        Path(a.md).write_text(text + "\n")
        print(f"\nyazildi: {a.md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
