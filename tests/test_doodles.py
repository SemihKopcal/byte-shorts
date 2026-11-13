"""Hareketli karalama arka plani: kimlikten sabit, soluk, ust bant bos, hareket ediyor."""
import unittest

try:
    import numpy as np
    from PIL import Image
    from worker import doodles as DD
    from worker import draw as D
    from worker import themes as TH
    D.F_DISP(20)
    _OK, _WHY = True, ""
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)


def lum(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY}")
class Doodles(unittest.TestCase):
    def tearDown(self):
        D.use_theme("midnight")                    # paleti sizdirma: sonraki test dosyalari varsayilan koyu temayi bekler

    def canvas(self, name="paper"):
        D.use_theme(name)
        return D.build_bg(), name

    def test_layout_is_fixed_by_the_id(self):
        a, b = DD.layout("p001-x", 2), DD.layout("p001-x", 2)
        self.assertEqual(a, b)
        self.assertNotEqual(a, DD.layout("p002-y", 2))
        self.assertNotEqual(a, DD.layout("p001-x", 3))
        self.assertEqual(len(a), DD.COUNT)

    def test_nothing_enters_the_host_band_or_the_caption_zone(self):
        for sid in ("a", "b", "c", "d", "e"):
            for k in range(4):
                for dd in DD.layout(sid, k):
                    self.assertGreater(dd["y"] - dd["ay"] - dd["size"] / 2, DD.TOP - 60, (sid, k))
                    self.assertLess(dd["y"] + dd["ay"] + dd["size"] / 2, DD.BOT + 90, (sid, k))
                    self.assertTrue(-5 < dd["x"] - dd["ax"] - dd["size"] / 2 and dd["x"] + dd["ax"] + dd["size"] / 2 < DD.W + 5)

    def test_every_kind_draws_a_visible_mark(self):
        for kind in DD.KINDS:
            sp = DD.sprite(kind, 70, (120, 110, 100), 0)
            self.assertGreater(np.asarray(sp.split()[3]).sum(), 2000, kind)
            self.assertNotEqual(DD.sprite(kind, 70, (120, 110, 100), 0).tobytes(),
                                DD.sprite(kind, 70, (120, 110, 100), 1).tobytes(), f"{kind}: titreme varyanti ayni")

    def test_drawing_changes_the_background_but_only_below_the_top_band(self):
        bg, name = self.canvas()
        img = bg.copy()
        n = DD.draw(img, 1.3, "p001-x", 0, D.LINE, D.MUTE)
        self.assertEqual(n, DD.COUNT)
        diff = np.abs(np.asarray(img, np.int16) - np.asarray(bg, np.int16)).sum(axis=2)
        self.assertGreater(diff.sum(), 20000)
        self.assertEqual(diff[:300].sum(), 0, "ust bant (BYTE sunucu) bos kalmali")

    def test_it_moves_over_time_and_is_deterministic(self):
        bg, _ = self.canvas()
        def frame(t):
            img = bg.copy()
            DD.draw(img, t, "p001-x", 1, D.LINE, D.MUTE)
            return img.tobytes()
        self.assertEqual(frame(2.0), frame(2.0))
        self.assertNotEqual(frame(2.0), frame(4.0))
        self.assertNotEqual(frame(2.0), frame(2.25))                 # elle cizim titremesi

    def test_marks_stay_faint_on_every_face(self):
        for name in ("paper", *TH.PAPER_VARIANTS, "ink", *TH.INK_VARIANTS):
            th = TH.TOON_THEMES[name]
            c = DD.tone(th["line"], th["mute"])
            r = contrast(c, th["bg0"])
            self.assertLess(r, 3.2, f"{name}: doodle yaziyla yarisacak kadar belirgin ({r:.2f})")
            self.assertGreater(r, 1.1, f"{name}: doodle gorunmez ({r:.2f})")
            # yazi (ink) her zaman doodle'dan cok daha belirgin
            self.assertGreater(contrast(th["ink"], th["bg0"]), 3 * r, name)


if __name__ == "__main__":
    unittest.main()
