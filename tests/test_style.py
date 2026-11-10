"""
Video stil profili (worker/style.py) ve kamera / gecis efektleri (worker/fx.py).

Denetlenen seyler:
  1. DETERMINIZM: ayni senaryo hep ayni profili alir (publish.yml videoyu yeniden uretiyor),
     sha256 tabanli: Python surumu/islemi degisse de ayni;
  2. CESITLILIK: depodaki senaryolar farkli profil alir; art arda iki sahne ayni kamerayi yapmaz;
  3. GUVENLIK: tempo sinirli (QC 59 sn), kamera kenardan tasmaz, efektler boyutu/modu bozmaz
     ve bitince (u >= 1) kareyi aynen birakir.

    python -m unittest tests.test_style -v
"""
import copy
import json
import unittest
from pathlib import Path

from worker import style as S

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [json.loads(p.read_text()) for p in sorted((ROOT / "content" / "scripts").glob("p*.json"))]


def spec(sid="p900-x", fmt="measured"):
    return {"id": sid, "format": fmt, "series": "G"}


class Determinism(unittest.TestCase):
    def test_same_script_same_profile(self):
        a, b = S.profile(spec()), S.profile(copy.deepcopy(spec()))
        self.assertEqual(a, b)
        self.assertEqual(S.cameras("p900-x", 9), S.cameras("p900-x", 9))

    def test_profile_depends_only_on_id_and_format(self):
        base = S.profile(spec())
        noisy = {**spec(), "title": "other", "beats": [1, 2, 3], "theme": "ember", "tags": ["x"]}
        self.assertEqual(S.profile(noisy), base)

    def test_golden_values_pin_the_hash_scheme(self):
        """Algoritma degisirse BUTUN videolarin gorunumu degisir: bilerek yapilmali (VERSION)."""
        p = S.profile(spec("p013-deep-blue-1997", "story"))
        self.assertEqual(p, S.profile(spec("p013-deep-blue-1997", "story")))
        self.assertEqual(len(set(p["fx"])), 2)
        self.assertEqual([c["mode"] for c in S.cameras("p013-deep-blue-1997", 5)],
                         [c["mode"] for c in S.cameras("p013-deep-blue-1997", 5)])
        self.assertEqual(S.VERSION, 1)

    def test_prefix_of_camera_sequence_is_stable_when_scene_count_changes(self):
        short, long_ = S.cameras("p900-x", 4), S.cameras("p900-x", 8)
        self.assertEqual(short, long_[:4])


class Variety(unittest.TestCase):
    def test_real_scripts_get_many_different_profiles(self):
        profs = [S.profile(s) for s in SCRIPTS]
        self.assertGreaterEqual(len(SCRIPTS), 30)
        self.assertGreaterEqual(len({tuple(p["fx"]) for p in profs}), 8)
        self.assertEqual({f for p in profs for f in p["fx"]}, set(S.FX))
        seqs = {tuple(c["mode"] for c in S.cameras(s["id"], 5)) for s in SCRIPTS}
        self.assertGreaterEqual(len(seqs), 20)
        self.assertEqual({c["mode"] for s in SCRIPTS for c in S.cameras(s["id"], 6)}, set(S.CAMERAS))
        self.assertGreaterEqual(len({p["texture_alt"] for p in profs}), 3)
        self.assertTrue(any(p["texture_own"] for p in profs) and any(not p["texture_own"] for p in profs))

    def test_no_two_consecutive_scenes_share_a_camera_move(self):
        for s in SCRIPTS:
            cams = S.cameras(s["id"], 12)
            for a, b in zip(cams, cams[1:]):
                self.assertNotEqual(a["mode"], b["mode"], s["id"])

    def test_a_video_alternates_its_two_signature_transitions(self):
        p = S.profile(spec())
        seq = [S.transition_for(p, i) for i in range(1, 7)]
        self.assertEqual(set(seq), set(p["fx"]))
        for a, b in zip(seq, seq[1:]):
            self.assertNotEqual(a, b)
        self.assertIsNone(S.transition_for(p, 0))
        self.assertIsNone(S.transition_for({}, 3))

    def test_amplitudes_leave_room_to_drift(self):
        for s in SCRIPTS:
            for c in S.cameras(s["id"], 8):
                self.assertTrue(0.029 <= c["amp"] <= 0.056, c)
                if c["mode"].startswith("drift") or c["mode"] == "rise":
                    self.assertGreaterEqual(c["amp"], 0.045)


class Pace(unittest.TestCase):
    def test_pace_is_bounded_for_every_script(self):
        for s in SCRIPTS:
            p = S.pace_for(s)
            self.assertTrue(S.LENGTH_MIN <= p["length_delta"] <= S.LENGTH_MAX, s["id"])
            self.assertTrue(S.GAP_MIN <= p["gap_scale"] <= S.GAP_MAX, s["id"])

    def test_formats_differ_story_slow_measured_snappy(self):
        story = [S.pace_for(spec(f"s{i}", "story"))["length_delta"] for i in range(40)]
        meas = [S.pace_for(spec(f"s{i}", "measured"))["length_delta"] for i in range(40)]
        self.assertGreater(sum(story) / 40, sum(meas) / 40 + 0.02)

    def test_unknown_format_is_centered_on_neutral(self):
        vals = [S.pace_for(spec(f"u{i}", "weird"))["length_delta"] for i in range(60)]
        self.assertLess(abs(sum(vals) / 60), 0.006)

    def test_slowest_pace_keeps_every_real_script_under_the_safe_limit(self):
        """build.py: tempo yuzunden sure SAFE_SECONDS'i asarsa varsayilana doner; ama gercek
        senaryolarda en yavas tempo bile buna yaklasmamali (gece yeniden sentez yapmayalim)."""
        from tests.test_scripts_draw import fake_timeline
        from worker import build as B
        from worker import cta as C
        brand = json.loads((ROOT / "brand.json").read_text())
        longest = 0.0
        for s in SCRIPTS:
            sp = copy.deepcopy(s)
            C.apply(sp, brand, ROOT)
            est = fake_timeline(sp)[1]
            # konusma %LENGTH_MAX yavaslar; beat arasi bosluklar (suresinin en fazla ~%20'si) GAP_MAX kadar uzar
            slowest = est * (1 + S.LENGTH_MAX / 1.06) + est * 0.2 * (S.GAP_MAX - 1)
            longest = max(longest, slowest)
        self.assertLess(longest, B.SAFE_SECONDS - 3, f"en uzun tahmini: {longest:.1f} sn")

    def test_safe_limit_and_neutral_worst_case_are_below_qc(self):
        from worker import build as B
        self.assertLess(B.SAFE_SECONDS, 59 - 2)
        self.assertLess(52 + 3.5, 59, "kapi (52) + CTA + son pay QC'yi asmamali")


class Settings(unittest.TestCase):
    def test_enabled_unless_explicitly_false(self):
        for brand in ({}, {"style": {}}, {"style": None}, {"style": {"enabled": True}}, {"style": "x"}):
            self.assertTrue(S.settings(brand)["enabled"], brand)
        self.assertFalse(S.settings({"style": {"enabled": False}})["enabled"])

    def test_apply_sets_profile_once_and_respects_the_switch(self):
        sp = spec()
        self.assertTrue(S.apply(sp, {}))
        first = copy.deepcopy(sp["_style"])
        self.assertFalse(S.apply(sp, {}))
        self.assertEqual(sp["_style"], first)
        off = spec()
        self.assertFalse(S.apply(off, {"style": {"enabled": False}}))
        self.assertNotIn("_style", off)
        self.assertEqual(S.pace(off), S.NEUTRAL_PACE)

    def test_repo_brand_json_keeps_style_on(self):
        brand = json.loads((ROOT / "brand.json").read_text())
        self.assertTrue(S.settings(brand)["enabled"])


# ═══ fx: cizim ══════════════════════════════════════════════════════════════
try:
    import numpy as np
    from PIL import Image
    from worker import fx as X
    _OK = True
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)


def frame(w=270, h=480):
    """Renkli, desenli kucuk kare (efektler gorunur sekilde bir seyi degistirsin)."""
    y, x = np.mgrid[0:h, 0:w]
    arr = np.stack([(x * 255 // w), (y * 255 // h), ((x + y) * 255 // (w + h))], axis=2).astype(np.uint8)
    arr[h // 3:h // 3 + 40, 20:w - 20] = (240, 240, 240)
    return Image.fromarray(arr)


def diff(a, b):
    return int(np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).sum())


@unittest.skipUnless(_OK, "Pillow/numpy yok")
class Camera(unittest.TestCase):
    def test_modes_start_and_end_states(self):
        s0, *_ = X.camera_state("push", 0.0, 0.04, 1080, 1920)
        s1, *_ = X.camera_state("push", 1.0, 0.04, 1080, 1920)
        self.assertEqual(s0, 1.0)
        self.assertAlmostEqual(s1, 1.04)
        p0, *_ = X.camera_state("pull", 0.0, 0.04, 1080, 1920)
        p1, *_ = X.camera_state("pull", 1.0, 0.04, 1080, 1920)
        self.assertAlmostEqual(p0, 1.04)
        self.assertEqual(p1, 1.0)

    def test_drifts_never_leave_the_picture(self):
        for mode in ("drift_l", "drift_r", "rise"):
            for amp in (0.045, 0.055):
                for p in (0, 0.25, 0.5, 0.75, 1):
                    sc, dx, dy = X.camera_state(mode, p, amp, 1080, 1920)
                    self.assertLessEqual(abs(dx), (1080 - 1080 / sc) / 2 + 1e-6)
                    self.assertLessEqual(abs(dy), (1920 - 1920 / sc) / 2 + 1e-6)

    def test_drift_directions_are_opposite(self):
        _, dl0, _ = X.camera_state("drift_l", 0.0, 0.05, 1080, 1920)
        _, dr0, _ = X.camera_state("drift_r", 0.0, 0.05, 1080, 1920)
        self.assertEqual(dl0, -dr0)
        self.assertNotEqual(dl0, 0)

    def test_progress_is_clamped_and_unknown_mode_is_neutral(self):
        self.assertEqual(X.camera_state("push", 9, 0.04, 100, 100), X.camera_state("push", 1, 0.04, 100, 100))
        self.assertEqual(X.camera_state("push", -3, 0.04, 100, 100), X.camera_state("push", 0, 0.04, 100, 100))
        self.assertEqual(X.camera_state("nope", 0.5, 0.04, 100, 100), (1.0, 0.0, 0.0))

    def test_apply_camera_keeps_size_and_neutral_is_identity(self):
        im = frame()
        self.assertIs(X.apply_camera(im, 1.0, 0.0, 0.0), im)
        out = X.apply_camera(im, 1.05, 3.0, -2.0)
        self.assertEqual(out.size, im.size)
        self.assertGreater(diff(out, im), 0)

    def test_zoomed_picture_has_no_blank_border(self):
        im = Image.new("RGB", (270, 480), (200, 120, 60))
        for mode in ("drift_l", "drift_r", "rise", "push", "pull"):
            for p in (0, 0.5, 1):
                sc, dx, dy = X.camera_state(mode, p, 0.05, 270, 480)
                out = np.asarray(X.apply_camera(im, sc, dx, dy))
                self.assertTrue((out.reshape(-1, 3).min(axis=0) >= (190, 110, 50)).all(), (mode, p))


@unittest.skipUnless(_OK, "Pillow/numpy yok")
class Transitions(unittest.TestCase):
    def test_every_effect_changes_the_frame_at_the_start_and_leaves_it_alone_at_the_end(self):
        im = frame()
        for kind in S.FX:
            start = X.transition(im, kind, 0.05, {"glow": (139, 139, 255), "bg0": (7, 7, 12)}, seed=3)
            self.assertEqual(start.size, im.size, kind)
            self.assertEqual(start.mode, "RGB", kind)
            self.assertGreater(diff(start, im), 0, kind)
            self.assertIs(X.transition(im, kind, 1.0), im, kind)
            self.assertIs(X.transition(im, kind, 1.7), im, kind)

    def test_effects_fade_out_monotonically(self):
        im = frame()
        for kind in ("flash", "blur", "zoom", "slide"):
            ds = [diff(X.transition(im, kind, u, {"glow": (139, 139, 255), "bg0": (7, 7, 12)}), im)
                  for u in (0.02, 0.2, 0.5, 0.8)]
            self.assertTrue(all(a >= b for a, b in zip(ds, ds[1:])), (kind, ds))

    def test_unknown_or_missing_kind_is_a_noop(self):
        im = frame()
        for kind in (None, "", "nope"):
            self.assertIs(X.transition(im, kind, 0.1), im)
        self.assertIs(X.transition(im, "flash", -0.5), im)

    def test_glitch_is_deterministic_per_seed(self):
        im = frame()
        a = X.transition(im, "glitch", 0.1, seed=11)
        b = X.transition(im, "glitch", 0.1, seed=11)
        c = X.transition(im, "glitch", 0.1, seed=12)
        self.assertEqual(diff(a, b), 0)
        self.assertGreater(diff(a, c), 0)

    def test_flash_is_soft_never_blows_out_the_frame(self):
        im = Image.new("RGB", (100, 100), (10, 10, 10))
        out = np.asarray(X.transition(im, "flash", 0.0, {"glow": (255, 255, 255)}))
        self.assertLess(int(out.max()), 120)

    def test_all_style_effects_are_implemented(self):
        im = frame()
        for kind in S.FX:
            self.assertIsNot(X.transition(im, kind, 0.1, {"glow": (1, 2, 3), "bg0": (0, 0, 0)}), im, kind)


@unittest.skipUnless(_OK, "Pillow/numpy yok")
class StyleLayer(unittest.TestCase):
    """worker.build.style_layer: kamera + gecis, sahne pencerelerine gore."""
    STAGES = [(0.0, 5.0, None), (5.4, 10.0, None), (10.4, 14.0, None)]
    CAMS = [{"mode": "push", "amp": 0.04}, {"mode": "drift_l", "amp": 0.05}, {"mode": "pull", "amp": 0.04}]
    STY = {"fx": ["flash", "zoom"], "fx_start": 0}
    THEME = {"glow": (139, 139, 255), "bg0": (7, 7, 12)}

    def layer(self, t, img=None, i=0):
        from worker.build import style_layer
        return style_layer(img or frame(270, 480), t, i, self.STAGES, self.CAMS, self.STY, self.THEME)

    def test_empty_stages_leave_the_frame_alone(self):
        from worker.build import style_layer
        im = frame()
        self.assertIs(style_layer(im, 1.0, 0, [], [], self.STY, self.THEME), im)

    def test_camera_holds_the_previous_scenes_end_state_until_the_next_scene_starts(self):
        """5.0-5.4 arasi (bosluk): ziplama yok, onceki sahnenin son kamerasi."""
        im = frame()
        sc, dx, dy = X.camera_state("push", 1.0, 0.04, im.width, im.height)
        expected = X.apply_camera(im, sc, dx, dy)
        for t in (5.1, 5.39):
            self.assertEqual(diff(self.layer(t, im), expected), 0, t)

    def test_first_scene_has_no_transition_and_later_ones_do_for_a_third_of_a_second(self):
        im = frame()

        def cam_only(t, k):
            t0, t1, _ = self.STAGES[k]
            sc, dx, dy = X.camera_state(self.CAMS[k]["mode"], (t - t0) / (t1 - t0), self.CAMS[k]["amp"], im.width, im.height)
            return X.apply_camera(im, sc, dx, dy)

        self.assertEqual(diff(self.layer(0.05, im), cam_only(0.05, 0)), 0, "ilk sahnede efekt olmamali")
        self.assertGreater(diff(self.layer(5.5, im), cam_only(5.5, 1)), 0, "sahne degisiminde efekt")
        end = 5.4 + X.TRANSITION_DELAY + X.TRANSITION_SECONDS + 0.05
        self.assertEqual(diff(self.layer(end, im), cam_only(end, 1)), 0)

    def test_transitions_alternate_between_the_two_signature_effects(self):
        self.assertEqual(S.transition_for(self.STY, 1), "zoom")
        self.assertEqual(S.transition_for(self.STY, 2), "flash")

    def test_output_is_always_a_same_size_rgb_frame(self):
        for t in (0.0, 2.5, 5.2, 5.5, 7.0, 10.6, 13.9, 20.0):
            out = self.layer(t)
            self.assertEqual((out.size, out.mode), ((270, 480), "RGB"), t)


if __name__ == "__main__":
    unittest.main()
