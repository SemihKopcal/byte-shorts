"""
Editorial hat testleri. AG YOK: Gemini sahte, zaman sahte. Her test saniyenin
altinda biter; check.yml her push'ta calistiriyor.

    python -m unittest discover -s tests -v
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from editorial import llm as L
from editorial import pipeline, roles, rules
from publish import manifest as M
from tests.fixtures import (CLAIMS, SCENES, THEMES, FakeLLM, copy_parts,
                            counter, good_spec, review)

BRAND = {"name": "BYTE", "handle": "@bytetest",
         "description_footer": "BYTE measures things.",
         "tags_base": ["ai", "tech"],
         "hashtags": {"core": ["#ai", "#tech"], "per_series": {"G": ["#data"]}},
         "title_rules": {"max_chars": 60, "ban": ["SHOCKING", "!!!"]}}


# ═══ llm.py ═════════════════════════════════════════════════════════════
class Stub:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, key, body=None, timeout=120):
        self.calls.append((method, url, body))
        return self.replies.pop(0) if self.replies else (500, {})


def ok(text):
    return 200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def models(*names):
    return 200, {"models": [{"name": f"models/{n}",
                             "supportedGenerationMethods": ["generateContent"]}
                            for n in names]}


def gem(stub, sleeps=None, logs=None):
    return L.Gemini("k", transport=stub,
                    sleep=(sleeps.append if sleeps is not None
                           else (lambda s: None)),
                    clock=counter(),
                    log=(logs.append if logs is not None else (lambda m: None)),
                    min_interval=0)


def quota(kind="rate", delay=None, text="You exceeded your current quota."):
    """Gemini'nin gercek 429 govdesine benzeyen sahte cevap."""
    qid = {"zero": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
           "daily": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
           "rate": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}[kind]
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": qid,
                                "quotaValue": "0" if kind == "zero" else "20"}]}]
    if delay is not None:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": f"{delay}s"})
    return 429, {"error": {"code": 429, "message": text, "details": details}}


class ModelPick(unittest.TestCase):
    def test_stable_newest_first_lite_and_preview_last(self):
        got = L.rank_models([
            {"name": "models/gemini-2.5-flash",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-flash-lite",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8-flash",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.9-flash-preview-05",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-image",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8-pro",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.0-flash",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.0-flash",
             "supportedGenerationMethods": ["embedContent"]},
        ])
        self.assertEqual(got, ["gemini-3.8-flash", "gemini-2.5-flash",
                               "gemini-2.0-flash", "gemini-3.5-flash-lite",
                               "gemini-3.9-flash-preview-05"])


class Client(unittest.TestCase):
    def test_retries_then_succeeds(self):
        s = Stub([models("gemini-3.8-flash"), (429, {}), (503, {}), ok("hi")])
        g = gem(s)
        self.assertEqual(g.ask("x", json_mode=False), "hi")
        self.assertEqual(g.model, "gemini-3.8-flash")

    def test_dead_model_falls_through_to_next(self):
        s = Stub([models("gemini-3.8-flash", "gemini-2.5-flash"),
                  (404, {"error": {"message": "gone"}}), ok("{}")])
        g = gem(s)
        self.assertEqual(g.ask("x"), "{}")
        self.assertEqual(g.model, "gemini-2.5-flash")
        self.assertNotIn("gemini-3.8-flash", g.candidates())

    def test_grounding_refused_retries_without_tools(self):
        s = Stub([models("gemini-3.8-flash"), (400, {"error": {"message": "n"}}),
                  ok('{"a": 1}')])
        g = gem(s)
        self.assertEqual(g.ask_json("x", grounded=True), {"a": 1})
        self.assertIn("tools", s.calls[1][2])
        self.assertNotIn("tools", s.calls[2][2])
        self.assertFalse(g.last_grounded)

    def test_zero_quota_model_is_skipped_without_waiting(self):
        sleeps, logs = [], []
        s = Stub([models("gemini-3.8-flash", "gemini-2.5-flash"),
                  quota("zero"), ok("fine")])
        g = gem(s, sleeps, logs)
        self.assertEqual(g.ask("x", json_mode=False), "fine")
        self.assertEqual(g.model, "gemini-2.5-flash")
        self.assertEqual(sleeps, [])                  # bekleme YOK
        self.assertNotIn("gemini-3.8-flash", g.candidates())
        self.assertTrue(any("kotasi yok" in m for m in logs))

    def test_daily_quota_is_dead_for_the_rest_of_the_run(self):
        s = Stub([models("gemini-3.8-flash", "gemini-2.5-flash"),
                  quota("daily"), ok("a"), ok("b")])
        g = gem(s)
        g.ask("x", json_mode=False)
        g.ask("y", json_mode=False)
        urls = [c[1] for c in s.calls if c[0] == "POST"]
        self.assertEqual(sum("3.8-flash" in u for u in urls), 1)   # bir kez denendi

    def test_rate_limit_waits_the_time_google_asks_for(self):
        sleeps = []
        s = Stub([models("gemini-3.8-flash"), quota("rate", 12), ok("hi")])
        g = gem(s, sleeps)
        self.assertEqual(g.ask("x", json_mode=False), "hi")
        self.assertEqual(sleeps, [12])                 # sabit 5 degil

    def test_rate_limit_hint_is_capped(self):
        sleeps = []
        s = Stub([models("gemini-3.8-flash"), quota("rate", 600), ok("hi")])
        gem(s, sleeps).ask("x", json_mode=False)
        self.assertEqual(sleeps, [L.MAX_HINT])

    def test_wait_budget_stops_endless_waiting(self):
        sleeps = []
        s = Stub([models("gemini-3.8-flash", "gemini-2.5-flash")]
                 + [quota("rate", 30)] * 60)
        g = gem(s, sleeps)
        g.wait_budget = 40
        self.assertIsNone(g.ask("x", json_mode=False))
        self.assertLessEqual(sum(sleeps), 40)
        self.assertLess(len(s.calls), 20)

    def test_search_quota_falls_back_to_ungrounded_same_model(self):
        s = Stub([models("gemini-3.8-flash"),
                  quota("zero", text="Quota exceeded for metric: "
                        "generate_content_grounding_requests, limit: 0"),
                  ok('{"a": 1}')])
        g = gem(s)
        self.assertEqual(g.ask_json("x", grounded=True), {"a": 1})
        self.assertEqual(g.model, "gemini-3.8-flash")  # model oldurulmedi
        self.assertFalse(g.last_grounded)

    def test_quota_hint_reads_message_when_details_missing(self):
        k, d = L.quota_hint({"error": {"message":
            "Quota exceeded for metric: x, limit: 0, model: m\n"
            "Please retry in 7.5s."}})
        self.assertEqual((k, d), ("zero", 7.5))
        self.assertEqual(L.quota_hint({}), ("", None))
        self.assertEqual(L.quota_hint({"error": {"details": ["junk", 3]}}),
                         ("", None))

    def test_failure_log_names_the_reason(self):
        logs = []
        s = Stub([models("gemini-3.8-flash"), quota("zero")])
        g = gem(s, logs=logs)
        self.assertIsNone(g.ask("x", json_mode=False))
        self.assertTrue(any("hicbir model cevap vermedi" in m for m in logs))

    def test_list_failure_still_tries_fallback_names(self):
        s = Stub([(500, {}), ok("fine")])
        g = gem(s)
        self.assertEqual(g.ask("x", json_mode=False), "fine")
        self.assertTrue(s.calls[1][1].endswith("gemini-flash-latest:generateContent"))

    def test_nothing_works_returns_none_never_raises(self):
        s = Stub([models("gemini-3.8-flash")] + [(500, {})] * 40)
        g = gem(s)
        self.assertIsNone(g.ask("x"))
        self.assertGreaterEqual(g.failures, 1)

    def test_key_is_header_never_url(self):
        s = Stub([models("gemini-3.8-flash"), ok("x")])
        gem(s).ask("x", json_mode=False)
        self.assertTrue(all("key=" not in c[1] for c in s.calls))

    def test_thought_parts_are_dropped(self):
        out = {"candidates": [{"content": {"parts": [
            {"text": "thinking...", "thought": True}, {"text": "answer"}]}}]}
        self.assertEqual(L.Gemini._text(out), "answer")

    def test_parse_json_tolerates_fences_and_chatter(self):
        self.assertEqual(L.parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(L.parse_json('Sure! {"a": [1, 2]} hope it helps'),
                         {"a": [1, 2]})
        self.assertIsNone(L.parse_json("no json here"))
        self.assertIsNone(L.parse_json(""))


# ═══ rules.py ═══════════════════════════════════════════════════════════
class Arithmetic(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(rules.safe_eval("0.40*60"), 24)
        self.assertAlmostEqual(rules.safe_eval("1,200 x 2".replace("x", "*")), 2400)
        self.assertAlmostEqual(rules.safe_eval("2^10"), 1024)
        self.assertAlmostEqual(rules.safe_eval("$3 * 4"), 12)
        self.assertAlmostEqual(rules.safe_eval("50%"), 0.5)

    def test_rejects_code(self):
        for bad in ("__import__('os').system('id')", "open('x')", "a+1",
                    "[1,2]", "(lambda: 1)()", "9**9**9", "10**30", "1/0"):
            with self.assertRaises((ValueError, SyntaxError, ZeroDivisionError,
                                    OverflowError), msg=bad):
                rules.safe_eval(bad)


class ScriptValidation(unittest.TestCase):
    def v(self, spec):
        return rules.validate_script(spec, SCENES)

    def test_good_spec_is_clean(self):
        self.assertEqual(self.v(good_spec()), [])

    def test_unknown_scene(self):
        s = good_spec()
        s["beats"][2]["scene"] = "hologram"
        self.assertTrue(any("bilinmeyen sahne" in p for p in self.v(s)))

    def test_bad_pose_would_crash_render(self):
        s = good_spec()
        s["beats"][7]["data"]["pose"] = "dance"
        self.assertTrue(any("pose" in p for p in self.v(s)))

    def test_digits_in_spoken_text(self):
        s = good_spec()
        s["beats"][4]["say"] = "The cheapest model charges 3 dollars."
        self.assertTrue(any("rakam" in p for p in self.v(s)))

    def test_cta_is_banned(self):
        s = good_spec()
        s["beats"][9]["say"] = "Subscribe for more of this."
        self.assertTrue(any("yasakli" in p for p in self.v(s)))

    def test_roles_must_be_in_story_order(self):
        s = good_spec()
        s["beats"][7]["role"] = "why"          # turn'den once data bitmeden
        self.assertTrue(any("role" in p for p in self.v(s)))

    def test_missing_turn(self):
        s = good_spec()
        for b in s["beats"]:
            if b["role"] == "turn":
                b["role"] = "data"
        self.assertTrue(any("turn" in p for p in self.v(s)))

    def test_hook_must_not_be_question_or_long(self):
        s = good_spec()
        s["beats"][0]["say"] = "Why does one second of video cost so much?"
        self.assertTrue(any("soru" in p for p in self.v(s)))

    def test_must_open_and_close_right(self):
        s = good_spec()
        s["beats"][0]["scene"] = "table"
        s["beats"][0]["data"] = {"rows": [{"name": "a", "value": "b"}]}
        self.assertTrue(any("ilk sahne" in p for p in self.v(s)))

    def test_too_few_scene_types(self):
        s = good_spec()
        for i in (2, 7):
            s["beats"][i].pop("scene")
            s["beats"][i].pop("data")
        self.assertTrue(any("farkli sahne" in p for p in self.v(s)))

    def test_table_without_rows_breaks_render(self):
        s = good_spec()
        s["beats"][3]["data"] = {}
        self.assertTrue(any("rows" in p for p in self.v(s)))


class Claims(unittest.TestCase):
    def test_good_claims_pass_and_lookup_is_returned(self):
        p, look = rules.check_claims(good_spec(), CLAIMS, 2)
        self.assertEqual(p, [])
        self.assertEqual([c["shown"] for c in look], ["$0.40"])

    def test_wrong_arithmetic_is_caught_by_code(self):
        bad = copy.deepcopy(CLAIMS)
        bad[1]["value"] = 42                    # editor yanlis sonuc yazdi
        p, _ = rules.check_claims(good_spec(), bad, 2)
        self.assertTrue(any("0.40*60" in x for x in p))

    def test_unsourced_figure(self):
        bad = copy.deepcopy(CLAIMS)
        bad[0]["source"] = None
        p, _ = rules.check_claims(good_spec(), bad, 2)
        self.assertTrue(any("kaynak numarasi" in x for x in p))

    def test_editor_cannot_skip_a_number(self):
        p, _ = rules.check_claims(good_spec(), CLAIMS[:1], 2)
        self.assertTrue(any("ekranda" in x for x in p))

    def test_formula_that_is_not_math_is_rejected(self):
        bad = copy.deepcopy(CLAIMS)
        bad[1]["expr"] = "__import__('os').getcwd()"
        p, _ = rules.check_claims(good_spec(), bad, 2)
        self.assertTrue(any("hesaplanamadi" in x for x in p))


class Facts(unittest.TestCase):
    def test_story_needs_at_least_two_listed_statements(self):
        p, out = rules.fact_lookups(
            {"format": "story"}, [{"claim": "it went offline", "source": 0}], 2)
        self.assertEqual(len(out), 1)
        self.assertTrue(any("at least 2" in x for x in p))

    def test_measured_does_not_need_statements(self):
        self.assertEqual(rules.fact_lookups({"format": "measured"}, [], 2),
                         ([], []))
        self.assertEqual(rules.fact_lookups({"format": "explain"}, None, 2),
                         ([], []))

    def test_statement_without_valid_source_is_a_problem_not_a_lookup(self):
        p, out = rules.fact_lookups(
            {"format": "story"},
            [{"claim": "a", "source": 0}, {"claim": "b", "source": 7},
             {"claim": "c", "source": None}, {"claim": "", "source": 0},
             {"claim": "d", "source": True}, "junk"], 2)
        self.assertEqual([o["claim"] if "claim" in o else o["shown"]
                          for o in out], ["a"])
        self.assertEqual(sum("no valid source" in x for x in p), 3)

    def test_lookups_are_capped(self):
        facts = [{"claim": f"statement {i}", "source": 0} for i in range(20)]
        _, out = rules.fact_lookups({"format": "story"}, facts, 2)
        self.assertEqual(len(out), rules.MAX_FACTS)

    def test_ungrounded_factcheck_verifies_nothing(self):
        # model "confirmed" dese de arama yoksa hafizadan konusuyor
        llm = FakeLLM({"dogrulayici": [{"results": [
            {"shown": "a", "status": "confirmed"},
            {"shown": "b", "status": "confirmed"}]}]})
        llm.last_grounded = False
        lookups = [{"shown": "a", "source": 0}, {"shown": "b", "source": 1}]
        problems, unverified, grounded = roles.factcheck(
            llm, good_spec(), lookups)
        self.assertEqual((problems, unverified, grounded), ([], 2, False))

    def test_grounded_factcheck_counts_statuses(self):
        llm = FakeLLM({"dogrulayici": [{"results": [
            {"shown": "a", "status": "confirmed"},
            {"shown": "b", "status": "contradicted", "correct": "c"},
            {"shown": "d", "status": "unverifiable"}]}]})
        lookups = [{"shown": s, "source": 0} for s in "abd"]
        problems, unverified, grounded = roles.factcheck(
            llm, good_spec(), lookups)
        self.assertEqual(len(problems), 1)
        self.assertEqual((unverified, grounded), (1, True))

    def test_timeline_text_must_fit_the_screen(self):
        s = good_spec()
        s["beats"][3]["scene"] = "timeline"
        s["beats"][3]["data"] = {"steps": [
            {"at": "Morning", "label": "Bot goes live"},
            {"at": "A very long time label", "label": "ok"}]}
        self.assertTrue(any("timeline" in x
                            for x in rules.validate_script(s, SCENES)))
        s["beats"][3]["data"] = {"steps": [
            {"at": "Morning", "label": "A label that is much too long to read"}]}
        self.assertTrue(any("timeline" in x
                            for x in rules.validate_script(s, SCENES)))
        s["beats"][3]["data"] = {"steps": [
            {"at": "Morning", "label": "Bot goes live"},
            {"at": "Night", "label": "Taken offline"}]}
        self.assertEqual(rules.validate_script(s, SCENES), [])

    def test_format_is_required_in_a_script(self):
        s = good_spec()
        del s["format"]
        self.assertTrue(any("format" in x
                            for x in rules.validate_script(s, SCENES)))
        s["format"] = "gossip"
        self.assertTrue(any("format" in x
                            for x in rules.validate_script(s, SCENES)))


class Decision(unittest.TestCase):
    def d(self, **kw):
        probs = kw.pop("problems", [])
        return rules.decide(rules.normalize_review(review(**kw)), probs)

    def test_publish(self):
        self.assertEqual(self.d().verdict, "publish")

    def test_low_score_forces_revise(self):
        d = self.d(score=6, verdict="publish")
        self.assertEqual(d.verdict, "revise")
        self.assertTrue(d.fixes)

    def test_code_problem_overrides_editor_approval(self):
        self.assertEqual(self.d(problems=["aritmetik"]).verdict, "revise")

    def test_high_risk_rejects(self):
        self.assertEqual(self.d(risk="high").verdict, "reject")

    def test_medium_risk_revises(self):
        self.assertEqual(self.d(risk="medium").verdict, "revise")

    def test_garbage_review_is_worst_case_not_publish(self):
        d = rules.decide(rules.normalize_review("lol"), [])
        self.assertEqual(d.verdict, "revise")
        d = rules.decide(rules.normalize_review(None), [])
        self.assertNotEqual(d.verdict, "publish")


class Producer(unittest.TestCase):
    def cand(self, angle, **sc):
        s = {"timeliness": 8, "measurability": 8, "curiosity": 8,
             "audience_fit": 8, "safety": 9}
        s.update(sc)
        return {"angle": angle, "measure": "m", "scores": s}

    def test_filters_and_sorts(self):
        got = roles.rank([
            self.cand("alpha ratios in tokenizers across scripts"),
            self.cand("unsafe topic about someone", safety=4),
            self.cand("cannot be measured honestly", measurability=5),
            self.cand("gpu electricity cost per token", curiosity=10),
        ], [])
        self.assertEqual([c["angle"] for c in got],
                         ["gpu electricity cost per token",
                          "alpha ratios in tokenizers across scripts"])

    def test_format_rotation_prefers_the_format_not_used_lately(self):
        a = self.cand("tokens per alphabet across scripts")
        a["format"] = "measured"
        b = self.cand("a chatbot that was shut down within a day")
        b["format"] = "story"
        got = roles.rank([a, b], [], ["measured", "measured", "measured"])
        self.assertEqual([c["format"] for c in got], ["story", "measured"])
        # gecmis yoksa ikisi esit: uretici sirasi bozulmadan kalir
        got = roles.rank([self.cand("first idea about caches"),
                          self.cand("second idea about quotas")], [], [])
        self.assertEqual(len(got), 2)

    def test_strong_measured_still_beats_weak_story_with_rotation(self):
        a = self.cand("gpu electricity cost per token", curiosity=10,
                      timeliness=10)
        a["format"] = "measured"
        b = self.cand("a very average story about a bot", curiosity=7,
                      timeliness=6, audience_fit=7)
        b["format"] = "story"
        got = roles.rank([a, b], [], ["story", "story", "measured"])
        self.assertEqual(got[0]["format"], "measured")

    def test_curiosity_gate_and_new_score_name(self):
        dull = self.cand("a dull but exact table of prices", curiosity=5)
        new = {"angle": "tokens differ per alphabet by a wide margin",
               "measure": "m", "format": "explain",
               "scores": {"timeliness": 7, "verifiability": 8, "curiosity": 8,
                          "audience_fit": 8, "safety": 9}}
        got = roles.rank([dull, new], [])
        self.assertEqual([c["format"] for c in got], ["explain"])

    def test_unknown_format_becomes_measured(self):
        c = self.cand("cache break even reuse count")
        c["format"] = "gossip"
        self.assertEqual(roles.rank([c], [])[0]["format"], "measured")

    def test_producer_prompt_shows_recent_formats_and_backlog_format(self):
        llm = FakeLLM({"yapimci": [{"candidates": []}]})
        roles.produce(llm, live="(none)", today="2026-11-06",
                      recent=[], formats=["measured", "story"],
                      backlog=[{"format": "explain", "angle": "no clock",
                                "measure": "request body"}])
        prompt = llm.log[0][1]
        self.assertIn("measured, story", prompt)
        self.assertIn("[explain] no clock", prompt)

    def test_drops_repeats_of_recent_titles(self):
        got = roles.rank([self.cand("cost of video generation per second")],
                         ["The cost of video generation per second"])
        self.assertEqual(got, [])


# ═══ publish/manifest.py ════════════════════════════════════════════════
class Copy(unittest.TestCase):
    def test_compose_builds_three_platform_texts(self):
        c = M.compose(BRAND, good_spec(), copy_parts())
        self.assertIn("Sources / method:", c["youtube"])
        self.assertIn("Veo public pricing page", c["youtube"])
        self.assertIn("@bytetest", c["instagram"])
        self.assertNotIn("http", c["instagram"] + c["tiktok"])
        self.assertEqual(M.validate_copy(c, BRAND), [])

    def test_gemini_cannot_remove_sources_or_inflate_hashtags(self):
        parts = copy_parts()
        parts["hashtags"]["youtube"] = [f"#tag{i}" for i in range(30)]
        parts["youtube"]["hook"] = "Short hook."
        c = M.compose(BRAND, good_spec(), parts)
        self.assertIn("Sources / method:", c["youtube"])
        self.assertLessEqual(c["youtube"].count("#"), 5)

    def test_template_when_gemini_is_absent(self):
        c = M.compose(BRAND, good_spec(), None)
        self.assertEqual(M.validate_copy(c, BRAND), [])
        self.assertIn("#ai", c["tiktok"])

    def test_validation_catches_shouting_emoji_links(self):
        c = M.compose(BRAND, good_spec(), copy_parts())
        c["title"] = "THIS IS ABSOLUTELY UNBELIEVABLE NEWS"
        self.assertTrue(any("BUYUK" in p for p in M.validate_copy(c, BRAND)))
        c = M.compose(BRAND, good_spec(), copy_parts())
        c["tiktok"] += " \U0001F525"
        self.assertTrue(any("emoji" in p for p in M.validate_copy(c, BRAND)))
        c = M.compose(BRAND, good_spec(), copy_parts())
        c["instagram"] += " https://example.com"
        self.assertTrue(any("baglanti" in p for p in M.validate_copy(c, BRAND)))

    def test_invalid_hashtags_are_dropped(self):
        self.assertEqual(M.clean_tags(["ai", "#ok_tag", "bad tag!", "9x", "#AI"], 5),
                         ["#ai", "#ok_tag"])


# ═══ pipeline ═══════════════════════════════════════════════════════════
def cands():
    return {"candidates": [{
        "angle": "A minute of AI video costs sixty times its second",
        "measure": "price per second x 60", "calc": "0.40*60",
        "sources": ["Veo public pricing page", "Provider pricing table"],
        "signal_url": None, "why_now": "new model this week",
        "scores": {"timeliness": 8, "measurability": 9, "curiosity": 8,
                   "audience_fit": 8, "safety": 9}}]}


def root_with_content(tmp: str) -> Path:
    r = Path(tmp)
    (r / "content/scripts").mkdir(parents=True)
    (r / "content/published.json").write_text("[]")
    (r / "content/backlog.json").write_text(json.dumps({"topics": [
        {"angle": "UTF-8 makes the same sentence cost different amounts",
         "measure": "byte length", "sources": ["UDHR article one"]}]}))
    (r / "brand.json").write_text(json.dumps(BRAND))
    return r


class Pipeline(unittest.TestCase):
    def run_pipeline(self, replies, grounded=True, scripts=(), **kw):
        with tempfile.TemporaryDirectory() as tmp:
            root = root_with_content(tmp)
            for name, body in scripts:
                (root / "content/scripts" / name).write_text(json.dumps(body))
            llm = FakeLLM(replies)
            llm.last_grounded = grounded
            try:
                spec = pipeline.run(llm, root=root, today="2026-11-06",
                                    scene_names=SCENES, theme_names=THEMES,
                                    live="(none)", log=lambda m: None, **kw)
                files = sorted(p.name for p in (root / "content/scripts").glob("*"))
                rej = sorted(p.name for p in (root / "content/rejected").glob("*")) \
                    if (root / "content/rejected").exists() else []
                return spec, llm, files, rej, None
            except pipeline.Failure as e:
                rej = sorted(p.name for p in (root / "content/rejected").glob("*")) \
                    if (root / "content/rejected").exists() else []
                return None, llm, [], rej, e

    def test_happy_path_with_one_revision(self):
        weak = good_spec()
        weak["beats"][0]["say"] = "Why does one second of video cost so much?"
        revised = good_spec()
        spec, llm, files, _, err = self.run_pipeline({
            "yapimci": [cands()],
            "yazar": [weak, good_spec()],              # ilk taslak kuraldan dusuyor
            "editor": [review("revise", 6, fixes=["sharpen the hook"]),
                       review("publish", 8)],
            "yazar-duzeltme": [revised],
            "dogrulayici": [{"results": [{"shown": "$0.40",
                                          "status": "confirmed"}]}],
            "sanat": [{"theme": "ember", "why": "money"}],
            "metin": [copy_parts()],
        })
        self.assertIsNone(err)
        self.assertEqual(spec["review"]["rounds"], 1)
        self.assertEqual(spec["theme"], "ember")
        self.assertEqual(spec["series"], "G")
        self.assertTrue(spec["id"].startswith("2026-11-06-"))
        self.assertEqual(spec["title"], "Video models bill by the second")
        self.assertEqual(M.validate_copy(spec["copy"], BRAND), [])
        self.assertEqual(files, [spec["id"] + ".json"])
        # editore giden metin kod tarafindan temizlenmis (ic alan sizmiyor)
        editor_prompt = [p for r, p in llm.log if r == "editor"][0]
        self.assertNotIn('"review"', editor_prompt)

    def test_wrong_arithmetic_blocks_even_if_editor_says_publish(self):
        bad = copy.deepcopy(CLAIMS)
        bad[1]["value"] = 99
        spec, _, files, rej, err = self.run_pipeline({
            "yapimci": [cands()], "yazar": [good_spec()],
            "editor": [review("publish", 9, claims=bad)],
            "yazar-duzeltme": [good_spec()],
            "dogrulayici": [{"results": []}],
        })
        self.assertIsNone(spec)
        self.assertIsInstance(err, pipeline.Failure)
        self.assertEqual(files, [])
        self.assertTrue(rej, "reddedilen konu content/rejected altina yazilmali")

    def test_contradicted_figure_blocks(self):
        spec, *_ , err = self.run_pipeline({
            "yapimci": [cands()], "yazar": [good_spec()],
            "editor": [review("publish", 9)],
            "yazar-duzeltme": [good_spec()],
            "dogrulayici": [{"results": [{"shown": "$0.40",
                                          "status": "contradicted",
                                          "correct": "$0.20"}]}],
        })
        self.assertIsNone(spec)
        self.assertIsNotNone(err)

    def test_one_unverifiable_is_tolerated_two_are_not(self):
        two = copy.deepcopy(CLAIMS) + [
            {"shown": "$12.50", "expr": None, "value": None, "source": 1}]
        s = good_spec()
        s["beats"][5]["cap"] = "$12.50"
        one_ok, *_ = self.run_pipeline({
            "yapimci": [cands()], "yazar": [good_spec()],
            "editor": [review("publish", 8)],
            "dogrulayici": [{"results": []}],        # $0.40 dogrulanamadi
            "sanat": [{"theme": "ember"}], "metin": [copy_parts()],
        })
        self.assertIsNotNone(one_ok)
        self.assertEqual(one_ok["review"]["unverified"], 1)
        two_bad, *_ = self.run_pipeline({
            "yapimci": [cands()], "yazar": [s],
            "editor": [review("publish", 8, claims=two)],
            "yazar-duzeltme": [s],
            "dogrulayici": [{"results": []}],
        })
        self.assertIsNone(two_bad)

    FACTS = [{"claim": "the bot launched on Twitter", "source": 0},
             {"claim": "the company took it offline within a day", "source": 1}]

    def story(self):
        s = good_spec()
        s["format"] = "story"
        return s

    def verdicts(self, *claims, status="confirmed"):
        return {"results": [{"shown": c, "status": status} for c in claims]}

    def test_story_happy_path_checks_events_and_records_format(self):
        spec, llm, *_ , err = self.run_pipeline({
            "yazar": [self.story()],
            "editor": [review("publish", 8, facts=self.FACTS)],
            "dogrulayici": [self.verdicts(
                "$0.40", *[f["claim"] for f in self.FACTS])],
            "sanat": [{"theme": "plum"}], "metin": [copy_parts()],
        }, topic="a chatbot that was shut down in a day")
        self.assertIsNone(err)
        self.assertEqual(spec["brief"]["format"], "story")
        fc = [p for r, p in llm.log if r == "dogrulayici"][0]
        self.assertIn("took it offline within a day", fc)    # olay iddiasi da gitti

    def test_story_without_listed_statements_is_sent_back(self):
        spec, *_ , err = self.run_pipeline({
            "yazar": [self.story()],
            "editor": [review("publish", 9, facts=[])],
            "yazar-duzeltme": [self.story()],
            "dogrulayici": [self.verdicts("$0.40")],
        }, topic="a story with nothing to check")
        self.assertIsNone(spec)
        self.assertIn("at least 2", str(err.args[0]) + "")

    def test_story_cannot_publish_when_search_is_down(self):
        spec, *_ , err = self.run_pipeline({
            "yazar": [self.story()],
            "editor": [review("publish", 9, facts=self.FACTS)],
            "yazar-duzeltme": [self.story()],
            "dogrulayici": [self.verdicts(
                "$0.40", *[f["claim"] for f in self.FACTS])],
        }, grounded=False, topic="a story we cannot check")
        self.assertIsNone(spec)
        self.assertIsNotNone(err)

    def test_measured_with_one_lookup_still_publishes_without_search(self):
        # tek rakam (<= ALLOW_UNVERIFIED) aramasiz da gecer; formuller kodla
        # kanitlandigi icin arama gerekmiyor
        spec, *_ , err = self.run_pipeline({
            "yapimci": [cands()], "yazar": [good_spec()],
            "editor": [review("publish", 8)],
            "dogrulayici": [self.verdicts("$0.40")],
            "sanat": [{"theme": "ember"}], "metin": [copy_parts()],
        }, grounded=False)
        self.assertIsNone(err)
        self.assertFalse(spec["review"]["grounded"])

    def test_writer_must_keep_the_briefed_format(self):
        wrong = good_spec()                       # measured
        problems = pipeline._draft_problems(
            wrong, SCENES, [], {"format": "story"})
        self.assertTrue(any('"story"' in p for p in problems))
        self.assertEqual(pipeline._draft_problems(
            wrong, SCENES, [], {"format": "auto"}), [])

    def test_recent_formats_read_from_scripts_legacy_means_measured(self):
        old = good_spec()
        del old["format"]
        st = good_spec()
        st["brief"] = {"format": "story"}
        with tempfile.TemporaryDirectory() as tmp:
            root = root_with_content(tmp)
            (root / "content/scripts/2026-11-01-a.json").write_text(
                json.dumps(old))
            (root / "content/scripts/2026-11-02-b.json").write_text(
                json.dumps(st))
            self.assertEqual(pipeline.recent_formats(root),
                             ["measured", "story"])

    def test_backlog_puts_unused_formats_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = root_with_content(tmp)
            (root / "content/backlog.json").write_text(json.dumps({"topics": [
                {"format": "measured", "angle": "alpha measure topic here",
                 "measure": "m"},
                {"format": "story", "angle": "bravo story topic here",
                 "measure": "m"},
                {"angle": "charlie legacy topic here", "measure": "m"}]}))
            got = pipeline.backlog_candidates(
                root, [], "2026-11-06", ["story", "story"])
            self.assertNotEqual(got[-1]["format"], "measured")
            self.assertEqual(got[-1]["format"], "story")
            self.assertEqual({g["format"] for g in got},
                             {"measured", "story"})

    def test_gemini_down_stops_loudly_without_hammering(self):
        spec, llm, files, rej, err = self.run_pipeline({"yapimci": [cands()]})
        self.assertIsNone(spec)
        self.assertIsInstance(err, pipeline.Failure)
        self.assertLess(llm.calls, 8)

    def test_producer_empty_falls_back_to_backlog(self):
        spec, llm, *_ = self.run_pipeline({
            "yapimci": [{"candidates": []}], "yazar": [good_spec()],
            "editor": [review("publish", 8)],
            "dogrulayici": [{"results": [{"shown": "$0.40",
                                          "status": "confirmed"}]}],
            "sanat": [{"theme": "deep"}], "metin": [copy_parts()],
        })
        self.assertIsNotNone(spec)
        writer_prompt = [p for r, p in llm.log if r == "yazar"][0]
        self.assertIn("UTF-8", writer_prompt)

    def test_explicit_topic_skips_producer(self):
        spec, llm, *_ = self.run_pipeline({
            "yazar": [good_spec()], "editor": [review("publish", 8)],
            "dogrulayici": [{"results": [{"shown": "$0.40",
                                          "status": "confirmed"}]}],
            "sanat": [{"theme": "deep"}], "metin": [copy_parts()],
        }, topic="how much does a Short cost")
        self.assertIsNotNone(spec)
        self.assertNotIn("yapimci", [r for r, _ in llm.log])

    def test_bad_copy_falls_back_to_template_not_failure(self):
        spec, *_ = self.run_pipeline({
            "yapimci": [cands()], "yazar": [good_spec()],
            "editor": [review("publish", 8)],
            "dogrulayici": [{"results": [{"shown": "$0.40",
                                          "status": "confirmed"}]}],
            "sanat": [{"theme": "deep"}],
            "metin": [None],                         # metin yazari cevap vermedi
        })
        self.assertIsNotNone(spec)
        self.assertEqual(M.validate_copy(spec["copy"], BRAND), [])

    def test_art_director_cannot_pick_recent_or_unknown_theme(self):
        class A(FakeLLM):
            pass
        llm = A({"sanat": [{"theme": "hologram"}]})
        self.assertIsNone(roles.art_direct(llm, good_spec(), [], THEMES))
        llm = A({"sanat": [{"theme": "ember"}]})
        self.assertIsNone(roles.art_direct(llm, good_spec(), ["ember"], THEMES))
        llm = A({"sanat": [{"theme": "deep"}]})
        self.assertEqual(roles.art_direct(llm, good_spec(), ["ember"], THEMES),
                         "deep")


# ═══ render tarafi ══════════════════════════════════════════════════════
class RenderSide(unittest.TestCase):
    def _timeline_pixels(self, steps, t):
        from PIL import Image, ImageDraw
        from worker import draw as D, scenes
        try:
            D.F_DISP(40)
        except RuntimeError:                  # check.yml runner'inda font yok
            self.skipTest("Inter fontu kurulu degil")
        im = Image.new("RGB", (D.W, D.H), (18, 10, 28))
        scenes.timeline(ImageDraw.Draw(im), t, 0.0, 6.0, {"steps": steps})
        return im

    def test_timeline_draws_its_last_step_and_stays_on_screen(self):
        from worker import draw as D, scenes
        steps = [{"at": "Morning", "label": "Bot goes live"},
                 {"at": "Hours", "label": "Users test it"},
                 {"at": "Evening", "label": "Replies turn ugly", "tone": "bad"},
                 {"at": "Night", "label": "Taken offline", "tone": "bad"}]
        im = self._timeline_pixels(steps, 9.0)            # ilerleme bitmis
        y = int(scenes.MID - 40)
        # Noktalar yaricapi ~18 px, cizgi 6 px kalinliginda: sutun yuksekligi
        # >= 25 olan ardisik bolgeler = nokta. 4 adim = 4 nokta.
        px = im.load()
        tall = []
        for x in range(D.W):
            ext = sum(1 for yy in range(y - 25, y + 26)
                      if sum(px[x, yy]) > 300)
            tall.append(ext >= 25)
        dots = sum(1 for x in range(1, D.W) if tall[x] and not tall[x - 1])
        self.assertEqual(dots, len(steps), "son adim cizilmiyor")
        # etiketler kenar bosluguna tasmiyor: sol/sag 60 px bos
        band = im.crop((0, y + 40, D.W, y + 160)).convert("L")
        px = band.load()
        for x in list(range(0, 60)) + list(range(D.W - 60, D.W)):
            for yy in range(band.height):
                self.assertLess(px[x, yy], 60, f"tasma x={x}")

    def test_manifest_uses_copy_and_exposes_three_captions(self):
        spec = good_spec()
        spec.update(id="x", series="G", _theme="ember")
        spec["copy"] = M.compose(BRAND, spec, copy_parts())
        with tempfile.TemporaryDirectory() as tmp:
            r = Path(tmp)
            (r / "brand.json").write_text(json.dumps(BRAND))
            man = M.build_manifest(spec, {"duration": 41.2}, Path("v.mp4"), r)
        self.assertEqual(man["title"], spec["copy"]["title"])
        self.assertEqual(set(man["captions"]), {"youtube", "instagram", "tiktok"})
        self.assertEqual(man["description"], man["captions"]["youtube"])
        self.assertEqual(man["theme"], "ember")
        self.assertIn("## Instagram", M.captions_markdown(man))

    def test_manifest_without_copy_uses_template(self):
        spec = good_spec()
        spec.update(id="x", series="G")
        with tempfile.TemporaryDirectory() as tmp:
            r = Path(tmp)
            (r / "brand.json").write_text(json.dumps(BRAND))
            man = M.build_manifest(spec, {"duration": 40}, Path("v.mp4"), r)
        self.assertIn("Sources / method:", man["description"])

    def test_close_scene_gets_the_real_handle(self):
        try:
            from worker.build import _inject_brand
        except Exception as e:                       # noqa: BLE001
            self.skipTest(f"render bagimliliklari yok: {e}")
        spec = good_spec()
        _inject_brand(spec, {"handle": "@bytetest"})
        self.assertEqual(spec["beats"][-1]["data"]["handle"], "@bytetest")

    def test_beat_without_scene_stays_on_the_previous_scene(self):
        try:
            from worker.series_g import _group
        except Exception as e:                       # noqa: BLE001
            self.skipTest(f"render bagimliliklari yok: {e}")
        groups = _group(good_spec()["beats"])
        names = [g[0] for g in groups]
        # b5-b7 sahnesiz: tablo ekranda kalmali, bos 'title' acilmamali
        self.assertEqual(names, ["contrast", "counter", "table", "byte_says",
                                 "close"])
        self.assertEqual(groups[2][2], ["b4", "b5", "b6", "b7"])

    def test_scene_names_in_tests_match_the_real_catalog(self):
        try:
            from worker.scenes import NAMES
        except Exception as e:                       # noqa: BLE001
            self.skipTest(f"render bagimliliklari yok: {e}")
        self.assertEqual(set(NAMES), set(SCENES))
        from worker.themes import NAMES as T
        self.assertEqual(set(T), set(THEMES))
        self.assertEqual(set(roles.THEME_DOC), set(THEMES))


if __name__ == "__main__":
    unittest.main()
