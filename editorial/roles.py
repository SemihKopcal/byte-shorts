"""
Gemini'nin rolleri. Bes ayri is, bes ayri istem, hepsi ayni sozlesme:
girdi al, JSON dondur, hata olursa None dondur (cagiran yedege dusuyor).

  yapimci       5 konu adayi onerir (4 bicim), kendi puanlar (arama destekli)
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
CRT-headed robot whose only expression is a cursor. It reports what it measured
and what actually happened with AI tools. It never claims expertise, never
gives advice, never pretends to be human, never sells anything.

Voice: a deadpan friend who just found something strange and cannot quite let
it go. Dry, exact, short sentences. Concrete comparisons the audience can feel
(a coffee, a month of streaming, a phone battery, their homework) instead of
abstractions. Put the strangest detail first and keep one concrete payoff for
the last third, so the viewer has a reason to stay. No hype words. No questions
to the viewer. No calls to action."""

FORMATS = rules.FORMATS

FORMAT_DOC = {
    "measured": """FORMAT measured - the numbers are the story.
  hook = the contradiction in one number. why = the mechanism. data = the
  measured figures, one idea per beat. turn = the outlier. resolve = flat
  conclusion. Prefer arithmetic you do yourself over figures you half remember.""",
    "story": """FORMAT story - a documented episode, told in time order. People stay for
a story: something happened, something went wrong or turned out strange.
  hook = the strangest moment, stated first. why = the setup in one or two
  beats (who, what was supposed to happen). data = the events IN ORDER, one per
  beat; use timeline, split or byte_says scenes to show the sequence. turn =
  the twist or the consequence. resolve = what is true today, flat.
  Every date, company, product, ruling and quote must be checkable on a primary
  page or in major news. Companies, products, projects and historical systems
  may be named; no private individuals, no living people. Do not invent
  dialogue, motives or details. If you are unsure of a detail, leave it out.""",
    "explain": """FORMAT explain - one surprising reason an AI tool behaves the way it does.
  hook = the odd behaviour, stated as a fact. why = the mechanism in plain
  words. data = ONE concrete example the viewer can picture or try, shown
  step by step. turn = what that means for how they use it. resolve = flat
  takeaway. Few or no big numbers; any number shown must be derivable.""",
    "trend": """FORMAT trend - something people are talking about this week, checked
against the primary source.
  hook = what people are saying. why = where it came from. data = what the
  primary page actually says, claim by claim. turn = the gap between the two.
  resolve = flat conclusion. Name the page you checked in "sources".""",
}

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

steps      numbered steps, stacked. data: {steps:[{label, sub?, tone?}] (max 4)}
flow       boxes joined by arrows. data: {nodes:[{label, sub?, tone?}] (2-4), arrows?:[short text beside each arrow]}
equation   column arithmetic. data: {terms:[{value, label?}] (max 4), op?:"×", result:{value, label?, tone?}}
ring       percentage ring. data: {value, of?:100, label, sub?, tone?, dp?}
dots       a grid of dots, some light up. data: {total?:100, hit, label?, sub?, tone?}
chat       chat bubbles. data: {messages:[{who:"user"|"bot", text, name?, tone?}] (max 4)}
terminal   command window. data: {title?, lines:["$ cmd" | "output" | {text, kind:"hl"|"err", tone?}] (max 7)}
tokens     text split into chips. data: {tokens:[str] (max 24), note?}
probs      next-word odds. data: {prompt?, rows:[{word, p}] (max 5)}  p: 0..1
layers     stack built bottom to top. data: {layers:[{label, sub?}] (max 5, bottom first), total?}
checklist  true/false rows. data: {rows:[{text, ok}] (max 5)}
headline   news card. data: {source, date?, headline, kicker?}
scale      log ruler. data: {items:[{label, exp | value, text?}] (max 4)}
cycle      loop of 3-4 nodes. data: {nodes:[{label}] (3-4), center?}
bits       0/1 grid with an overflow. data: {bits:"0111...", flip_to?:"1000...", label?, flip_label?}

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
NO_SEARCH_PRODUCER = """
WEB SEARCH IS OFF FOR THIS RUN, so nothing can be fact-checked online. Propose
ONLY topics whose every figure is arithmetic a viewer can redo from numbers the
video itself states (sizes, counts, rates, seconds times a price given as an
assumption). Use the formats "measured" or "explain" only. Do not rely on how a
named product, model, tokenizer, company or paper behaves, and give no dates,
versions or published prices: each of those would be rejected as unverifiable.
Ignore any instruction below to search the web.
"""

NO_SEARCH_WRITER = """WEB SEARCH IS OFF TODAY: nothing can be fact-checked online, so the editor
rejects every statement that is not pure arithmetic. Show only numbers you
derive from numbers stated in the video. Do not state how a specific tokenizer,
model, product or company behaves, and give no dates, versions, prices or event
details. Build the video from the arithmetic and from what is true by
definition.

"""

PRODUCER = """Today is {today}. Propose exactly 5 candidate topics for the next
BYTE video.
{search_note}
BYTE tells things about AI that are TRUE and make a 10 to 30 year old think
"wait, really?". Interesting comes first; correct is the entry fee. Offer at
least 3 different formats among the 5:

  measured  the numbers are the story: arithmetic, or published prices/specs.
  story     a documented episode told in time order: what happened, what went
            wrong or turned out strange, what changed. Real events from AI and
            tech history or from the last weeks (a bot that was shut down in a
            day, a chatbot whose promise ended up in court, a machine that hid
            a human).
  explain   one surprising reason an AI tool behaves the way it does, shown
            with one example the viewer can picture (why a model miscounts
            letters, why it forgets you).
  trend     something being talked about this week, checked against the
            primary source: what people say against what the page says.

Formats used by the latest videos (newest last): {formats}
Prefer a format that is NOT among the most recent ones.

A good topic has ALL of these:
 1. A hook: a specific, strange or counter-intuitive first sentence. The viewer
    must want the next sentence.
 2. Everything in it is checkable: arithmetic you can do, or a primary page,
    court filing, paper, vendor post or major news report a viewer could open.
    Never rely on memory for a date, a name or a figure.
 3. Something a 10 to 30 year old cares about or can picture (phone, homework,
    games, feeds, jobs), not an abstraction.
 4. An angle that differs from the recent titles below.

WHAT IS BEING TALKED ABOUT RIGHT NOW
{live}

EVERGREEN IDEAS (use one only if no live signal works better)
{backlog}

RECENT TITLES - do not repeat or paraphrase
{recent}

Rules: no health, finance, legal or political advice; nothing about a named
living person (companies, products, projects and historical systems are fine);
nothing you cannot source. When you use a live signal put its URL in
"signal_url". Search the web first to confirm that news is real and recent.

Score each candidate honestly from 1 to 10. A 9 or 10 is rare. "verifiability"
is how easily a viewer could check every claim; "curiosity" is how much the
first sentence makes a stranger keep watching. Reply with JSON only:
{{"candidates": [{{
  "format": "measured|story|explain|trend",
  "angle": "one sentence: the surprising fact or the strangest moment",
  "measure": "what exactly is measured, or which events are told, and how",
  "calc": "the arithmetic, or the sequence of events, in one line",
  "sources": ["published page or document", "second one"],
  "signal_url": "url or null",
  "why_now": "one short line",
  "scores": {{"timeliness": 0, "verifiability": 0, "curiosity": 0,
             "audience_fit": 0, "safety": 0}}
}}]}}"""


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def produce(llm, *, live: str, backlog: list[dict], recent: list[str],
            today: str, formats: list[str] | None = None,
            search: bool = True) -> list[dict]:
    """Siralanmis aday listesi (en iyi basta). Gemini calismazsa bos liste."""
    formats = formats or []
    prompt = PRODUCER.format(
        today=today, live=live,
        search_note="" if search else NO_SEARCH_PRODUCER,
        formats=", ".join(formats[-4:]) or "(none yet)",
        backlog="\n".join(
            f"- [{b.get('format', 'measured')}] {b['angle']}  "
            f"[{b['measure']}]" for b in backlog[:6]) or "(none)",
        recent="\n".join(f"- {t}" for t in recent) or "- (none yet)")
    raw = llm.ask_json(prompt, system=SYSTEM, temperature=1.0, grounded=True,
                       role="yapimci")
    cands = raw.get("candidates") if isinstance(raw, dict) else None
    return rank(cands or [], recent, formats)


def rank(cands: list, recent: list[str],
         formats: list[str] | None = None) -> list[dict]:
    """Adaylari filtreler ve siralar. Kod karar veriyor, Gemini degil:
    dogrulanabilirlik, merak ve guvenlik 7'nin altindaysa ne kadar parlak
    olursa olsun elenir.

    Siralama: toplam puan (merak iki kat) + bicim dengesi. Son uc videoda
    kullanilmayan bicim +2, kullanilan her tekrar icin -2: kanal ayni bicimi
    ust uste uretmiyor, ama kotu bir hikaye iyi bir olcumun onune de gecmiyor.
    """
    seen = [_words(t) for t in recent]
    last = [f for f in (formats or [])][-3:]
    out = []
    for c in cands:
        if not isinstance(c, dict) or not c.get("angle") or not c.get("measure"):
            continue
        sc = c.get("scores") if isinstance(c.get("scores"), dict) else {}
        nums = {k: v for k, v in sc.items() if isinstance(v, (int, float))}
        # "measurability": eski ad, geriye uyum
        ver = nums.get("verifiability", nums.get("measurability", 0))
        if ver < 7 or nums.get("safety", 0) < 7 or nums.get("curiosity", 0) < 7:
            continue
        aw = _words(c["angle"])
        if any(aw and w and len(aw & w) / len(aw | w) > 0.5 for w in seen):
            continue
        fmt = c.get("format") if c.get("format") in FORMATS else "measured"
        c["format"] = fmt
        bonus = 2 if fmt not in last else -2 * last.count(fmt)
        c["_total"] = sum(nums.values()) + nums.get("curiosity", 0) + bonus
        out.append(c)
    out.sort(key=lambda c: (-c["_total"],
                            -c.get("scores", {}).get("timeliness", 0)))
    return out


# ═══ 2. YAZAR ═══════════════════════════════════════════════════════════
WRITER = """Write ONE script as JSON for this topic.

TOPIC
  format  : {format}
  angle   : {angle}
  measure : {measure}
  calc    : {calc}
  sources : {sources}
  signal  : {signal}

{search_note}{format_doc}

The video must be INTERESTING, not only correct: open on the strangest true
detail, let the middle build, and hold one concrete payoff for the last third.

HARD RULES
LENGTH
- 12 to 16 beats. Total spoken words under {max_words}.
- One short spoken sentence per beat. No sentence over 14 words.

TWO TEXTS PER BEAT
- "say" is what the voice reads. Numbers are WORDS here, never digits:
  "three dollars", "forty seven percent", "U T F eight".
- "cap" is what appears on screen. Digits and symbols: "$3", "47%", "UTF-8".
- No URL, bracket or emoji in either.

STRUCTURE - every beat has a "role", in exactly this order, each used:
  hook    (1 beat)   the surprising, specific, verifiable fact. At most 12
                     words. Not a question. The contradiction is visible at once.
  why     (2-3)      the mechanism or the setup: why it is true.
  data    (3-6)      the measured numbers or the events, one idea per beat.
  turn    (1-2)      the expectation flips: "but X is the strange one".
  resolve (1-2)      a flat conclusion. No call to action, no question.

SCENES - choose from this catalogue only. Never invent a name.
{scenes}
- Use at least 4 different scene types.
- Put "data" only on the beat where a scene STARTS. Following beats using the
  same scene with no data keep it on screen.
- Open with "title" or "contrast". Close with "close".

NUMBERS AND FACTS
- Every number on screen must be checkable from the sources. Prefer arithmetic
  you do yourself (ratios, byte counts, price x duration) over figures you
  half remember. If unsure of a figure, change the angle instead of guessing.
- Every event, date, name and ruling you state must be on a listed source.
  Leave out any detail you cannot place on one.
- "sources": real, checkable things, at least two.

FORBIDDEN: health/finance/legal/political advice; named living people;
anything you cannot source.

TITLE: under 60 characters, plain statement, no ALL CAPS, no "shocking".

{feedback}Reply with ONLY this JSON object:
{{"format": "{format_pick}", "title": "...", "summary": "one sentence",
 "tags": ["3 to 6 lowercase"],
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
    fmt = brief.get("format") if brief.get("format") in FORMATS else "auto"
    prompt = WRITER.format(
        format=fmt, format_doc=_format_doc(fmt), format_pick=_pick(fmt),
        angle=brief["angle"], measure=brief["measure"],
        calc=brief.get("calc", ""), sources=", ".join(brief.get("sources", [])),
        signal=brief.get("signal_url") or "none", scenes=SCENE_DOC,
        search_note="" if brief.get("search", True) else NO_SEARCH_WRITER,
        max_words=max_words, feedback=fb)
    return _as_dict(llm.ask_json(prompt, system=SYSTEM, temperature=0.9,
                                 role="yazar"))


def _format_doc(fmt: str) -> str:
    if fmt in FORMAT_DOC:
        return FORMAT_DOC[fmt]
    return ("Choose the ONE format that fits the topic best:\n"
            + "\n".join(FORMAT_DOC.values()))


def _pick(fmt: str) -> str:
    return fmt if fmt in FORMAT_DOC else "measured|story|explain|trend"


def _as_dict(x):
    return x if isinstance(x, dict) else None


def _strip(spec: dict) -> dict:
    """Modele gidecek kopya: ic alanlar (_ ile baslayan, review, copy...) yok."""
    keep = ("format", "title", "summary", "tags", "sources", "beats")
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
  audience  does a 10 to 30 year old care AND would they repeat it to a friend?
            concrete comparisons they can feel? A correct list of numbers with
            no tension scores 5 or 6, however accurate.
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

FACTS - the script states what happened (events, dates, rulings, who did what,
what a page says). List the 6 most important such statements that are NOT just
numbers on screen, each with the 0-based index of the listed source that backs
it. Stories and trend checks MUST list at least 2. A statement you cannot place
on a listed source is a defect: say so in "fixes".

VERDICT: "publish" only if every score is 7 or more and risk is low.
"revise" if fixable. "reject" if the premise itself is unsound.

FORMAT: {format}

SCRIPT
{script}

Reply with JSON only:
{{"scores": {{"hook": 0, "story": 0, "clarity": 0, "audience": 0, "voice": 0}},
 "notes": {{"hook": "short", "story": "short", "clarity": "short",
           "audience": "short", "voice": "short"}},
 "risk": {{"level": "low", "flags": []}},
 "claims": [{{"shown": "", "expr": null, "value": null, "source": null}}],
 "facts": [{{"claim": "", "source": 0}}],
 "verdict": "revise",
 "fixes": ["concrete instruction, one per problem"]}}"""


def edit(llm, spec: dict) -> dict:
    """Normalize edilmis inceleme. Gemini cevap vermezse EN KOTU varsayim
    (skor 0 -> revise); sessizce 'yayinla' demiyor."""
    raw = llm.ask_json(EDITOR.format(script=_j(_strip(spec)),
                                     format=spec.get("format") or "unknown"),
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
    """(sorunlar, dogrulanamayan_sayisi, aramali_mi).

    ARAMA YOKSA HICBIR SEY DOGRULANMIS SAYILMAZ. Model aramasiz "confirmed"
    derse bu hafizasindan konusuyor demek; olay ve rakam iddiasi icin bu
    kanit degil. O durumda her arama gerektiren iddia dogrulanamayan sayilir
    (fail-closed): yalniz formulle kanitlanan icerik yayina girebilir."""
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
    if not grounded:
        return [], len(lookups), False
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
