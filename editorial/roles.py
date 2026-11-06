"""
Gemini'nin rolleri. Bes ayri is, bes ayri istem, hepsi ayni sozlesme:
girdi al, JSON dondur, hata olursa None dondur (cagiran yedege dusuyor).

  yapimci       4 konu adayi onerir, kendi puanlar (arama destekli)
  yazar         secilen konudan senaryo yazar / editorun notlariyla yeniden yazar
  editor        senaryoyu yargilar, sayi iddialarini formule doker
  dogrulayici   formulsuz rakamlari canli aramayla kontrol eder
  sanat yon.    video icin temayi secer
  metin yazari  baslik alternatifleri + platform basina metin

Gemini KOD yazmiyor ve sahne UYDURMUYOR: katalogdan secip data dolduruyor.
Gorsel dil boylece binlerce videoda ayni kaliyor.

Rolleri AYRI cagrilara bolmenin sebebi: ayni cagri hem yazip hem "iyi mi?"
diye sorulursa model kendi cumlesini savunuyor. Editor ayri bir sistem
istemiyle, dusuk sicaklikla ve metni ilk kez gorur gibi okuyor.
"""
import json
import re

from . import rules

SYSTEM = """You work for BYTE, a faceless short-video channel (YouTube Shorts,
Instagram Reels, TikTok) for people aged 10 to 30. BYTE is openly a machine: a
CRT-headed robot whose only expression is a cursor. It measures things about
AI tools and reports numbers. It never claims expertise, never gives advice,
never pretends to be human, never sells anything.

Voice: dry, exact, a little deadpan. Short sentences. Concrete comparisons the
audience can feel (a coffee, a month of streaming, a phone battery) instead of
abstractions. No hype words. No questions to the viewer. No calls to action."""

SCENE_DOC = """
title      big headline. data: {kicker?, lines:[1-3 short lines], accent?}
contrast   two numbers side by side, the right one emphasised.
           data: {left:{label,value}, right:{label,value,tone?}, verdict?}
table      rows that reveal one by one (max 6).
           data: {unit?, rows:[{name, value, ratio, tone?}]}
           ratio = a number; it sets the visual bar length
bars       growing bars (max 5). data: {rows:[{name, v, label?, tone?}]}
counter    a number counting up.
           data: {prefix?, suffix?, from, to, dp?, threshold?, tone?, tone_over?, note?}
split      screen divides in two. data: {a:{label,sub?,tone?}, b:{label,sub?,tone?}}
timeline   steps left to right (max 5). data: {steps:[{at, label, tone?}]}
byte_says  BYTE large, one line. data: {line?, pose?, cursor?}
           pose: idle|point_r|point_l|point_up|shrug|alert
           cursor: mint|amber|red|violet
close      closing card. data: {lines:[1-2 short lines], accent?}
           (never put a handle in it; the pipeline adds the real one)

tone values: base (neutral) | good (green) | mid (purple) | bad (amber/warning)
"""

THEME_DOC = {
    "midnight": "default, purple-black. neutral topics",
    "ember": "warm red. prices, costs, bills",
    "deep": "deep blue. speed, latency, performance",
    "moss": "green-grey. efficiency, memory, energy",
    "slate": "neutral grey. head-to-head comparisons",
    "plum": "violet. surprising, myth-busting, the twist",
    "rust": "orange-brown. limits, quotas, failures",
    "ice": "cyan. measurements, tokens, data-heavy",
}


def _j(o) -> str:
    return json.dumps(o, ensure_ascii=False, indent=1)


# ═══ 1. YAPIMCI ═════════════════════════════════════════════════════════
PRODUCER = """Today is {today}. Propose exactly 4 candidate topics for the next
BYTE video.

A good topic has ALL of these:
 1. A measurable claim. The numbers come from arithmetic you can do, or from a
    published page a viewer can open. No vibes, no rankings of opinion.
 2. A visible contradiction in the first sentence: what people expect against
    what the measurement shows.
 3. Something a 10 to 30 year old cares about this week.
 4. An angle that differs from the recent titles below.

WHAT IS BEING TALKED ABOUT RIGHT NOW
{live}

EVERGREEN IDEAS (use one only if no live signal can be measured honestly)
{backlog}

RECENT TITLES - do not repeat or paraphrase
{recent}

Rules: no health, finance, legal or political advice; nothing about a named
living person; nothing you cannot source. When you use a live signal put its
URL in "signal_url". Search the web first to confirm that news is real and
recent. Everyone else explains the announcement; BYTE computes the bill.

Score each candidate honestly from 1 to 10. A 9 or 10 is rare. Reply with
JSON only:
{{"candidates": [{{
  "angle": "one sentence: the surprising fact",
  "measure": "what exactly is measured, and how",
  "calc": "the arithmetic or lookup, in one line",
  "sources": ["published page or document", "second one"],
  "signal_url": "url or null",
  "why_now": "one short line",
  "scores": {{"timeliness": 0, "measurability": 0, "curiosity": 0,
             "audience_fit": 0, "safety": 0}}
}}]}}"""


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def produce(llm, *, live: str, backlog: list[dict], recent: list[str],
            today: str) -> list[dict]:
    """Siralanmis aday listesi (en iyi basta). Gemini calismazsa bos liste."""
    prompt = PRODUCER.format(
        today=today, live=live,
        backlog="\n".join(f"- {b['angle']}  [measure: {b['measure']}]"
                          for b in backlog[:6]) or "(none)",
        recent="\n".join(f"- {t}" for t in recent) or "- (none yet)")
    raw = llm.ask_json(prompt, system=SYSTEM, temperature=1.0, grounded=True,
                       role="yapimci")
    cands = raw.get("candidates") if isinstance(raw, dict) else None
    return rank(cands or [], recent)


def rank(cands: list, recent: list[str]) -> list[dict]:
    """Adaylari filtreler ve siralar. Kod karar veriyor, Gemini degil:
    olculebilirlik ve guvenlik 7'nin altindaysa ne kadar parlak olursa olsun
    elenir."""
    seen = [_words(t) for t in recent]
    out = []
    for c in cands:
        if not isinstance(c, dict) or not c.get("angle") or not c.get("measure"):
            continue
        sc = c.get("scores") if isinstance(c.get("scores"), dict) else {}
        nums = {k: v for k, v in sc.items() if isinstance(v, (int, float))}
        if nums.get("measurability", 0) < 7 or nums.get("safety", 0) < 7:
            continue
        aw = _words(c["angle"])
        if any(aw and w and len(aw & w) / len(aw | w) > 0.5 for w in seen):
            continue
        c["_total"] = sum(nums.values())
        out.append(c)
    out.sort(key=lambda c: (-c["_total"],
                            -c.get("scores", {}).get("timeliness", 0)))
    return out


# ═══ 2. YAZAR ═══════════════════════════════════════════════════════════
WRITER = """Write ONE script as JSON for this topic.

TOPIC
  angle   : {angle}
  measure : {measure}
  calc    : {calc}
  sources : {sources}
  signal  : {signal}

HARD RULES
LENGTH
- 12 to 16 beats. Total spoken words under {max_words}.
- One short spoken sentence per beat. No sentence over 14 words.

TWO TEXTS PER BEAT
- "say" is what the voice reads. Numbers are WORDS here, never digits:
  "three dollars", "forty seven percent", "U T F eight".
- "cap" is what appears on screen. Digits and symbols: "$3", "47%", "UTF-8".
- No URL, bracket or emoji in either.

STORY - every beat has a "role", in exactly this order, each used:
  hook    (1 beat)   the surprising, specific, verifiable fact. At most 12
                     words. Not a question. The contradiction is visible at once.
  why     (2-3)      the mechanism: why it is true.
  data    (3-6)      the measured numbers, one idea per beat.
  turn    (1-2)      the expectation flips: "but X is the strange one".
  resolve (1-2)      a flat conclusion. No call to action, no question.

SCENES - choose from this catalogue only. Never invent a name.
{scenes}
- Use at least 4 different scene types.
- Put "data" only on the beat where a scene STARTS. Following beats using the
  same scene with no data keep it on screen.
- Open with "title" or "contrast". Close with "close".

NUMBERS
- Every number on screen must be checkable from the sources. Prefer arithmetic
  you do yourself (ratios, byte counts, price x duration) over figures you
  half remember. If unsure of a figure, change the angle instead of guessing.
- "sources": real, checkable things, at least two.

FORBIDDEN: health/finance/legal/political advice; named living people;
anything you cannot source.

TITLE: under 60 characters, plain statement, no ALL CAPS, no "shocking".

{feedback}Reply with ONLY this JSON object:
{{"title": "...", "summary": "one sentence", "tags": ["3 to 6 lowercase"],
 "sources": ["...", "..."],
 "beats": [
  {{"id": "b1", "role": "hook", "scene": "contrast", "say": "...", "cap": "...",
    "data": {{}}}},
  {{"id": "b2", "role": "why", "say": "...", "cap": "..."}}
 ]}}"""

REVISE = """Your script was reviewed. Fix EVERY point below and return the
COMPLETE corrected JSON (same schema). Keep what already works; change only
what the points require.

POINTS TO FIX
{points}

CURRENT SCRIPT
{script}"""


def write(llm, brief: dict, *, max_words: int, problems: list[str] | None = None,
          previous: dict | None = None) -> dict | None:
    """Ilk taslak (previous=None) ya da duzeltme (previous + problems)."""
    if previous is not None:
        prompt = REVISE.format(points="\n".join(f"- {x}" for x in problems or []),
                               script=_j(_strip(previous)))
        return _as_dict(llm.ask_json(prompt, system=SYSTEM, temperature=0.6,
                                     role="yazar-duzeltme"))
    fb = ""
    if problems:
        fb = ("Your last attempt was rejected. Fix all of these:\n"
              + "\n".join(f"- {x}" for x in problems) + "\n\n")
    prompt = WRITER.format(
        angle=brief["angle"], measure=brief["measure"],
        calc=brief.get("calc", ""), sources=", ".join(brief.get("sources", [])),
        signal=brief.get("signal_url") or "none", scenes=SCENE_DOC,
        max_words=max_words, feedback=fb)
    return _as_dict(llm.ask_json(prompt, system=SYSTEM, temperature=0.9,
                                 role="yazar"))


def _as_dict(x):
    return x if isinstance(x, dict) else None


def _strip(spec: dict) -> dict:
    """Modele gidecek kopya: ic alanlar (_ ile baslayan, review, copy...) yok."""
    keep = ("title", "summary", "tags", "sources", "beats")
    return {k: spec[k] for k in keep if k in spec}


# ═══ 3. EDITOR ══════════════════════════════════════════════════════════
EDITOR_SYSTEM = """You are the editor of BYTE, a short-video channel about
measured facts on AI tools. You have rejected thousands of scripts. You do not
rewrite; you judge, and you are specific. You read the script as a stranger
who has never seen the channel. Score honestly: 9 or 10 means genuinely
compelling, 7 or 8 good enough to publish, 5 or 6 mediocre, 4 or below weak.
Most first drafts deserve 5 to 7."""

EDITOR = """Review this script for BYTE (audience 10 to 30, voice: dry machine
that measures things).

SCORE 1-10
  hook      does the first sentence stop a thumb? specific, surprising, not a question
  story     hook, why, data, turn, resolve: does the turn actually flip an expectation,
            and does the ending land flat and clean?
  clarity   could a 12 year old follow it on one listen? any jargon unexplained?
  audience  does a 10 to 30 year old care? concrete comparisons they can feel?
  voice     dry, exact, deadpan; no hype, no advice, no calls to action, no pretending

RISK (low / medium / high) - flag any of:
  advice (health, money, legal, political) | a named living person |
  a claim that could be false | clickbait | anything unsafe for young viewers

CLAIMS - list EVERY number that appears on screen (cap and data) or in the
title. For each:
  "shown":  the text as shown, e.g. "$0.40" or "8x"
  "expr":   if the number is DERIVED, the arithmetic that produces it using only
            digits and + - * / ( ) **, e.g. "0.40*60"; else null
  "value":  the numeric result you claim for expr (a number), else null
  "source": if expr is null, the 0-based index into "sources" of the document
            that states this figure, else null
A number you cannot trace to arithmetic or to a listed source is a defect:
say so in "fixes".

VERDICT: "publish" only if every score is 7 or more and risk is low.
"revise" if fixable. "reject" if the premise itself is unsound.

SCRIPT
{script}

Reply with JSON only:
{{"scores": {{"hook": 0, "story": 0, "clarity": 0, "audience": 0, "voice": 0}},
 "notes": {{"hook": "short", "story": "short", "clarity": "short",
           "audience": "short", "voice": "short"}},
 "risk": {{"level": "low", "flags": []}},
 "claims": [{{"shown": "", "expr": null, "value": null, "source": null}}],
 "verdict": "revise",
 "fixes": ["concrete instruction, one per problem"]}}"""


def edit(llm, spec: dict) -> dict:
    """Normalize edilmis inceleme. Gemini cevap vermezse EN KOTU varsayim
    (skor 0 -> revise); sessizce 'yayinla' demiyor."""
    raw = llm.ask_json(EDITOR.format(script=_j(_strip(spec))),
                       system=EDITOR_SYSTEM, temperature=0.2,
                       max_tokens=8192, role="editor")
    return rules.normalize_review(raw)


# ═══ 4. DOGRULAYICI ═════════════════════════════════════════════════════
FACTCHECK = """You are a fact checker. Use web search. Below are figures that a
short video will show as fact, each with the source the writer says it comes
from. For each figure find the SAME figure (allowing rounding) on an official
or primary page, as it stands today.

FIGURES
{items}

SOURCES THE WRITER LISTED
{sources}

Mark "confirmed" only if you found it. Mark "contradicted" if the real figure
differs (give it in "correct"). Mark "unverifiable" if you could not find it.
Never guess. Reply with JSON only:
{{"results": [{{"shown": "", "status": "confirmed|contradicted|unverifiable",
              "evidence": "one short line", "correct": ""}}]}}"""


def factcheck(llm, spec: dict, lookups: list[dict]):
    """(sorunlar, dogrulanamayan_sayisi, aramali_mi)."""
    if not lookups:
        return [], 0, True
    items = "\n".join(
        f"- {c.get('shown')}  (source #{c.get('source')}: "
        f"{spec['sources'][c['source']]})" for c in lookups)
    raw = llm.ask_json(
        FACTCHECK.format(items=items,
                         sources="\n".join(f"{i}. {s}" for i, s in
                                           enumerate(spec["sources"]))),
        system=SYSTEM, temperature=0.0, grounded=True, role="dogrulayici")
    grounded = bool(getattr(llm, "last_grounded", False))
    res = raw.get("results") if isinstance(raw, dict) else None
    by = {str(r.get("shown")).strip(): r for r in res or []
          if isinstance(r, dict)}
    problems, unverified = [], 0
    for c in lookups:
        r = by.get(str(c.get("shown")).strip())
        st = (r or {}).get("status")
        if st == "contradicted":
            problems.append(
                f"'{c['shown']}' yanlis: gercek deger "
                f"{(r or {}).get('correct') or '?'} "
                f"({(r or {}).get('evidence', '')}) -- duzelt ya da cikar")
        elif st != "confirmed":
            unverified += 1
    return problems, unverified, grounded


# ═══ 5. SANAT YONETMENI ═════════════════════════════════════════════════
ART = """Choose the colour theme for a BYTE video. Colour carries meaning here:
warm for money, cold for speed. Pick the one that fits the topic and mood.
Do NOT pick any of these (used by the last videos): {recent}

THEMES
{themes}

TITLE: {title}
SUMMARY: {summary}

Reply with JSON only: {{"theme": "name", "why": "one short line"}}"""


def art_direct(llm, spec: dict, recent: list[str], names) -> str | None:
    themes = "\n".join(f"- {k}: {v}" for k, v in THEME_DOC.items() if k in names)
    raw = llm.ask_json(
        ART.format(recent=", ".join(recent) or "none", themes=themes,
                   title=spec["title"], summary=spec.get("summary", "")),
        system=SYSTEM, temperature=0.5, role="sanat")
    t = raw.get("theme") if isinstance(raw, dict) else None
    return t if t in names and t not in recent else None


# ═══ 6. METIN YAZARI ════════════════════════════════════════════════════
COPY = """Write the publishing copy for this BYTE video, for three platforms.

VIDEO
  title   : {title}
  summary : {summary}
  hook    : {hook}
  result  : {result}

RULES
- 4 alternative titles, each under 60 characters, each a PLAIN STATEMENT of the
  surprising fact. No ALL CAPS, no "!!", no "shocking", no question. The
  strongest part goes first (phones cut titles at about 40 characters).
- youtube.hook: 1-2 sentences for the top of the description. Facts only.
- instagram.caption: the first line must work alone (it is all the feed shows).
  Then one more short line. No links.
- tiktok.caption: ONE short line, under 110 characters. No links.
- hashtags: youtube up to 5, instagram up to 5, tiktok up to 4. Specific to the
  topic, lowercase, no spaces, not generic spam like #fyp #viral.
- No emoji anywhere. BYTE is a dry machine.

Reply with JSON only:
{{"titles": ["", "", "", ""], "best": 0,
 "youtube": {{"hook": ""}}, "instagram": {{"caption": ""}},
 "tiktok": {{"caption": ""}},
 "hashtags": {{"youtube": [], "instagram": [], "tiktok": []}}}}"""


def copywrite(llm, spec: dict) -> dict | None:
    beats = spec["beats"]
    raw = llm.ask_json(
        COPY.format(title=spec["title"], summary=spec.get("summary", ""),
                    hook=beats[0].get("cap", ""), result=beats[-2].get("cap", "")),
        system=SYSTEM, temperature=0.8, role="metin")
    if not isinstance(raw, dict):
        return None
    titles = [t.strip() for t in raw.get("titles", []) if isinstance(t, str)]
    best = raw.get("best")
    ordered = ([titles[best]] if isinstance(best, int) and 0 <= best < len(titles)
               else []) + titles
    return {"titles": list(dict.fromkeys(ordered)),
            "youtube": raw.get("youtube") or {},
            "instagram": raw.get("instagram") or {},
            "tiktok": raw.get("tiktok") or {},
            "hashtags": raw.get("hashtags") or {}}
