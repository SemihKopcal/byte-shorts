"""
Editorial hat: konu -> taslak -> editor dongusu -> dogrulama -> tema -> metin.

    python -m editorial                       # Gemini konuyu kendi secer
    python -m editorial --topic "..."         # konuyu sen veriyorsun
    python -m editorial --dry-run             # dosya yazmadan dene

Akis
  1. yapimci    4 aday uretir, kod eler ve siralar (olculebilirlik/guvenlik >= 7)
  2. yazar      senaryoyu yazar; kural dogrulamasi gecene kadar 3 deneme
  3. editor     yargilar; kod sayi iddialarini HESAPLAR; arama destekli
                dogrulayici formulsuz rakamlari kontrol eder
                -> publish | revise (en fazla 2 tur) | reject
  4. sanat yon. temayi secer
  5. metin yaz. baslik alternatifleri + platform basina metin; kod dogrular
  6. content/scripts/<id>.json  (reddedilenler content/rejected/ altina)

Her adimda Gemini cevap vermezse bir yedek var; yedegi de yoksa hat YUKSEK
SESLE durur. Kotu bir videoyu sessizce yayinlamaktansa "bugun video yok".
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editorial import roles, rules, signals          # noqa: E402
from editorial.llm import Gemini                      # noqa: E402
from publish import manifest as M                     # noqa: E402

MIN_SCORE = int(os.environ.get("MIN_SCORE", "7"))
MAX_REVISIONS = 2
MAX_CANDIDATES = 3
ALLOW_UNVERIFIED = 1       # aramayla dogrulanamayan en fazla bir rakam


class Failure(Exception):
    """Hat bugun video uretemedi. Mesaj Actions logunda gorunuyor."""


# ── yardimcilar ──────────────────────────────────────────────────────────
def _read(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _scripts(root: Path) -> list[dict]:
    d = root / "content/scripts"
    return [_read(f, {}) for f in sorted(d.glob("*.json"))] if d.exists() else []


def recent_titles(root: Path, n: int = 30) -> list[str]:
    """Yayinlananlar + uretilenler. Yukleme kapaliyken de tekrar etmesin."""
    titles = [x.get("title", "") for x in _read(root / "content/published.json", [])]
    titles += [s.get("title", "") for s in _scripts(root)]
    return [t for t in dict.fromkeys(titles) if t][-n:]


def recent_themes(root: Path, n: int = 3) -> list[str]:
    out = [x.get("theme", "") for x in _read(root / "content/published.json", [])]
    out += [s.get("theme", "") for s in _scripts(root)]
    return [t for t in out if t][-n:]


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:52] or "untitled"


def _title_words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def similar_title(title: str, recent: list[str]) -> str | None:
    tw = _title_words(title)
    for old in recent:
        ow = _title_words(old)
        if tw and ow and len(tw & ow) / len(tw | ow) > 0.6:
            return old
    return None


def backlog_candidates(root: Path, recent: list[str], today: str) -> list[dict]:
    """Yedek havuzdan, basliklarda gecmeyen konular. Gunun sirasina gore
    donuyor: ayni gun ayni sonuc, ertesi gun bir sonraki."""
    topics = _read(root / "content/backlog.json", {}).get("topics", [])
    if not topics:
        return []
    seen = " ".join(recent).lower()
    fresh = [t for t in topics
             if not any(w in seen for w in
                        re.findall(r"[a-z]{7,}", t["angle"].lower()))]
    pool = fresh or topics
    k = dt.date.fromisoformat(today).toordinal() % len(pool)
    pool = pool[k:] + pool[:k]
    return [{"angle": t["angle"], "measure": t["measure"], "calc": "",
             "sources": t.get("sources", []), "signal_url": None}
            for t in pool]


# ── bir konuyu olgunlastir ───────────────────────────────────────────────
def develop(llm, brief: dict, scene_names, recent: list[str], log=print,
            min_score: int = MIN_SCORE, max_revisions: int = MAX_REVISIONS):
    """(spec, bilgi). Basarisizsa spec None; bilgi['stage'] nerede takildigini
    soyluyor. stage == 'llm' ise Gemini hic cevap vermiyor: diger konulari
    denemenin anlami yok."""
    max_words = int(rules.MAX_SECONDS * rules.WORDS_PER_SEC * 0.92)

    # 1. taslak: kural dogrulamasi gecene kadar
    spec, problems, nones = None, [], 0
    for attempt in range(1, 4):
        spec = roles.write(llm, brief, max_words=max_words,
                           problems=problems or None)
        if spec is None:
            nones += 1
            if nones >= 2:
                return None, {"stage": "llm", "problems": ["Gemini cevap vermedi"]}
            problems = ["reply with one valid JSON object"]
            continue
        problems = _draft_problems(spec, scene_names, recent)
        if not problems:
            break
        log(f"  taslak {attempt} reddedildi:\n    " + "\n    ".join(problems))
    else:
        return None, {"stage": "draft", "problems": problems, "spec": spec}

    # 2. editor dongusu
    d, unverified, grounded = None, 0, False
    for rnd in range(max_revisions + 1):
        review = roles.edit(llm, spec)
        claim_problems, lookups = rules.check_claims(
            spec, review["claims"], len(spec["sources"]))
        fact_problems, unverified, grounded = roles.factcheck(llm, spec, lookups)
        extra = claim_problems + fact_problems
        if unverified > ALLOW_UNVERIFIED:
            extra.append(
                f"{unverified} figures could not be verified online. Replace "
                "them with arithmetic you can show, or with figures from the "
                "listed sources, or remove them")
        d = rules.decide(review, extra, min_score)
        log(f"  editor tur {rnd}: {d.verdict}  ort {d.mean:.1f}  "
            + " ".join(f"{k}={v}" for k, v in d.scores.items())
            + f"  risk={d.risk}")
        if d.verdict == "publish":
            break
        if d.verdict == "reject" or rnd == max_revisions:
            return None, {"stage": "editor", "problems": d.fixes, "spec": spec,
                          "scores": d.scores}
        log("  duzeltmeler:\n    " + "\n    ".join(d.fixes[:8]))
        new = roles.write(llm, brief, max_words=max_words,
                          problems=d.fixes, previous=spec)
        for _ in range(2):                       # bozduysa bir kez daha
            if new is None:
                return None, {"stage": "llm",
                              "problems": ["duzeltme cevabi gelmedi"]}
            problems = _draft_problems(new, scene_names, recent)
            if not problems:
                break
            log("  duzeltme gecersiz:\n    " + "\n    ".join(problems))
            new = roles.write(llm, brief, max_words=max_words,
                              problems=problems, previous=new)
        else:
            return None, {"stage": "revise", "problems": problems, "spec": new}
        spec = new

    spec["review"] = {
        "verdict": "publish", "scores": d.scores, "mean": round(d.mean, 1),
        "risk": d.risk, "rounds": rnd, "grounded": grounded,
        "unverified": unverified, "model": llm.model,
    }
    return spec, {"stage": "ok"}


def _draft_problems(spec: dict, scene_names, recent: list[str]) -> list[str]:
    p = rules.validate_script(spec, scene_names)
    if not p:
        title = spec["title"]
        if len(title) > 60:
            p.append(f"title is {len(title)} characters; max 60")
        old = similar_title(title, recent)
        if old:
            p.append(f"title too close to an earlier video: {old!r}")
    return p


# ── yayin metni ──────────────────────────────────────────────────────────
def make_copy(llm, spec: dict, brand: dict, recent: list[str],
              log=print) -> dict:
    """Gemini'nin metnini kod kuruyor ve dogruluyor. Gemini yoksa ya da metin
    kurallara uymuyorsa sablona dusuyor: metin yuzunden video durmuyor."""
    parts = roles.copywrite(llm, spec)
    if parts:
        for title in list(parts.get("titles", [])) + [spec["title"]]:
            if similar_title(title, recent) is not None:
                continue
            c = M.compose(brand, spec, {**parts, "title": title,
                                        "alt_titles": parts.get("titles", [])})
            bad = M.validate_copy(c, brand)
            if not bad:
                return c
            log(f"  metin reddedildi ({title[:40]!r}): {'; '.join(bad[:3])}")
    else:
        log("  metin yazari cevap vermedi")
    log("  sablon metne dusuldu")
    return M.compose(brand, spec, None)


# ── ana akis ─────────────────────────────────────────────────────────────
def run(llm, *, root: Path = ROOT, today: str | None = None,
        topic: str | None = None, scene_names, theme_names,
        live: str | None = None, write: bool = True, log=print) -> dict:
    today = today or dt.date.today().isoformat()
    recent = recent_titles(root)
    brand = M.load_brand(root)
    backlog = _read(root / "content/backlog.json", {}).get("topics", [])

    # 1. adaylar
    if topic:
        cands = [{"angle": topic, "calc": "", "signal_url": None, "sources": [],
                  "measure": "whatever the topic needs, from arithmetic or "
                             "published pages"}]
        log(f"konu verildi: {topic[:90]}")
    else:
        if live is None:
            log("canli sinyal toplaniyor...")
            live = signals.as_prompt(signals.collect())
        cands = roles.produce(llm, live=live, backlog=backlog, recent=recent,
                              today=today)
        log(f"yapimci {len(cands)} uygun aday verdi")
        if not cands:
            log("-> yedek havuza dusuluyor")
            cands = backlog_candidates(root, recent, today)
    if not cands:
        raise Failure("konu adayi yok: yapimci bos dondu, yedek havuz da bos")

    # 2-3. olgunlastir; ilk onaylanan kazanir
    rejected: list[dict] = []
    spec, brief = None, None
    for n, brief in enumerate(cands[:MAX_CANDIDATES], 1):
        log(f"\nkonu {n}/{min(len(cands), MAX_CANDIDATES)}: {brief['angle'][:100]}")
        spec, info = develop(llm, brief, scene_names, recent, log)
        if spec:
            break
        rejected.append({"brief": brief, **info})
        if info["stage"] == "llm":
            break
    if spec is None:
        _save_rejected(root, today, rejected, write)
        why = rejected[-1]
        raise Failure(f"{len(rejected)} konu denendi, hicbiri yayina uygun "
                      f"cikmadi (son: {why['stage']}): "
                      + "; ".join(why["problems"][:3]))

    # 4. tema
    theme = roles.art_direct(llm, spec, recent_themes(root), theme_names)
    if theme:
        spec["theme"] = theme
        log(f"  tema: {theme}")

    # 5. metin
    copy = make_copy(llm, spec, brand, recent, log)
    spec["title"] = copy["title"]
    spec["copy"] = copy
    spec.setdefault("summary", copy["title"])
    spec["brief"] = {k: brief.get(k) for k in
                     ("angle", "signal_url", "why_now") if brief.get(k)}

    spec = {**spec, "id": _unique_id(root, today, spec["title"]),
            "series": "G", "lang": "en", "generated_by": llm.model,
            "generated_at": today}

    # 6. yaz
    if write:
        out = root / "content/scripts" / f"{spec['id']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(spec, indent=1, ensure_ascii=False))
        log(f"\nyazildi: {out.relative_to(root)}")
    return spec


def _unique_id(root: Path, today: str, title: str) -> str:
    base = f"{today}-{_slug(title)}"
    d, n, sid = root / "content/scripts", 1, base
    while (d / f"{sid}.json").exists():
        n += 1
        sid = f"{base}-{n}"
    return sid


def _save_rejected(root: Path, today: str, items: list[dict], write: bool):
    """Reddedilenler git gecmisinde kalsin: 'Gemini bugun neden video
    uretmedi' sorusunun cevabi dosyada."""
    if not write:
        return
    d = root / "content/rejected"
    d.mkdir(parents=True, exist_ok=True)
    for i, it in enumerate(items, 1):
        slug = _slug(it["brief"]["angle"])[:40]
        (d / f"{today}-{i}-{slug}.json").write_text(
            json.dumps(it, indent=1, ensure_ascii=False, default=str))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1].strip())
    ap.add_argument("--topic", default="", help="konuyu sen ver")
    ap.add_argument("--dry-run", action="store_true",
                    help="dosya yazma, sadece sonucu goster")
    a = ap.parse_args(argv)

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        sys.exit("GEMINI_API_KEY yok")

    from worker.scenes import NAMES                       # noqa: E402
    from worker.themes import NAMES as THEMES             # noqa: E402

    llm = Gemini(key)
    topic = (a.topic or os.environ.get("TOPIC", "")).strip() or None
    try:
        spec = run(llm, topic=topic, scene_names=NAMES, theme_names=THEMES,
                   write=not a.dry_run)
    except Failure as e:
        print(f"\nBUGUN VIDEO YOK: {e}", file=sys.stderr)
        sys.exit(1)

    r = spec["review"]
    print(f"\n  baslik : {spec['title']}")
    print(f"  model  : {llm.model} ({llm.calls} cagri)")
    print(f"  editor : ort {r['mean']}  {r['scores']}  tur={r['rounds']}")
    print(f"  alt    : {', '.join(spec['copy']['alt_titles'][:3])}")


if __name__ == "__main__":
    main()
