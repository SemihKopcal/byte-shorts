"""
BYTE'in ifadeleri (worker/byte.py poz + simge, worker/cartoon.mood): yeni pozlar, simgeler, oncelik sirasi
ve poz listelerinin uc yerde (cizim, kural, LLM katalogu) ayni kalmasi.

    python -m unittest tests.test_byte_moods -v
"""
import unittest

try:
    from PIL import Image, ImageDraw
    from worker import byte as B
    from worker import cartoon as TOON
    _OK, _WHY = True, ""
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)

from editorial import roles, rules


def sheet(pose, glyph="", anim=0.0, cursor=None):
    img = Image.new("RGB", (400, 520), (244, 236, 212))
    B.draw_byte_sticker(ImageDraw.Draw(img), 200, 270, 0.6, pose, cursor or B.MINT, True, 1.0,
                        glyph=glyph, anim=anim, shadow=(208, 195, 160))
    return img


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY if not _OK else ''}")
class Poses(unittest.TestCase):
    def test_every_pose_draws_and_differs_from_idle(self):
        base = sheet("idle").tobytes()
        for p in B.POSES:
            with self.subTest(pose=p):
                im = sheet(p)
                self.assertEqual(im.size, (400, 520))
                if p != "idle":
                    self.assertNotEqual(im.tobytes(), base)

    def test_glyphs_replace_the_cursor(self):
        base = sheet("idle").tobytes()
        seen = {base}
        for g in ("!", "?", "star"):
            with self.subTest(glyph=g):
                b = sheet("idle", g).tobytes()
                self.assertNotIn(b, seen)
                seen.add(b)

    def test_unknown_glyph_falls_back_to_the_cursor(self):
        self.assertEqual(sheet("idle", "bilinmeyen").tobytes(), sheet("idle", "").tobytes())

    def test_wave_and_cheer_move_other_poses_dont(self):
        for p in ("wave", "cheer"):
            with self.subTest(pose=p):
                self.assertNotEqual(sheet(p, anim=0.0).tobytes(), sheet(p, anim=0.1).tobytes())
        for p in ("idle", "point_r", "shrug", "alert", "think"):
            with self.subTest(pose=p):
                self.assertEqual(sheet(p, anim=0.0).tobytes(), sheet(p, anim=0.1).tobytes())

    def test_pose_lists_agree_across_drawing_rules_and_llm_catalogue(self):
        self.assertEqual(tuple(rules.POSES), tuple(B.POSES))
        self.assertIn("|".join(B.POSES), roles.SCENE_DOC)

    def test_glyph_names_are_a_closed_set(self):
        self.assertEqual(set(B.GLYPHS), {"", "!", "?", "star"})


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY if not _OK else ''}")
class Mood(unittest.TestCase):
    D = 30.0

    def m(self, t, tone="base", t0=10.0, pointing=False):
        return TOON.mood(t, tone, t0, self.D, pointing)

    def test_wave_at_start_and_end(self):
        self.assertEqual(self.m(0.2, "bad", t0=0.0), ("wave", ""))
        self.assertEqual(self.m(self.D - 0.5, "good"), ("wave", ""))
        self.assertEqual(self.m(TOON.WAVE_OPEN + 0.01, "base", t0=0.0), ("idle", ""))
        self.assertEqual(self.m(self.D - TOON.WAVE_CLOSE - 0.01, "base"), ("idle", ""))

    def test_pointing_beats_everything(self):
        for t in (0.2, 10.3, self.D - 0.3):
            self.assertEqual(self.m(t, "bad", pointing=True), ("point_r", ""))

    def test_stage_start_expression_by_tone(self):
        self.assertEqual(self.m(10.2, "bad"), ("alert", "!"))
        self.assertEqual(self.m(10.2, "good"), ("cheer", "star"))
        self.assertEqual(self.m(10.2, "mid"), ("think", "?"))
        self.assertEqual(self.m(10.2, "base"), ("idle", ""))

    def test_expression_ends_after_mood_seconds_and_not_before_stage(self):
        self.assertEqual(self.m(10.0 + TOON.MOOD_SECONDS + 0.01, "bad"), ("idle", ""))
        self.assertEqual(self.m(9.9, "bad"), ("idle", ""))

    def test_first_stage_expression_starts_after_the_wave(self):
        self.assertEqual(self.m(1.0, "bad", t0=0.0), ("wave", ""))
        self.assertEqual(self.m(TOON.WAVE_OPEN + 0.2, "bad", t0=0.0), ("alert", "!"))
        self.assertEqual(self.m(TOON.WAVE_OPEN + TOON.MOOD_SECONDS + 0.05, "bad", t0=0.0), ("idle", ""))

    def test_every_result_is_a_known_pose_and_glyph(self):
        for t in [i * 0.1 for i in range(0, 300)]:
            for tone in ("bad", "good", "mid", "base"):
                for pt in (False, True):
                    p, g = self.m(t, tone, pointing=pt)
                    self.assertIn(p, B.POSES)
                    self.assertIn(g, B.GLYPHS)


if __name__ == "__main__":
    unittest.main()
