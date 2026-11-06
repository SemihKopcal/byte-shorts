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
        self.timeouts = []

    def __call__(self, method, url, key, body=None, timeout=120):
        self.calls.append((method, url, body))
        self.timeouts.append(timeout)
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

    def test_overloaded_model_rests_so_later_calls_skip_it(self):
        # canli kosuda: yazar, editor, metin ayni bozuk modele bastan vuruyordu
        s = Stub([models("gemini-3.8-flash", "gemini-3.7-flash"),
                  (503, {}), (503, {}), (503, {}), ok("a"), ok("b")])
        g = gem(s)
        self.assertEqual(g.ask("x", json_mode=False), "a")
        self.assertEqual(g.model, "gemini-3.7-flash")
        self.assertEqual(g.ask("y", json_mode=False), "b")
        urls = [c[1] for c in s.calls if c[0] == "POST"]
        self.assertEqual(sum("3.8-flash" in u for u in urls), 3)    # sadece ilk rolde
        self.assertEqual(sum("3.7-flash" in u for u in urls), 2)

    def test_503_gets_two_retries_not_four(self):
        s = Stub([models("gemini-3.8-flash", "gemini-3.7-flash")]
                 + [(503, {})] * 3 + [ok("fine")])
        g = gem(s)
        self.assertEqual(g.ask("x", json_mode=False), "fine")
        self.assertEqual(sum("3.8-flash" in c[1] for c in s.calls), 3)

    def test_unproven_model_that_times_out_is_dropped_at_once(self):
        # hic cevap vermemis modelde tek zaman asimi yeter: en kotu 45 sn
        s = Stub([models("gemini-3.8-flash", "gemini-3.7-flash"),
                  (0, {"error": {"message": "timed out"}}), ok("fine")])
        g = gem(s)
        self.assertEqual(g.ask("x", json_mode=False), "fine")
        self.assertEqual(g.model, "gemini-3.7-flash")
        self.assertEqual(sum("3.8-flash" in c[1] for c in s.calls), 1)

    def test_proven_model_gets_a_second_attempt_after_a_timeout(self):
        s = Stub([models("gemini-3.8-flash"), ok("a"),
                  (0, {}), ok("b")])
        g = gem(s)
        g.ask("x", json_mode=False)
        self.assertEqual(g.ask("y", json_mode=False), "b")
        self.assertEqual(g.model, "gemini-3.8-flash")

    def test_first_request_to_an_unproven_model_uses_the_short_timeout(self):
        s = Stub([models("gemini-3.8-flash"), ok("a"), ok("b")])
        g = gem(s)
        g.timeout = 60
        g.ask("x", json_mode=False)
        g.ask("y", json_mode=False)
        posts = [to for c, to in zip(s.calls, s.timeouts) if c[0] == "POST"]
        self.assertEqual(posts, [L.FIRST_TIMEOUT, 60])

    def test_all_models_resting_still_tries_again(self):
        s = Stub([(503, {})] * 3 + [ok("recovered")])
        g = gem(s)
        g._cands = ["gemini-3.8-flash"]          # tek model, liste cagrisi yok
        self.assertIsNone(g.ask("x", json_mode=False))
        self.assertEqual(g.candidates(), ["gemini-3.8-flash"])   # dinleniyor ama
        self.assertEqual(g.ask("y", json_mode=False), "recovered")  # denenir

    def test_deadline_stops_everything(self):
        s = Stub([models("gemini-3.8-flash", "gemini-3.7-flash")]
                 + [(503, {})] * 60)
        g = gem(s)
        g.deadline = 6                      # sahte saat: cagri basina 2 tik
        self.assertIsNone(g.ask("x", json_mode=False))
        self.assertLess(len(s.calls), 8)
        self.assertIsNone(g.ask("y", json_mode=False))   # tavan kalici

    def test_request_timeout_is_passed_to_transport(self):
        s = Stub([models("gemini-3.8-flash"), ok("x")])
        g = gem(s)
        g.timeout = 33
        g.ask("x", json_mode=False)
        self.assertEqual(set(s.timeouts), {33})

    def test_warm_picks_the_first_healthy_model_and_prefers_it(self):
        s = Stub([models("gemini-3.8-flash", "gemini-3.7-flash"),
                  (503, {}), ok("ready"), ok("answer")])
        g = gem(s)
        self.assertEqual(g.warm(), "gemini-3.7-flash")
        self.assertEqual(g.model, "gemini-3.7-flash")
        self.assertNotIn("gemini-3.8-flash", g.candidates())     # dinleniyor
        self.assertEqual(g.ask("x", json_mode=False), "answer")  # dogrudan saglikliya
        self.assertEqual([c[1].split("/models/")[-1].split(":")[0]
                          for c in s.calls if c[0] == "POST"],
                         ["gemini-3.8-flash", "gemini-3.7-flash",
                          "gemini-3.7-flash"])

    def test_warm_drops_models_without_quota_or_gone(self):
        s = Stub([models("gemini-3.8-flash", "gemini-3.7-flash",
                         "gemini-3.6-flash"),
                  quota("zero"), (404, {"error": {"message": "gone"}}),
                  ok("ready")])
        g = gem(s)
        self.assertEqual(g.warm(), "gemini-3.6-flash")
        self.assertNotIn("gemini-3.8-flash", g.candidates())
        self.assertNotIn("gemini-3.7-flash", g.candidates())
        # kotasi olmayan ve 404 veren KALICI elenir (dinlenmez)
        self.assertEqual(g._dead, {"gemini-3.8-flash", "gemini-3.7-flash"})
        self.assertEqual(set(g.reasons), {"gemini-3.8-flash", "gemini-3.7-flash"})

    def test_models_that_answered_this_run_come_first(self):
        s = Stub([models("gemini-3.8-flash", "gemini-2.5-flash")])
        g = gem(s)
        self.assertEqual(g.candidates()[0], "gemini-3.8-flash")
        g._proven.add("gemini-2.5-flash")
        self.assertEqual(g.candidates()[0], "gemini-2.5-flash")

    def test_warm_gives_up_with_reasons_and_bounded_calls(self):
        s = Stub([models("gemini-3.8-flash", "gemini-3.7-flash")]
                 + [(503, {"error": {"message": "overloaded"}})] * 30)
        g = gem(s)
        self.assertIsNone(g.warm(limit=3))
        self.assertLessEqual(len(s.calls), 4)                  # liste + 3 yoklama
        self.assertIn("overloaded", g.reasons["gemini-3.8-flash"])

    def test_probe_is_one_small_request_with_short_timeout(self):
        s = Stub([ok("ready")])
        g = gem(s)
        st, _, _ = g.probe("gemini-3.8-flash")
        self.assertEqual(st, 200)
        self.assertEqual(s.timeouts, [L.PING_TIMEOUT])
        self.assertLessEqual(s.calls[0][2]["generationConfig"]["maxOutputTokens"], 64)

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


class GeminiCheckTool(unittest.TestCase):
    def row(self, name, ok_, grounded=None):
        mk = lambda o: {"model": name, "ok": o, "secs": 1.0,
                        "why": "" if o else "503: busy"}
        return {"model": name, "plain": mk(ok_),
                "grounded": None if grounded is None else mk(grounded)}

    def test_recommend_first_healthy_with_search(self):
        from tools import gemini_check as C
        best, why = C.recommend([self.row("a", False), self.row("b", True, True),
                                 self.row("c", True, True)])
        self.assertEqual(best, "b")
        self.assertIn("GEMINI_MODEL=b", why)            # onundeki "a" bozuk
        self.assertIn("1 model", why)
        best, why = C.recommend([self.row("a", True, True), self.row("b", True, True)])
        self.assertEqual(best, "a")
        self.assertIn("bir sey yapmana gerek yok", why)

    def test_recommend_no_search_anywhere_still_suggests_pinning(self):
        from tools import gemini_check as C
        best, why = C.recommend([self.row("x", False), self.row("y", False),
                                 self.row("z", True, False),
                                 self.row("w", True, False)])
        self.assertEqual(best, "z")
        self.assertIn("hicbir modelde arama yok", why)
        self.assertIn("GEMINI_MODEL=z", why)
        self.assertIn("2 model", why)

    def test_recommend_prefers_a_model_with_search(self):
        from tools import gemini_check as C
        best, why = C.recommend([self.row("a", True, False),
                                 self.row("b", True, True)])
        self.assertEqual(best, "b")
        self.assertIn("GEMINI_MODEL=b", why)

    def test_recommend_nothing_works(self):
        from tools import gemini_check as C
        best, why = C.recommend([self.row("a", False), self.row("b", False)])
        self.assertIsNone(best)
        self.assertIn("HICBIR", why)

    def test_render_marks_missing_search(self):
        from tools import gemini_check as C
        out = C.render([self.row("a", True, False)])
        self.assertIn("| a | evet | 1.0 | YOK |", out)


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
    def run_pipeline(self, replies, grounded=True, scripts=(), llm_cls=FakeLLM,
                     **kw):
        with tempfile.TemporaryDirectory() as tmp:
            root = root_with_content(tmp)
            for name, body in scripts:
                (root / "content/scripts" / name).write_text(json.dumps(body))
            llm = llm_cls(replies)
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

    def test_main_stops_at_once_when_no_model_answers_the_ping(self):
        import contextlib
        import io
        from unittest import mock

        class Dead:
            reasons = {"gemini-3.8-flash": "503: overloaded"}

            def __init__(self, key):
                pass

            def warm(self):
                return None

        err = io.StringIO()
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch.object(pipeline, "Gemini", Dead), \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                pipeline.main(["--dry-run"])
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("BUGUN VIDEO YOK", err.getvalue())
        self.assertIn("overloaded", err.getvalue())

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


    STORY = "the week a support bot promised refunds it could not give"

    def two_candidates(self):
        story = copy.deepcopy(cands()["candidates"][0])
        story.update(format="story", angle=self.STORY)
        story["scores"]["curiosity"] = 10                # ilk sirada olsun
        measured = copy.deepcopy(cands()["candidates"][0])
        measured["format"] = "measured"
        return {"candidates": [story, measured]}

    def searchless_replies(self):
        return {"yapimci": [self.two_candidates()], "yazar": [good_spec()],
                "editor": [review("publish", 8)],
                "dogrulayici": [{"results": [{"shown": "$0.40",
                                              "status": "confirmed"}]}],
                "sanat": [{"theme": "ember"}], "metin": [copy_parts()]}

    def test_with_search_the_story_candidate_is_tried_first(self):
        _, llm, *_ = self.run_pipeline(self.searchless_replies())
        first = [p for r, p in llm.log if r == "yazar"][0]
        self.assertIn(self.STORY, first)

    def test_without_search_story_and_trend_candidates_are_skipped(self):
        class NoSearch(FakeLLM):
            def search_ok(self):
                return False
        spec, llm, *_, err = self.run_pipeline(self.searchless_replies(),
                                               llm_cls=NoSearch)
        self.assertIsNone(err)
        self.assertEqual(spec["brief"]["format"], "measured")
        prompts = [p for r, p in llm.log if r == "yazar"]
        self.assertEqual(len(prompts), 1)               # tek yazar cagrisi
        self.assertFalse(any(self.STORY in p for p in prompts))

    def test_without_search_and_only_story_candidates_falls_back_to_backlog(self):
        class NoSearch(FakeLLM):
            def search_ok(self):
                return False
        only = self.two_candidates()
        only["candidates"] = only["candidates"][:1]
        rep = self.searchless_replies()
        rep["yapimci"] = [only]
        spec, llm, *_, err = self.run_pipeline(rep, llm_cls=NoSearch)
        self.assertIsNone(err)
        first = [p for r, p in llm.log if r == "yazar"][0]
        self.assertIn("UTF-8", first)                   # yedek havuzdaki olcum
        self.assertNotIn(self.STORY, first)

    def reject_then_publish(self):
        rep = self.searchless_replies()
        rep["editor"] = [review("reject", 4), review("publish", 8)]
        rep["yapimci"] = [{"candidates": [self.two_candidates()["candidates"][1]]}]
        return rep

    def test_one_rejected_candidate_falls_through_to_the_backlog(self):
        spec, llm, files, rej, err = self.run_pipeline(self.reject_then_publish())
        self.assertIsNone(err)
        prompts = [p for r, p in llm.log if r == "yazar"]
        self.assertEqual(len(prompts), 2)
        self.assertIn("UTF-8", prompts[1])              # ikinci deneme yedekten
        self.assertEqual(files, [spec["id"] + ".json"])

    def test_no_search_note_reaches_producer_and_writer(self):
        class NoSearch(FakeLLM):
            def search_ok(self):
                return False
        _, llm, *_ = self.run_pipeline(self.searchless_replies(),
                                       llm_cls=NoSearch)
        prod = [p for r, p in llm.log if r == "yapimci"][0]
        wr = [p for r, p in llm.log if r == "yazar"][0]
        self.assertIn("WEB SEARCH IS OFF", prod)
        self.assertIn("WEB SEARCH IS OFF", wr)
        _, llm, *_ = self.run_pipeline(self.searchless_replies())
        self.assertNotIn("WEB SEARCH IS OFF",
                         [p for r, p in llm.log if r == "yapimci"][0])
        self.assertNotIn("WEB SEARCH IS OFF",
                         [p for r, p in llm.log if r == "yazar"][0])

    def test_manual_topic_without_search_also_gets_the_note(self):
        class NoSearch(FakeLLM):
            def search_ok(self):
                return False
        rep = self.searchless_replies()
        _, llm, *_ = self.run_pipeline(rep, llm_cls=NoSearch,
                                       topic="pixels in a short")
        self.assertIn("WEB SEARCH IS OFF",
                      [p for r, p in llm.log if r == "yazar"][0])

    def test_main_warms_then_checks_search_before_running(self):
        from unittest import mock
        order = []

        class G:
            reasons = {}
            model = "m"

            def __init__(self, key):
                pass

            def warm(self):
                order.append("warm")
                return "m"

            def check_search(self):
                order.append("check_search")
                return False

        def fake_run(llm, **kw):
            order.append("run")
            raise pipeline.Failure("test")

        env = {"GEMINI_API_KEY": "k"}
        with mock.patch.object(pipeline, "Gemini", G), \
                mock.patch.object(pipeline, "run", fake_run), \
                mock.patch.dict("os.environ", env):
            with self.assertRaises(SystemExit):
                pipeline.main([])
        self.assertEqual(order, ["warm", "check_search", "run"])

    def test_main_stops_when_no_model_answers_and_never_checks_search(self):
        from unittest import mock
        order = []

        class G:
            reasons = {"m": "503: busy"}

            def __init__(self, key):
                pass

            def warm(self):
                order.append("warm")
                return None

            def check_search(self):
                order.append("check_search")

        with mock.patch.object(pipeline, "Gemini", G), \
                mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}):
            with self.assertRaises(SystemExit):
                pipeline.main([])
        self.assertEqual(order, ["warm"])

    def lookups(self, n):
        return [{"shown": f"${i + 5}.50", "source": 0} for i in range(n)]

    def test_hopeless_topic_skips_the_revision_rounds(self):
        n = pipeline.ALLOW_UNVERIFIED + pipeline.HOPELESS + 1
        rep = self.searchless_replies()
        rep["editor"] = [review("revise", 8, fixes=["x"],
                                claims=self.lookups(n))]
        rep["yapimci"] = [{"candidates": [self.two_candidates()["candidates"][1]]}]
        spec, llm, files, rej, err = self.run_pipeline(
            rep, grounded=False, topic=None)
        roles_used = [r for r, _ in llm.log]
        self.assertEqual(roles_used.count("yazar-duzeltme"), 0)   # revizyon yok
        self.assertEqual(roles_used.count("editor"), 2)           # 2 konu, tur 0
        self.assertEqual(len(rej), 2)

    def test_few_unverified_statements_still_get_revised(self):
        n = pipeline.ALLOW_UNVERIFIED + 2
        rep = self.searchless_replies()
        rep["editor"] = [review("revise", 8, fixes=["x"], claims=self.lookups(n)),
                         review("publish", 8)]
        rep["yapimci"] = [{"candidates": [self.two_candidates()["candidates"][1]]}]
        rep["yazar-duzeltme"] = [good_spec()]
        spec, llm, *_, err = self.run_pipeline(rep, grounded=False)
        roles_used = [r for r, _ in llm.log]
        self.assertGreaterEqual(roles_used.count("yazar-duzeltme"), 1)

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


# ═══ ucretsiz anahtar: Semih'in gemini-check tablosu (6 Kasim 2026) ═════
HIS_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
              "gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite",
              "gemini-3.1-flash-lite", "gemini-2.5-flash-lite",
              "gemini-3-flash-preview", "gemini-2.5-flash-preview-tts",
              "gemini-flash-latest", "gemini-2.0-flash"]


class FreeTierTransport:
    """Gercek tablo: 3.8/3.7/latest 503 (asiri yuklu); 2.x 404; digerleri
    aramasiz 200, ARAMALI istek 429 -- ve o 429 DUZ bir kota mesaji: ne
    QuotaFailure ne 'limit: 0' ne 'search' kelimesi var (tabloda kind bos)."""

    def __init__(self, grounded_ok=()):
        self.calls = []
        self.grounded_ok = set(grounded_ok)

    def __call__(self, method, url, key, body=None, timeout=120):
        if method == "GET":
            return models(*HIS_MODELS)
        model = url.split("/models/")[1].split(":")[0]
        grounded = bool((body or {}).get("tools"))
        self.calls.append((model, grounded))
        if model in ("gemini-3.8-flash", "gemini-3.7-flash",
                     "gemini-flash-latest"):
            return 503, {"error": {"message": "This model is currently "
                                   "experiencing high demand."}}
        if model.startswith(("gemini-2.5", "gemini-2.0")):
            return 404, {"error": {"message": f"models/{model} is no longer "
                                   "available to new users."}}
        if grounded and model not in self.grounded_ok:
            return 429, {"error": {"code": 429, "message":
                                   "You exceeded your current quota, please "
                                   "check your plan and billing details."}}
        return ok(json.dumps({"candidates": [], "ready": True}))


class FreeTierKey(unittest.TestCase):
    def client(self, **kw):
        sleeps, logs = [], []
        stub = FreeTierTransport(**kw)
        return gem(stub, sleeps, logs), stub, sleeps, logs

    def test_tts_and_image_models_are_never_candidates(self):
        names = L.rank_models(models(*HIS_MODELS, "gemini-2.5-flash-image",
                                     "gemini-3-flash-live")[1]["models"])
        self.assertNotIn("gemini-2.5-flash-preview-tts", names)
        self.assertEqual(names[:3], ["gemini-3.8-flash", "gemini-3.7-flash",
                                     "gemini-3.6-flash"])
        self.assertIn("gemini-3-flash-preview", names)

    def test_search_429_without_details_does_not_burn_the_run(self):
        llm, stub, sleeps, logs = self.client()
        llm._cands = ["gemini-3.6-flash", "gemini-3.5-flash"]   # 503'ler atlandi
        out = llm.ask("x", grounded=True, role="yapimci")
        self.assertIsNotNone(out)
        self.assertEqual(llm.model, "gemini-3.6-flash")
        self.assertFalse(llm.last_grounded)             # aramasiz: kod fail-closed
        self.assertEqual(sleeps, [])                    # HIC bekleme yok
        self.assertEqual(stub.calls, [("gemini-3.6-flash", True),
                                      ("gemini-3.6-flash", False)])
        self.assertEqual(llm._dead, set())
        self.assertEqual(llm._cool, {})                 # dinlendirilmedi
        self.assertTrue(any("arama araci" in m for m in logs))

    def test_search_is_not_retried_for_the_rest_of_the_run(self):
        llm, stub, sleeps, _ = self.client()
        llm._cands = ["gemini-3.6-flash"]
        for role in ("yapimci", "dogrulayici", "dogrulayici"):
            self.assertIsNotNone(llm.ask("x", grounded=True, role=role))
        self.assertEqual(sum(1 for _, g in stub.calls if g), 1)   # tek deneme
        self.assertEqual(len(stub.calls), 4)
        self.assertEqual(sleeps, [])

    def test_search_still_used_when_a_model_supports_it(self):
        llm, stub, _, _ = self.client(grounded_ok={"gemini-3.6-flash"})
        llm._cands = ["gemini-3.6-flash"]
        self.assertIsNotNone(llm.ask("x", grounded=True))
        self.assertTrue(llm.last_grounded)
        self.assertEqual(stub.calls, [("gemini-3.6-flash", True)])

    def test_real_rate_limit_is_not_mistaken_for_missing_search(self):
        # model GERCEKTEN hiz siniri veriyorsa aramasiz da 429 doner: arama
        # "yok" diye isaretlenmez, bekleyip aramayla tekrar denenir
        seq = [quota("rate", 3), quota("rate", 3), ok("{}")]
        st = Stub(seq)
        sleeps = []
        llm = gem(st, sleeps)
        llm._cands = ["m"]
        self.assertIsNotNone(llm.ask("x", grounded=True))
        self.assertEqual(llm._no_search, set())
        self.assertEqual(sleeps, [5])                  # yalniz 1 bekleme
        self.assertEqual(len(st.calls), 3)

    def test_warm_skips_overloaded_models_and_settles_on_the_first_healthy(self):
        llm, stub, _, _ = self.client()
        self.assertEqual(llm.warm(), "gemini-3.6-flash")
        self.assertEqual([m for m, _ in stub.calls],
                         ["gemini-3.8-flash", "gemini-3.7-flash",
                          "gemini-3.6-flash"])

    def test_check_search_tells_the_run_up_front(self):
        llm, stub, sleeps, logs = self.client()
        self.assertEqual(llm.warm(), "gemini-3.6-flash")
        self.assertFalse(llm.check_search())
        self.assertFalse(llm.search_ok())
        self.assertEqual(stub.calls[-1], ("gemini-3.6-flash", True))
        self.assertTrue(any("kapali" in m for m in logs))
        self.assertEqual(sleeps, [])

    def test_check_search_true_when_the_model_has_search(self):
        llm, *_ = self.client(grounded_ok={"gemini-3.6-flash"})
        llm.warm()
        self.assertTrue(llm.check_search())
        self.assertTrue(llm.search_ok())

    def test_check_search_unknown_counts_as_available(self):
        # 503/zaman asimi "arama yok" demek degildir
        st = Stub([ok("ready"), (503, {"error": {"message": "busy"}})])
        llm = gem(st)
        llm._cands = ["m"]
        self.assertEqual(llm.warm(), "m")
        self.assertTrue(llm.check_search())
        self.assertTrue(llm.search_ok())
        self.assertTrue(gem(Stub([])).check_search())     # model secilmemis

    def test_note_is_added_to_producer_and_writer_prompts(self):
        llm = FakeLLM({"yapimci": [{"candidates": []}], "yazar": [None]})
        roles.produce(llm, live="x", backlog=[], recent=[], today="2026-11-06",
                      search=False)
        roles.write(llm, {"angle": "a", "measure": "m", "search": False},
                    max_words=100)
        self.assertTrue(all("WEB SEARCH IS OFF" in p for _, p in llm.log))
        llm2 = FakeLLM({"yapimci": [{"candidates": []}], "yazar": [None]})
        roles.produce(llm2, live="x", backlog=[], recent=[], today="2026-11-06")
        roles.write(llm2, {"angle": "a", "measure": "m"}, max_words=100)
        self.assertFalse(any("WEB SEARCH IS OFF" in p for _, p in llm2.log))

    def test_producer_and_factcheck_work_on_this_key(self):
        llm, stub, sleeps, _ = self.client()
        llm._cands = ["gemini-3.6-flash"]
        spec = good_spec()
        lookups = [{"shown": "$0.40", "source": 0}]
        # yapimci: JSON gelir ama aday yok -> bos liste, cokme yok
        self.assertEqual(roles.produce(llm, live="(none)", backlog=[],
                                       recent=[], today="2026-11-06"), [])
        # dogrulayici: arama yok -> hicbir sey dogrulanmis sayilmaz
        problems, unverified, grounded = roles.factcheck(llm, spec, lookups)
        self.assertEqual((problems, unverified, grounded), ([], 1, False))
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
