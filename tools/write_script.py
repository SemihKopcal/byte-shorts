#!/usr/bin/env python3
"""
Konu motoru: Gemini'ye bir senaryo yazdirir, dogrular, content/scripts'e koyar.

SINIRLAR -- bilerek dar tutuldu:
  * Gemini KOD yazmiyor. Sadece katalogdan sahne adi seciyor ve o sahnenin
    data'sini dolduruyor. Cizim tamamen worker/ altinda, degismiyor.
  * Urettigi her sey once dogrulamadan geciyor; sema bozuksa, sahne uydurmussa,
    kaynak yoksa ya da baslik oncekine benziyorsa dosya YAZILMIYOR.
  * Ciktinin kendisi repoya commit ediliyor -- kara kutu degil, git gecmisinden
    "o gun ne uretti" gorunuyor.

Neden bu kadar kisitli: dil modelleri sayi uydurur. Ekranda gorunen bir sayi
yanlissa kanalin tek savunmasi olan "olculmus veri" iddiasi coker.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trends                                          # noqa: E402
from worker.scenes import CATALOG                      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "content/scripts"
PUBLISHED = ROOT / "content/published.json"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
URL = (f"https://generativelanguage.googleapis.com/v1beta/models/"
       f"{MODEL}:generateContent")

WORDS_PER_SEC = 2.6        # Piper en-us-ryan-high, olculmus
GAP = 0.18
MAX_SECONDS = 52           # QC esigi 59; burada pay birakiyoruz

SCENE_DOC = """
title      buyuk baslik. data: {kicker?, lines:[1-3 kisa satir], accent?}
contrast   iki sayi yan yana, sagdaki vurgulu.
           data: {left:{label,value}, right:{label,value,tone?}, verdict?}
table      satir satir acilan tablo (en fazla 6 satir).
           data: {unit?, rows:[{name, value, ratio, tone?}]}
           ratio = gorsel cubuk uzunlugu icin sayisal oran
bars       buyuyen cubuklar (en fazla 5). data: {rows:[{name, v, label?, tone?}]}
counter    sayarak yukselen sayi.
           data: {prefix?, suffix?, from, to, dp?, threshold?, tone?, tone_over?, note?}
split      ekran ikiye bolunur. data: {a:{label,sub?,tone?}, b:{label,sub?,tone?}}
timeline   soldan saga adimlar (en fazla 5). data: {steps:[{at, label, tone?}]}
byte_says  BYTE buyuk, tek satir. data: {line?, pose?, cursor?}
           pose: idle|point_r|point_l|point_up|shrug|alert
           cursor: mint|amber|red|violet
close      kapanis karti. data: {lines:[1-2 satir], accent?, handle?}

tone degerleri: base (notr) | good (yesil) | mid (mor) | bad (amber/uyari)
"""

PROMPT = """You write scripts for BYTE, a faceless YouTube Shorts channel about
AI tools. BYTE is openly a machine: it measures things and reports numbers.
It never claims expertise, never gives advice, never pretends to be human.

Write ONE script as JSON. Rules, all of them hard:

LENGTH
- 12 to 16 beats. Total spoken words must be under {max_words}.
- Each beat is one short spoken sentence. No sentence over 14 words.

TWO TEXTS PER BEAT
- "say" is what the voice reads. Write numbers as words: "three dollars",
  "forty seven percent", "U T F eight". The synthesiser reads it literally.
- "cap" is what appears on screen. Use digits and symbols: "$3", "47%", "UTF-8".
- Never put a URL, a bracket or an emoji in either.

STRUCTURE
- Beat 1 must state a surprising, specific, verifiable fact. No question, no
  "did you know", no "imagine". The contradiction should be visible at once.
- Beats 2-4 give the mechanism: WHY the fact is true.
- Middle beats carry the measured data.
- One beat near the end must turn the expectation ("but X is the strange one").
- Last beat is a flat conclusion. No call to action, no "subscribe", no question.

SCENES — pick from this catalogue only. Never invent a scene name.
{scenes}
- Use AT LEAST 4 different scene types. A script that is all one scene is
  rejected.
- Put "data" only on the beat where the scene STARTS. Following beats with the
  same scene and no data keep that scene on screen.
- Open with "title" or "contrast". Close with "close".

NUMBERS
- Every number on screen must be one a reader could verify from the sources
  you list. Prefer arithmetic you can do yourself (ratios, byte counts, price
  per second x duration) over figures you half-remember.
- If you are not certain of a figure, change the topic rather than guess.
- "sources" must name real, checkable things: a document, a published price
  page, a measurement and its date. At least two.

FORBIDDEN TOPICS
- Health, finance, legal or political advice of any kind.
- Anything about a named living person.
- Anything you cannot source.

TITLE
- Under 60 characters. Plain statement. No ALL CAPS, no "shocking", no "!!!".

Topic area: AI tools — their price, their speed, their limits, how they
actually work, what they cost compared with each other.

WHAT IS BEING TALKED ABOUT RIGHT NOW
Pick your topic from this live list when one of them can be turned into a
measurement. Being current is worth a lot; being current AND measured is the
whole point of this channel. Everyone else explains the announcement; nobody
computes the bill.

{live}

If you use one of these, its URL goes in "sources" — the viewer must be able
to check where the topic came from. If none of them can be measured honestly,
ignore the list and pick an evergreen measurable topic instead.

Do NOT reuse or paraphrase any of these recent titles:
{recent}

Return ONLY this JSON object, no markdown fence, no commentary:

{{
 "title": "...",
 "summary": "one sentence for the description",
 "tags": ["3 to 6 lowercase tags"],
 "sources": ["...", "..."],
 "beats": [
   {{"id": "b1", "scene": "contrast", "say": "...", "cap": "...",
     "data": {{...}}}},
   {{"id": "b2", "say": "...", "cap": "..."}}
 ]
}}
"""


def _recent(n=25):
    if not PUBLISHED.exists():
        return []
    try:
        return [x.get("title", "") for x in json.loads(PUBLISHED.read_text())][-n:]
    except Exception:
        return []


def _call(prompt: str, key: str) -> str:
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 1.0,          # konu cesitliligi icin yuksek
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }).encode()
    req = urllib.request.Request(
        f"{URL}?key={key}", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Gemini HTTP {e.code}: {e.read().decode()[:400]}")
    try:
        return out["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        sys.exit("Gemini bos yanit verdi:\n" + json.dumps(out)[:600])


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:52] or "untitled"


def validate(spec: dict) -> list[str]:
    """Dosyaya yazmadan once. Bos liste = temiz."""
    p = []
    for k in ("title", "beats", "sources"):
        if not spec.get(k):
            p.append(f"eksik alan: {k}")
    if p:
        return p

    if len(spec["title"]) > 60:
        p.append(f"baslik {len(spec['title'])} karakter")
    if len(spec["sources"]) < 2:
        p.append("en az 2 kaynak gerekiyor")

    beats = spec["beats"]
    if not 10 <= len(beats) <= 18:
        p.append(f"{len(beats)} beat -- 10..18 arasi olmali")

    words = 0
    scenes = []
    for i, b in enumerate(beats):
        who = b.get("id", f"#{i}")
        if not b.get("say"):
            p.append(f"{who}: say yok")
            continue
        n = len(b["say"].split())
        words += n
        if n > 16:
            p.append(f"{who}: {n} kelime, cok uzun")
        if not b.get("cap"):
            p.append(f"{who}: cap yok")
        if re.search(r"https?://|[\[\]{}]", b.get("cap", "") + b["say"]):
            p.append(f"{who}: metinde URL/parantez var")
        s = b.get("scene")
        if s:
            if s not in CATALOG:
                p.append(f"{who}: bilinmeyen sahne {s!r}")
            scenes.append(s)

    if len(set(scenes)) < 4:
        p.append(f"{len(set(scenes))} farkli sahne -- en az 4 olmali")
    if scenes and scenes[-1] != "close":
        p.append("son sahne 'close' olmali")

    est = words / WORDS_PER_SEC + GAP * (len(beats) - 1)
    if est > MAX_SECONDS:
        p.append(f"tahmini sure {est:.0f}s > {MAX_SECONDS}s ({words} kelime)")

    ids = [b.get("id") for b in beats]
    if len(set(ids)) != len(ids):
        p.append("beat id'leri tekrar ediyor")
    return p


def main() -> None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY yok")

    recent = _recent()
    print("canli sinyal toplaniyor...")
    live = trends.as_prompt(trends.collect())
    prompt = PROMPT.format(
        scenes=SCENE_DOC,
        live=live,
        recent="\n".join(f"- {t}" for t in recent) or "- (none yet)",
        max_words=int(MAX_SECONDS * WORDS_PER_SEC * 0.92),
    )

    # Uc deneme: dogrulama hatalarini geri besleyerek. Dorduncude pes ediyoruz
    # -- bozuk bir senaryoyu zorla duzeltmeye calismak daha kotu metin uretiyor.
    attempt, problems = prompt, []
    for n in range(1, 4):
        raw = _call(attempt, key)
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError as e:
            problems = [f"gecersiz JSON: {e}"]
            attempt = prompt + f"\n\nYour last answer was not valid JSON: {e}"
            continue
        problems = validate(spec)
        if not problems:
            break
        print(f"deneme {n} reddedildi:", *problems, sep="\n  ")
        attempt = (prompt + "\n\nYour last answer was rejected for these "
                   "reasons. Fix them all:\n" +
                   "\n".join(f"- {x}" for x in problems))
    else:
        sys.exit("3 denemede gecerli senaryo cikmadi:\n  " +
                 "\n  ".join(problems))

    today = dt.date.today().isoformat()
    # ** once: id/series bizim, Gemini bunlari ezemesin
    spec = {
        **spec,
        "id": f"{today}-{_slug(spec['title'])}",
        "series": "G",
        "lang": "en",
        "generated_by": MODEL,
        "generated_at": today,
    }
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    out = SCRIPTS / f"{spec['id']}.json"
    out.write_text(json.dumps(spec, indent=1, ensure_ascii=False))
    print(f"yazildi: {out.relative_to(ROOT)}")
    print(f"  baslik: {spec['title']}")
    print(f"  sahneler: {', '.join(dict.fromkeys(b.get('scene','') for b in spec['beats'] if b.get('scene')))}")


if __name__ == "__main__":
    main()
