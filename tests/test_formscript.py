"""
Kolay form -> senaryo (editorial/formscript.py). AG YOK.

Sozlesme: formdan cikan senaryo AYNI kapidan (editorial.authored.problems) gecmeli; kapidan
gecmeyecek bir form ise acik bir sorunla geri donmeli. Panelin on kontrolu (panel/bytepanel/scripts.py)
formscript ile ayni sinirlari kullanmali: ikisi birbirinden ayrilirsa burada kirilir.
"""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

from editorial import authored, formscript as F, rules
from publish import manifest as M
from tests.fixtures import SCENES, story_form

ROOT = Path(__file__).resolve().parent.parent
BRAND = M.load_brand(ROOT)


def gate(spec):
    return authored.problems(spec, SCENES, BRAND, f"{spec['id']}.json")


def with_beats(n, form=None):
    """story_form'u n cumleye getirir (10-14): orta cumleler kopyalanir, rakamsiz."""
    form = copy.deepcopy(form or story_form())
    beats = form["beats"]
    while len(beats) < n:
        k = len(beats)
        beats.insert(4, {"say": f"Another plain step number {'abcdefghij'[k % 10]}.",
                         "cap": f"Plain step {'abcdefghij'[k % 10]}", "kw": "", "mark": ""})
    while len(beats) > n:
        del beats[4]
    return form


class Compile(unittest.TestCase):
    def test_the_sample_form_compiles_and_passes_the_gate(self):
        spec, probs = F.compile_form(story_form(), 48, "2026-11-13")
        self.assertEqual(probs, [])
        self.assertEqual(gate(spec), [])
        self.assertEqual(spec["id"], "p048-youtube-started-as-a-video-dating-site")
        self.assertEqual(spec["authored"], {"by": "panel", "date": "2026-11-13"})
        self.assertEqual((spec["series"], spec["lang"], spec["format"]), ("G", "en", "story"))

    def test_the_id_fits_the_queue_pattern_the_panel_and_pick_script_use(self):
        import re
        spec, _ = F.compile_form(story_form(), 7, "2026-11-13")
        self.assertRegex(spec["id"], r"^p\d{3}-[a-z0-9-]+\Z")
        self.assertTrue(spec["id"].startswith("p007-"))
        self.assertLessEqual(len(spec["id"]), 80)
        for title in ("Über-cool: 5 Ünïcode ✓ Başlık!", "!!!", "x" * 60):
            f = story_form()
            f["title"] = title
            s, p = F.compile_form(f, 12, "2026-11-13")
            self.assertEqual(p, [], title)
            self.assertTrue(re.match(r"^p012-[a-z0-9-]+\Z", s["id"]), s["id"])

    def test_it_is_deterministic(self):
        a = F.compile_form(story_form(), 50, "2026-11-13")
        b = F.compile_form(copy.deepcopy(story_form()), 50, "2026-11-13")
        self.assertEqual(json.dumps(a), json.dumps(b))

    def test_every_beat_count_from_ten_to_fourteen_passes_the_gate(self):
        for n in range(F.BEATS_MIN, F.BEATS_MAX + 1):
            spec, probs = F.compile_form(with_beats(n), 60, "2026-11-13")
            self.assertEqual(probs, [], n)
            self.assertEqual(len(spec["beats"]), n)
            self.assertEqual(gate(spec), [], n)
            roles = [b["role"] for b in spec["beats"]]
            self.assertEqual((roles[0], roles.count("hook"), roles[-1]), ("hook", 1, "resolve"))

    def test_no_scene_stays_on_screen_for_more_than_three_beats(self):
        for n in range(F.BEATS_MIN, F.BEATS_MAX + 1):
            spec, _ = F.compile_form(with_beats(n), 60, "2026-11-13")
            at = [i for i, b in enumerate(spec["beats"]) if b.get("scene")] + [n]
            gaps = [b - a for a, b in zip(at, at[1:])]
            self.assertLessEqual(max(gaps), F.MAX_STATIC, (n, at))

    def test_a_form_without_numbers_or_dates_still_gets_four_distinct_scenes(self):
        f = story_form()
        for b in f["beats"]:
            b["cap"] = "".join(c for c in b["cap"] if not c.isdigit()).replace("$", "").replace("M+", "")
            b["kw"] = ""
            b["mark"] = ""
        f["facts"] = [dict(x, text=x["text"] + " ") for x in f["facts"]]
        spec, probs = F.compile_form(f, 60, "2026-11-13")
        self.assertEqual(probs, [])
        self.assertGreaterEqual(len({b["scene"] for b in spec["beats"] if b.get("scene")}), 4)
        self.assertEqual(gate(spec), [])

    def test_first_scene_is_a_title_and_last_is_a_close(self):
        spec, _ = F.compile_form(story_form(), 48, "2026-11-13")
        self.assertEqual(spec["beats"][0]["scene"], "title")
        self.assertEqual(spec["beats"][-1]["scene"], "close")

    def test_counters_skip_numbers_inside_dates_and_prefer_units(self):
        spec, _ = F.compile_form(story_form(), 48, "2026-11-13")
        counters = {b["id"]: b["data"] for b in spec["beats"] if b.get("scene") == "counter"}
        self.assertTrue(counters)
        for d in counters.values():
            self.assertNotIn(d["to"], (14, 2005, 2006))
        self.assertEqual(F.counter_token("Google: $1.65 billion, Oct 2006")[0]["prefix"], "$")
        self.assertEqual(F.counter_token("Feb 14, 2005"), None)
        self.assertEqual(F.counter_token("In 2026"), None)
        self.assertEqual(F.counter_token("3 steps"), None)
        self.assertEqual(F.counter_token("100M+ views")[0]["suffix"], "M+")
        self.assertEqual(F.counter_token("1,500 users")[0]["to"], 1500)

    def test_dates_become_a_timeline_when_three_or_more_beats_have_one(self):
        spec, _ = F.compile_form(story_form(), 48, "2026-11-13")
        tl = [b for b in spec["beats"] if b.get("scene") == "timeline"]
        self.assertEqual(len(tl), 1)
        steps = tl[0]["data"]["steps"]
        self.assertGreaterEqual(len(steps), 3)
        for s in steps:
            self.assertLessEqual(len(s["at"]), 12)
            self.assertLessEqual(len(s["label"]), 26)
        self.assertEqual(F.date_label("Domain registered: Feb 14, 2005")[0], "Feb 14, 2005")
        self.assertEqual(F.date_label("September 2006: launch")[0], "Sep 2006")
        self.assertEqual(F.date_label("in 1999")[0], "1999")
        self.assertIsNone(F.date_label("no date here"))

    def test_every_screen_number_gets_a_claim_from_a_fact_with_its_source_and_note(self):
        spec, _ = F.compile_form(story_form(), 48, "2026-11-13")
        by = {c["shown"]: c for c in spec["claims"]}
        self.assertEqual(by["1.65"]["source"], 1)               # 2. kaynak -> indeks 1
        self.assertEqual(by["14"]["source"], 0)
        self.assertIn("Google press release", by["100"]["note"])
        self.assertTrue(all(c["note"] for c in spec["claims"]))

    def test_calc_rows_become_formula_claims_the_gate_checks(self):
        f = story_form()
        f["beats"][4].update(cap="About 750 MB raw", kw="")
        f["calcs"] = [{"shown": "750", "expr": "3*10**9*2/8/10**6"}]
        spec, probs = F.compile_form(f, 48, "2026-11-13")
        self.assertEqual(probs, [])
        self.assertEqual(gate(spec), [])
        self.assertIn({"shown": "750", "expr": "3*10**9*2/8/10**6", "value": 750.0, "source": None},
                      spec["claims"])
        f["calcs"] = [{"shown": "750", "expr": "3*10**9*2/8/10**5"}]       # sonuc tutmuyor
        _, probs = F.compile_form(f, 48, "2026-11-13")
        self.assertTrue(any("hesap 1" in p for p in probs), probs)
        f["calcs"] = [{"shown": "abc", "expr": "__import__('os')"}]
        _, probs = F.compile_form(f, 48, "2026-11-13")
        self.assertTrue(any("hesap 1" in p for p in probs), probs)

    def test_hashtags_and_copy_follow_the_brand_rules(self):
        spec, _ = F.compile_form(story_form(), 48, "2026-11-13")
        tags = spec["copy_parts"]["hashtags"]
        self.assertEqual(tags["youtube"][0], "#tech")
        self.assertLessEqual(len(tags["tiktok"]), 2)
        for plat, lst in tags.items():
            self.assertLessEqual(len(lst), M.LIMITS[plat])
            self.assertTrue(all(M.HASHTAG.match(t) for t in lst), lst)
        self.assertEqual(spec["copy_parts"]["tiktok"]["caption"], spec["title"])
        self.assertEqual(F.hashtags(["!!", "ai tools", "Ünï"])["youtube"], ["#tech", "#aitools"])


class Rejections(unittest.TestCase):
    def problems(self, mutate, number=48):
        f = story_form()
        mutate(f)
        spec, probs = F.compile_form(f, number, "2026-11-13")
        return spec, probs

    def test_a_number_on_screen_that_no_fact_mentions_is_refused_with_a_hint(self):
        def m(f):
            f["beats"][5]["cap"] = "Dec 2005: 37M views a day"
        spec, probs = self.problems(m)
        self.assertIsNone(spec)
        self.assertTrue(any("37" in p and "olay" in p for p in probs), probs)

    def test_an_unused_source_is_refused(self):
        def m(f):
            f["sources"].append("https://example.com/unused")
        _, probs = self.problems(m)
        self.assertTrue(any("kaynak 3" in p for p in probs), probs)

    def test_counts_and_limits(self):
        cases = [
            (lambda f: [f["beats"].pop() for _ in range(3)], "cumle"),
            (lambda f: f["beats"].extend(copy.deepcopy(f["beats"][:3])), "cumle"),
            (lambda f: f.update(title=""), "baslik"),
            (lambda f: f.update(title="x" * 61), "baslik"),
            (lambda f: f.update(format="trend"), "bicim"),
            (lambda f: f.update(theme="neon"), "tema"),
            (lambda f: f.update(description="kisa"), "aciklama"),
            (lambda f: [f["sources"].pop(), f["facts"].__setitem__(slice(None), f["facts"][:3])], "kaynak"),
            (lambda f: f["sources"].__setitem__(0, "http://insecure.example.com/x"), "https"),
            (lambda f: f["sources"].__setitem__(1, f["sources"][0]), "tekrar"),
            (lambda f: f["facts"].__setitem__(slice(None), f["facts"][:1]), "dogrulanan olay"),
            (lambda f: f["facts"][0].update(source=9), "kaynak no"),
            (lambda f: f["facts"][0].update(note=""), "not"),
            (lambda f: f["beats"][2].update(cap="x" * 49), "ekran yazisi"),
            (lambda f: f["beats"][2].update(say=""), "say"),
            (lambda f: f["beats"][2].update(mark="boom"), "isaret"),
        ]
        for mutate, word in cases:
            spec, probs = self.problems(mutate)
            self.assertIsNone(spec)
            self.assertTrue(any(word in p for p in probs), (word, probs))

    def test_what_normalize_lets_through_but_the_gate_must_catch_is_caught(self):
        """Mekanik kurallar kapida: formscript onlari cogaltmaz, sonuc kapidan donmeli."""
        cases = [
            (lambda f: f["beats"][1].update(say="It cost 5 dollars."), "rakam"),
            (lambda f: f["beats"][0].update(say="Is this a question about the first sentence?"), "hook"),
            (lambda f: f["beats"][1].update(say="Subscribe to the channel now."), "yasakli"),
            (lambda f: f["beats"][4].update(kw="not in the caption"), "kw"),
            (lambda f: f["beats"][4].update(say=" ".join(["word"] * 20)), "kelime"),
        ]
        for mutate, word in cases:
            f = story_form()
            mutate(f)
            spec, probs = F.compile_form(f, 48, "2026-11-13")
            self.assertEqual(probs, [], word)
            self.assertTrue(any(word in p for p in gate(spec)), (word, gate(spec)))

    def test_control_characters_and_curly_quotes_are_cleaned(self):
        f = story_form()
        f["title"] = "YouTube\x00 started’s a video\n dating site"
        f["beats"][1]["cap"] = "“Tagline”: Tune in, hook up"
        spec, probs = F.compile_form(f, 48, "2026-11-13")
        self.assertEqual(probs, [])
        self.assertNotIn("\x00", json.dumps(spec))
        self.assertEqual(spec["beats"][1]["cap"], '"Tagline": Tune in, hook up')

    def test_non_dict_forms_and_junk_rows_do_not_crash(self):
        for junk in (None, [], "x", 5, {"beats": "nope", "sources": 3, "facts": {"a": 1}}):
            spec, probs = F.compile_form(junk, 1, "2026-11-13")
            self.assertIsNone(spec)
            self.assertTrue(probs)
        f = story_form()
        f["beats"] += [None, 3, {}, {"say": "", "cap": ""}]
        f["facts"] += [None, {}, {"text": "", "note": "", "source": ""}]
        spec, probs = F.compile_form(f, 48, "2026-11-13")
        self.assertEqual(probs, [])
        self.assertEqual(len(spec["beats"]), 12)

    def test_number_out_of_range_is_refused(self):
        for n in (0, 1000):
            self.assertTrue(F.compile_form(story_form(), n, "2026-11-13")[1])


@unittest.skipUnless((ROOT / "panel" / "bytepanel" / "scripts.py").exists(), "panel kodu yok")
class PanelPrecheckAgrees(unittest.TestCase):
    """Panelin on kontrolu (Docker imajinda editorial yok, kendi kopyasi var) ayni sinirlari tasimali."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("panel_scripts_mod", ROOT / "panel" / "bytepanel" / "scripts.py")
        cls.P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.P)

    def test_the_limits_are_the_same_numbers(self):
        P = self.P
        self.assertEqual((P.BEATS_MIN, P.BEATS_MAX), (F.BEATS_MIN, F.BEATS_MAX))
        self.assertEqual((P.SOURCES_MIN, P.SOURCES_MAX), (F.SOURCES_MIN, F.SOURCES_MAX))
        self.assertEqual((P.FACTS_MIN, P.FACTS_MAX), (F.FACTS_MIN, F.FACTS_MAX))
        self.assertEqual(P.CALCS_MAX, F.CALCS_MAX)
        self.assertEqual(P.LIMIT, F.LIMIT)
        self.assertEqual(P.FORMATS, F.FORMATS)
        self.assertEqual(P.THEMES, F.THEMES)
        self.assertEqual(P.MARKS, F.MARKS)
        self.assertEqual((P.KW_MAX, P.MAX_BEAT_WORDS, P.MAX_HOOK_WORDS, P.MAX_SECONDS, P.WORDS_PER_SEC, P.GAP),
                         (rules.KW_MAX, rules.MAX_BEAT_WORDS, rules.MAX_HOOK_WORDS, rules.MAX_SECONDS,
                          rules.WORDS_PER_SEC, rules.GAP))
        self.assertEqual(P.KW_OK.pattern, rules.KW_OK.pattern)
        self.assertEqual(list(P.BANNED), rules.BANNED)

    def test_what_the_panel_accepts_the_compiler_and_the_gate_accept(self):
        form = story_form()
        self.assertEqual(self.P.precheck(form), [])
        spec, probs = F.compile_form(form, 48, "2026-11-13")
        self.assertEqual((probs, gate(spec)), ([], []))

    def test_what_the_panel_refuses_the_gate_would_have_refused(self):
        cases = [
            lambda f: f["beats"][1].update(say="It cost 5 dollars."),
            lambda f: f["beats"][0].update(say="Is this a question about the first sentence?"),
            lambda f: f["beats"][1].update(say="Subscribe to the channel now."),
            lambda f: f["beats"][4].update(kw="not in the caption"),
            lambda f: f["beats"][4].update(say=" ".join(["word"] * 20)),
            lambda f: f["beats"][4].update(kw="x" * 19),
            lambda f: f["beats"][4].update(kw="çayır"),
        ]
        for mutate in cases:
            f = story_form()
            mutate(f)
            self.assertTrue(self.P.precheck(f), f)
            spec, probs = F.compile_form(f, 48, "2026-11-13")
            self.assertTrue(probs or gate(spec), f)


if __name__ == "__main__":
    unittest.main()
