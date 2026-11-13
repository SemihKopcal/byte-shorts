"""
Ikinci tur sahneler (worker/scenes_more.py).

Uc sey denetleniyor:
  1. gecerli veriyle her sahne, her zamanda (sahneden once, basinda, ortasinda,
     cok sonra) PATLAMADAN ve bos olmayan bir sey cizerek calisir;
  2. bozuk veriyle (bos, yanlis tur, cok uzun metin) PATLAMAZ: senaryoyu bir
     model yazmis olabilir ve 4 dakikalik render'in sonunda kirmizi yanmak
     istemiyoruz;
  3. editorial.rules._shape ayni verinin gecerli olanini kabul, bozugunu reddeder.

    python -m unittest tests.test_scenes_more -v
"""
import unittest

from tests.fixtures import SCENES

try:
    from PIL import Image, ImageDraw
    from worker import draw as D
    from worker.scenes import CATALOG, NAMES
    from worker.scenes_more import NAMES_MORE
    D.F_DISP(20)                       # font yoksa burada patlar
    _OK, _WHY = True, ""
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)

from editorial import rules

SAMPLES = {
    "steps": {"steps": [{"label": "Text becomes tokens", "sub": "pieces"}, {"label": "Tokens become ids"}, {"label": "Model scores", "tone": "mid"}]},
    "flow": {"nodes": [{"label": "Prompt"}, {"label": "Tokenizer", "sub": "splits"}, {"label": "Model", "tone": "good"}], "arrows": ["split", "predict"]},
    "equation": {"terms": [{"value": "256", "label": "red"}, {"value": "256"}, {"value": "256"}], "op": "×", "result": {"value": "16,777,216", "label": "colours"}},
    "ring": {"value": 93.1, "dp": 1, "label": "931 of 1,000 GB", "sub": "shown", "tone": "mid"},
    "dots": {"total": 100, "hit": 6, "label": "6 of 100", "sub": "fake", "tone": "bad"},
    "chat": {"messages": [{"who": "user", "text": "Can I claim later?"}, {"who": "bot", "text": "Yes, within 90 days.", "tone": "bad"}]},
    "terminal": {"title": "unix time", "lines": ["$ date -u -d @2147483647", {"text": "Tue Jan 19 03:14:07 2038", "kind": "hl"}, {"text": "overflow", "kind": "err"}]},
    "tokens": {"tokens": ["Un", "believ", "able", "tokens"], "note": "4 tokens"},
    "probs": {"prompt": "The capital of France is", "rows": [{"word": "Paris", "p": 0.82}, {"word": "a", "p": 0.07}]},
    "layers": {"layers": [{"label": "Embeddings", "sub": "vectors"}, {"label": "Attention"}, {"label": "Output"}], "total": "x 32 layers"},
    "checklist": {"rows": [{"text": "Bot said yes", "ok": True}, {"text": "Policy said no", "ok": False}]},
    "headline": {"source": "Newswire", "date": "Oct 2018", "kicker": "Hiring", "headline": "Company scraps a recruiting tool"},
    "scale": {"items": [{"label": "chess", "exp": 44, "text": "10^44"}, {"label": "go", "exp": 170, "text": "10^170"}]},
    "cycle": {"nodes": [{"label": "Demonstrate"}, {"label": "Rank"}, {"label": "Optimize"}], "center": "RLHF"},
    "bits": {"bits": "01111111111111111111111111111111", "flip_to": "10000000000000000000000000000000", "label": "2038", "flip_label": "1901"},
    "guess": {"q": "How many chips did the demo use?", "options": ["One", "Two", "Four"], "answer": 1, "note": "Two, and one was a spare."},
}
JUNK = (None, "", 0, -5, "x" * 300, [], [None], [1, 2, 3], {"a": 1}, True, [{"label": None}])


def _canvas():
    img = Image.new("RGB", (D.W, D.H), D.BG0)
    return img, ImageDraw.Draw(img)


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY}")
class NewScenes(unittest.TestCase):
    def test_catalog_has_all_scenes_and_matches_fixture(self):
        self.assertEqual(len(NAMES), 25)
        self.assertEqual(set(NAMES), set(SCENES))
        self.assertEqual(set(SAMPLES), set(NAMES_MORE))
        for n in NAMES_MORE:
            self.assertIn(n, CATALOG)

    def test_valid_data_draws_something_at_every_time(self):
        for name, data in SAMPLES.items():
            for t in (-1.0, 0.0, 0.4, 1.5, 3.0, 8.0, 30.0):
                img, d = _canvas()
                CATALOG[name](d, t, 0.0, 6.0, data)
            img, d = _canvas()
            CATALOG[name](d, 5.0, 0.0, 6.0, data)
            blank = Image.new("RGB", (D.W, D.H), D.BG0)
            self.assertNotEqual(img.tobytes(), blank.tobytes(), f"{name}: hic bir sey cizmedi")

    def test_broken_data_never_raises(self):
        fails = []
        for name, data in SAMPLES.items():
            for call in ({}, {"zzz": 1}):
                img, d = _canvas()
                CATALOG[name](d, 2.0, 0.0, 6.0, call)
            for key in data:
                for junk in JUNK:
                    bad = dict(data)
                    bad[key] = junk
                    for t in (0.5, 5.0):
                        img, d = _canvas()
                        try:
                            CATALOG[name](d, t, 0.0, 6.0, bad)
                        except Exception as e:      # noqa: BLE001
                            fails.append(f"{name}[{key}={str(junk)[:20]!r}] t={t}: {type(e).__name__}: {e}")
        self.assertEqual(fails, [], "\n" + "\n".join(sorted(set(fails))[:40]))

    def test_long_text_does_not_raise(self):
        long = "word " * 80
        for name, data in SAMPLES.items():
            def stretch(v):
                if isinstance(v, str):
                    return long
                if isinstance(v, list):
                    return [stretch(x) for x in v]
                if isinstance(v, dict):
                    return {k: stretch(x) for k, x in v.items()}
                return v
            img, d = _canvas()
            data2 = {k: (v if k in ("bits", "flip_to", "tone", "kind", "who", "pose") else stretch(v))
                     for k, v in data.items()}
            CATALOG[name](d, 5.0, 0.0, 6.0, data2)


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY}")
class ContrastLabels(unittest.TestCase):
    """Iki uzun etiket ortada birbirine degmemeli ("ATOMS IN THE UNIVERSE" +
    "LEGAL GO POSITIONS" bitisik cikiyordu)."""

    def _ink_in_gap(self, left, right):
        from worker import scenes as S
        im = Image.new("RGB", (D.W, D.H), (0, 0, 0))
        S.contrast(ImageDraw.Draw(im), 2.0, 0.0, 3.0,
                   {"left": {"label": left, "value": "10^80"},
                    "right": {"label": right, "value": "2.08 x 10^170"}})
        y0, y1 = int(S.MID + 110), int(S.MID + 150)
        x0, x1 = int(S.MIDX - 8), int(S.MIDX + 8)
        gap = im.crop((x0, y0, x1, y1)).convert("L")
        side = im.crop((0, y0, D.W, y1)).convert("L")
        return max(gap.getdata()), max(side.getdata())

    def test_long_labels_leave_a_gap_in_the_middle(self):
        gap, side = self._ink_in_gap("atoms in the universe", "legal Go positions")
        self.assertGreater(side, 60, "etiketler hic cizilmedi")
        self.assertLess(gap, 40, "iki etiket ortada birbirine degiyor")

    def test_short_labels_still_drawn(self):
        gap, side = self._ink_in_gap("before", "after")
        self.assertGreater(side, 60)
        self.assertLess(gap, 40)


class ShapeRules(unittest.TestCase):
    def test_good_samples_pass(self):
        for name, data in SAMPLES.items():
            self.assertEqual(rules._shape(name, data, "b1"), [], name)

    def test_empty_data_is_rejected(self):
        for name in SAMPLES:
            self.assertTrue(rules._shape(name, {}, "b1"), f"{name}: bos data kabul edildi")

    def test_specific_mistakes(self):
        self.assertTrue(rules._shape("chat", {"messages": [{"who": "robot", "text": "x"}]}, "b1"))
        self.assertTrue(rules._shape("bits", {"bits": "0102"}, "b1"))
        self.assertTrue(rules._shape("bits", {"bits": "0101", "flip_to": "01"}, "b1"))
        self.assertTrue(rules._shape("cycle", {"nodes": [{"label": "a"}, {"label": "b"}]}, "b1"))
        self.assertTrue(rules._shape("dots", {"hit": 9, "total": 5}, "b1"))
        self.assertTrue(rules._shape("scale", {"items": [{"label": "x", "value": 0}]}, "b1"))
        self.assertTrue(rules._shape("probs", {"rows": [{"word": "a", "p": "high"}]}, "b1"))

    def test_guess_rules(self):
        ok = {"q": "Which one?", "options": ["a", {"text": "b"}], "answer": 1}
        self.assertEqual(rules._shape("guess", ok, "b1"), [])
        bad = (
            {**ok, "q": ""}, {**ok, "q": "x" * 91}, {**ok, "options": ["a"]}, {**ok, "options": list("abcde")},
            {**ok, "options": ["a", ""]}, {**ok, "options": ["a", "x" * 41]}, {**ok, "answer": 2},
            {**ok, "answer": -1}, {**ok, "answer": "1"}, {**ok, "answer": True}, {**ok, "answer": 0.0},
            {**ok, "note": 5}, {**ok, "note": "x" * 91}, {"q": "Which one?", "options": ["a", "b"]})
        for data in bad:
            with self.subTest(data=data):
                self.assertTrue(rules._shape("guess", data, "b1"))


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY}")
class GuessScene(unittest.TestCase):
    DATA = {"q": "How many chips did the demo use?", "options": ["One", "Two", "Four"], "answer": 1, "note": "Two."}

    def img(self, t, data=None, t1=8.0):
        img, d = _canvas()
        CATALOG["guess"](d, t, 0.0, t1, data or self.DATA)
        return img.tobytes()

    def test_answer_is_hidden_then_revealed(self):
        before, after = self.img(2.0), self.img(7.0)
        self.assertNotEqual(before, after)
        wrong = dict(self.DATA, answer=0)
        self.assertNotEqual(self.img(7.0, wrong), after)           # farkli sik vurgulanir

    def test_before_reveal_all_answers_look_identical(self):
        for t in (1.0, 2.0, 4.0):
            self.assertEqual(self.img(t, dict(self.DATA, answer=0)), self.img(t, dict(self.DATA, answer=2)))

    def test_short_scene_still_reveals(self):
        self.assertNotEqual(self.img(0.5, t1=1.0), self.img(1.0, t1=1.0))
        self.assertNotEqual(self.img(0.7, t1=1.0), self.img(5.0, t1=1.0))

    def test_invalid_answer_never_reveals(self):
        for a in (-1, 3, None, "x", True):
            with self.subTest(answer=a):
                bad = dict(self.DATA, answer=a)
                self.assertEqual(self.img(4.0, bad), self.img(7.5, bad))     # hicbir sik yesile donmez, sure cubugu da yok


if __name__ == "__main__":
    unittest.main()
