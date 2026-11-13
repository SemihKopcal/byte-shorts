"""
Yazilmis (Gemini'siz) senaryolarin kapisi. AG YOK.

    python -m unittest discover -s tests -v
"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from editorial import authored
from publish import manifest as M
from tests.fixtures import CLAIMS, SCENES, copy_parts, good_spec
from tests.test_editorial import BRAND

SRC = ["https://example.com/veo-pricing", "https://example.org/price-table"]


def sample() -> dict:
    s = good_spec()
    s.update(
        id="p001-sample", series="G", lang="en", sources=list(SRC),
        claims=[{**c, "note": "price page lists $0.40 per second"}
                if not c.get("expr") else dict(c) for c in CLAIMS],
        facts=[], copy_parts=copy_parts(),
        authored={"by": "claude", "date": "2026-11-06"})
    # kaynak #1 de kullanilsin
    s["claims"].append({"shown": "$3", "expr": None, "value": None,
                        "source": 1, "note": "cheap model rate on the table"})
    s["claims"] = [c for c in s["claims"] if not (c["shown"] == "$3" and c.get("expr"))]
    return s


def story() -> dict:
    s = sample()
    s["format"] = "story"
    s["facts"] = [{"claim": "the bot launched on Twitter", "source": 0,
                   "note": "launch post"},
                  {"claim": "it was taken offline within a day", "source": 1,
                   "note": "company statement"}]
    return s


def check(spec, name="p001-sample.json"):
    return authored.problems(spec, SCENES, BRAND, name)


class Gate(unittest.TestCase):
    def test_a_good_script_passes(self):
        self.assertEqual(check(sample()), [])
        self.assertEqual(check(story()), [])

    def test_missing_fields_are_listed(self):
        s = sample()
        del s["claims"], s["authored"]
        p = check(s)
        self.assertIn("eksik alan: claims", p)
        self.assertIn("eksik alan: authored", p)

    def test_filename_must_match_id(self):
        self.assertTrue(any("ayni olmali" in x
                            for x in check(sample(), "p002-other.json")))

    def test_authored_block_needs_author_and_date(self):
        s = sample()
        s["authored"] = {"by": "claude", "date": "yesterday"}
        self.assertTrue(any("authored" in x for x in check(s)))

    def test_sources_must_be_https_urls_and_distinct(self):
        s = sample()
        s["sources"] = ["Veo public pricing page", SRC[1]]
        self.assertTrue(any("https" in x for x in check(s)))
        s = sample()
        s["sources"] = [SRC[0], SRC[0]]
        self.assertTrue(any("tekrar" in x for x in check(s)))
        s = sample()
        s["sources"] = [SRC[0]]
        self.assertTrue(any("2..6" in x for x in check(s)))

    def test_an_uncovered_on_screen_number_is_rejected(self):
        s = sample()
        s["claims"] = [c for c in s["claims"] if c["shown"] != "$24"]
        self.assertTrue(any("ekranda" in x for x in check(s)))

    def test_wrong_arithmetic_is_rejected(self):
        s = sample()
        for c in s["claims"]:
            if c["shown"] == "$24":
                c["value"] = 25
        self.assertTrue(any("0.40*60" in x for x in check(s)))

    def test_a_sourced_claim_needs_a_note(self):
        s = sample()
        s["claims"][0]["note"] = ""
        self.assertTrue(any("note" in x for x in check(s)))

    def test_a_source_that_nothing_uses_is_rejected(self):
        s = sample()
        s["claims"] = [c for c in s["claims"] if c.get("source") != 1]
        s["claims"].append({"shown": "$3", "expr": "0.05*60", "value": 3})
        self.assertTrue(any("kaynak #1" in x for x in check(s)))

    def test_story_needs_two_sourced_events_with_notes(self):
        s = story()
        s["facts"] = s["facts"][:1]
        self.assertTrue(any("at least 2" in x for x in check(s)))
        s = story()
        s["facts"][1]["note"] = ""
        self.assertTrue(any("olay iddiasinin" in x for x in check(s)))
        s = story()
        s["facts"][0]["source"] = 9
        self.assertTrue(check(s))

    def test_publishing_text_must_exist_and_pass_the_brand_rules(self):
        s = sample()
        del s["copy_parts"]["instagram"]
        self.assertTrue(any("copy_parts.instagram.caption" in x for x in check(s)))
        s = sample()
        s["copy_parts"]["tiktok"]["caption"] = "wow \U0001F525 look"
        self.assertTrue(any("emoji" in x for x in check(s)))
        s = sample()
        s["copy_parts"]["title"] = "x" * 70
        self.assertTrue(any("karakter" in x for x in check(s)))

    def test_script_rules_still_apply(self):
        s = sample()
        s["beats"][1]["say"] = "Don't forget to subscribe for more."
        self.assertTrue(any("yasakli" in x for x in check(s)))


class Files(unittest.TestCase):
    def write(self, root, name, spec):
        d = Path(root) / "content/scripts"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(spec if isinstance(spec, str) else json.dumps(spec))

    def run_check(self, root, **kw):
        (Path(root) / "brand.json").write_text(json.dumps(BRAND))
        return authored.check_all(Path(root), SCENES, **kw)

    def test_only_authored_files_are_checked_and_duplicates_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "p001-sample.json", sample())
            legacy = copy.deepcopy(good_spec())
            legacy["id"] = "old"
            self.write(tmp, "old.json", legacy)             # "authored" yok: atlanir
            dup = sample()
            dup["id"] = "p002-dup"
            self.write(tmp, "p002-dup.json", dup)           # ayni baslik
            self.write(tmp, "p003-bad.json", "{oops")
            res = self.run_check(tmp)
        self.assertEqual(res["p001-sample.json"], [])
        self.assertNotIn("old.json", res)
        self.assertTrue(any("ayni" in x for x in res["p002-dup.json"]))
        self.assertTrue(any("JSON" in x for x in res["p003-bad.json"]))

    def test_same_id_in_two_files_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "p001-sample.json", sample())
            other = sample()
            other["title"] = "A different title entirely about bills"
            self.write(tmp, "p002-copy.json", other)        # id hala p001-sample
            res = self.run_check(tmp)
        self.assertTrue(any("cakisiyor" in x for x in res["p002-copy.json"]))

    def test_main_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "p001-sample.json", sample())
            self.assertEqual(
                {k: v for k, v in self.run_check(tmp).items() if v}, {})
            self.write(tmp, "p002-bad.json", {**sample(), "id": "p002-bad",
                                              "title": "Bad one about nothing",
                                              "claims": []})
            res = self.run_check(tmp)
        self.assertTrue(res["p002-bad.json"])

    def test_every_authored_script_in_the_repo_passes(self):
        # asil icerik: biri bozulursa ilk push'ta kirmizi
        res = authored.check_all(authored.ROOT, SCENES)
        bad = {k: v for k, v in res.items() if v}
        self.assertEqual(bad, {})

    def test_cli_prints_problems_and_returns_one(self):
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "p001-bad.json", {**sample(), "claims": []})
            old = authored.ROOT
            authored.ROOT = Path(tmp)
            (Path(tmp) / "brand.json").write_text(json.dumps(BRAND))
            try:
                with contextlib.redirect_stdout(buf):
                    orig = authored.check_all
                    authored.check_all = lambda only=None: orig(
                        Path(tmp), SCENES, only)
                    try:
                        rc = authored.main([])
                    finally:
                        authored.check_all = orig
            finally:
                authored.ROOT = old
        self.assertEqual(rc, 1)
        self.assertIn("p001-bad.json", buf.getvalue())


class Plan(unittest.TestCase):
    """content/plan.md ile kuyruk ayni seyi soylemeli: pick_script dosya adi
    sirasiyla aliyor, yani sira planin sirasi."""

    def authored_files(self):
        out = []
        for f in sorted((authored.ROOT / authored.SCRIPTS).glob("*.json")):
            if "authored" in json.loads(f.read_text()):
                out.append(f)
        return out

    def test_queue_names_sort_in_plan_order_and_numbers_are_unique(self):
        import re
        files = self.authored_files()
        self.assertTrue(files)
        nums = []
        for f in files:
            m = re.match(r"^p(\d{3})-[a-z0-9-]+\.json$", f.name)
            self.assertTrue(m, f"{f.name}: ad p<3 hane>-<kisa-ad>.json olmali")
            nums.append(int(m.group(1)))
        self.assertEqual(len(nums), len(set(nums)), "ayni numara iki dosyada")

    def test_every_queued_script_is_listed_in_the_plan(self):
        plan = (authored.ROOT / "content" / "plan.md").read_text()
        # Panelden (kolay form) eklenen hikayeler plan.md'ye yazilmaz: planda olmasi onlari dogrulamaz,
        # kapi zaten editorial.authored'dan gecti. Elle yazilanlar planda listelenir.
        missing = [f.stem for f in self.authored_files()
                   if f"`{f.stem}`" not in plan
                   and json.loads(f.read_text())["authored"].get("by") != "panel"]
        self.assertEqual(missing, [], "content/plan.md 'Yazildi' tablosunda yok")


class Manifest(unittest.TestCase):
    def test_render_uses_the_authored_copy_parts(self):
        s = sample()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "brand.json").write_text(json.dumps(BRAND))
            man = M.build_manifest(s, {"duration": 40.0}, Path("v.mp4"), Path(tmp))
        self.assertEqual(man["captions"]["instagram"].splitlines()[0],
                         copy_parts()["instagram"]["caption"])
        self.assertIn("Video models bill per second", man["description"])
        self.assertIn(SRC[0], man["description"])


if __name__ == "__main__":
    unittest.main()
