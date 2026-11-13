"""
Elle cizilmis ikonlar (worker/icons.py): kelimeden ikon secimi, tutarlilik kurallari, cizim ve
zaman cizelgesi / akis sahnelerine baglanmalari.

    python -m unittest tests.test_icons -v
"""
import unittest

try:
    from PIL import Image, ImageDraw
    from worker import draw as D
    from worker import icons as I
    from worker import scenes as S
    from worker import scenes_more as M
    D.F_DISP(20)
    _OK, _WHY = True, ""
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY if not _OK else ''}")
class Pick(unittest.TestCase):
    def test_keywords_map_to_icons(self):
        cases = {"Founded in a garage": "garage", "Moves into an office": "building", "Raises $20M": "money", "Costs €5 a month": "money",
                 "Product launch": "rocket", "Hacked and leaked": "lock", "Users grow 3x": "chart",
                 "Free download": "phone", "Order shipped": "box"}
        for label, want in cases.items():
            with self.subTest(label=label):
                self.assertEqual(I.pick(label), want)

    def test_no_match_is_none_not_random(self):
        for label in ("Nothing here", "Relationship status", "", "   ", None, 5, ["garage"], {"a": 1}):
            with self.subTest(label=label):
                self.assertIsNone(I.pick(label))

    def test_whole_words_only(self):
        self.assertIsNone(I.pick("Mapped the apparatus"))          # 'app' kelimenin icinde
        self.assertIsNone(I.pick("Priced out of the ideal costume"))   # 'price', 'deal', 'cost' baska kelimelerin icinde
        self.assertIsNone(I.pick("Define the fines"))
        self.assertEqual(I.pick("Big IPO day"), "building")

    def test_deterministic(self):
        for label in ("Raises $20M", "Product launch", "x"):
            self.assertEqual(I.pick(label), I.pick(label))

    def test_every_rule_names_a_known_icon(self):
        self.assertEqual({n for n, _ in I._RULES}, set(I.NAMES))


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY if not _OK else ''}")
class Many(unittest.TestCase):
    def test_needs_two_matches(self):
        self.assertEqual(I.pick_many(["Founded in a garage", "Nothing", "x"]), [None, None, None])
        self.assertEqual(I.pick_many(["Founded in a garage", "Raises $2M", "x"]), ["garage", "money", None])

    def test_no_repeat_icon(self):
        out = I.pick_many(["Product launch", "Beta release", "Raises $2M", "Big deal"])
        self.assertEqual(out, ["rocket", None, "money", None])

    def test_same_length_and_bad_input_safe(self):
        self.assertEqual(I.pick_many([]), [])
        self.assertEqual(I.pick_many([None, 3, "x"]), [None, None, None])


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY if not _OK else ''}")
class Draw(unittest.TestCase):
    def test_every_icon_has_ink_and_stays_inside(self):
        for n in I.NAMES:
            with self.subTest(icon=n):
                sp = I.sprite(n, 100, (30, 30, 60), 0)
                self.assertEqual(sp.size, (100, 100))
                box = sp.split()[3].getbbox()
                self.assertIsNotNone(box)
                self.assertGreater(box[2] - box[0], 40)
                self.assertGreater(box[3] - box[1], 40)

    def test_variants_differ_but_are_cached(self):
        a, b = I.sprite("rocket", 100, (1, 2, 3), 0), I.sprite("rocket", 100, (1, 2, 3), 1)
        self.assertNotEqual(a.tobytes(), b.tobytes())
        self.assertIs(a, I.sprite("rocket", 100, (1, 2, 3), 0))

    def test_unknown_icon_raises_in_sprite_and_is_ignored_by_paste(self):
        with self.assertRaises(ValueError):
            I.sprite("kedi", 50, (0, 0, 0), 0)
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        I.paste(ImageDraw.Draw(img), None, 50, 50, 40, (0, 0, 0))
        self.assertEqual(img.getextrema(), ((255, 255), (255, 255), (255, 255)))

    def test_paste_fades_in(self):
        def ink(a):
            img = Image.new("RGB", (160, 160), (255, 255, 255))
            I.paste(ImageDraw.Draw(img), "chart", 80, 80, 100, (0, 0, 0), a)
            return sum(255 - p for p in img.getchannel(0).tobytes())
        self.assertEqual(ink(0.0), 0)
        self.assertGreater(ink(0.5), 0)
        self.assertGreater(ink(1.0), ink(0.5))


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY if not _OK else ''}")
class InScenes(unittest.TestCase):
    def tearDown(self):
        D.use_theme("midnight")                    # paleti sizdirma
    TL = {"steps": [{"at": "2009", "label": "Founded in a garage"}, {"at": "2012", "label": "Moves into an office"},
                    {"at": "2014", "label": "Raises $20M", "tone": "good"}]}
    TL_PLAIN = {"steps": [{"at": "2009", "label": "It began"}, {"at": "2012", "label": "It grew"},
                          {"at": "2014", "label": "It ended", "tone": "good"}]}

    def render(self, fn, data, t=6.0):
        D.use_theme("ink")
        img = Image.new("RGB", (D.W, D.H), D.BG if hasattr(D, "BG") else (10, 12, 30))
        fn(ImageDraw.Draw(img), t, 0.0, 8.0, data)
        return img

    def test_timeline_with_icons_differs_from_plain_and_stays_in_band(self):
        a = self.render(S.timeline, self.TL)
        b = self.render(S.timeline, self.TL_PLAIN)
        self.assertNotEqual(a.tobytes(), b.tobytes())
        bbox = ImageChops_diff_bbox(a)
        self.assertGreaterEqual(bbox[1], S.TOP)           # ust banda (BYTE/kelime) tasmaz

    def test_timeline_marker_moves(self):
        a = self.render(S.timeline, self.TL, t=1.5).tobytes()
        b = self.render(S.timeline, self.TL, t=1.9).tobytes()
        self.assertNotEqual(a, b)

    def test_flow_icon_nodes_render(self):
        data = {"nodes": [{"label": "Order placed"}, {"label": "Phone app update"}]}
        a = self.render(M.flow, data)
        b = self.render(M.flow, {"nodes": [{"label": "It began"}, {"label": "It ended"}]})
        self.assertNotEqual(a.tobytes(), b.tobytes())


def ImageChops_diff_bbox(img):
    from PIL import ImageChops
    bg = Image.new("RGB", img.size, img.getpixel((0, 0)))
    return ImageChops.difference(img, bg).getbbox()


if __name__ == "__main__":
    unittest.main()
