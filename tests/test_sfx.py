"""
Ses efektleri (worker/sfx.py + cartoon.Toon.sfx_events): sentez, konusmanin tepe seviyesini asmama,
dosya karistirma, olay zamanlari ve brand anahtari.

    python -m unittest tests.test_sfx -v
"""
import json
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    import numpy as np
    from worker import sfx as SFX
    from worker import cartoon as TOON
    from tests.test_cartoon import build_toon, spec_g
    _OK, _WHY = True, ""
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)


def write_wav(path, x, sr=48000, ch=2):
    pcm = np.clip(np.rint(np.asarray(x) * 32767), -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


@unittest.skipUnless(_OK, f"bagimliliklar yok: {_WHY if not _OK else ''}")
class Synth(unittest.TestCase):
    def test_every_kind_is_finite_quiet_and_ends_clean(self):
        for k in SFX.KINDS:
            with self.subTest(kind=k):
                x = SFX.synth(k)
                self.assertTrue(np.all(np.isfinite(x)))
                self.assertGreater(len(x), 1000)
                self.assertLessEqual(float(np.max(np.abs(x))), 0.25)            # ~ -12 dBFS ustune cikmaz
                self.assertGreater(float(np.max(np.abs(x))), 0.04)              # duyulur
                self.assertLess(abs(float(x[-1])), 0.01)                        # sonda tik/cizirti yok

    def test_deterministic(self):
        for k in SFX.KINDS:
            SFX.synth.cache_clear()
            a = SFX.synth(k).tobytes()
            SFX.synth.cache_clear()
            self.assertEqual(a, SFX.synth(k).tobytes())

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            SFX.synth("patlama")


@unittest.skipUnless(_OK, f"bagimliliklar yok: {_WHY if not _OK else ''}")
class Render(unittest.TestCase):
    def silent(self, sec=2.0):
        return np.zeros((int(sec * SFX.SR), 2), np.float32)

    def test_effect_lands_at_its_time_only(self):
        out = SFX.render(self.silent(), [(0.5, "tik")], 1.0)
        s = int(0.5 * SFX.SR)
        self.assertEqual(float(np.max(np.abs(out[:s]))), 0.0)
        self.assertGreater(float(np.max(np.abs(out[s:s + 2000]))), 0.01)
        self.assertEqual(float(np.max(np.abs(out[s + len(SFX.synth("tik")):]))), 0.0)
        self.assertTrue(np.array_equal(out[:, 0], out[:, 1]))                   # iki kanal ayni

    def test_gain_zero_returns_voice_untouched(self):
        v = self.silent() + 0.3
        self.assertTrue(np.array_equal(SFX.render(v, [(0.1, "ding"), (0.5, "whoosh")], 0.0), v))

    def test_never_exceeds_the_voice_peak_limit(self):
        for level in (0.0, 0.3, 0.6, 0.83, 0.84, 0.9, 1.0):
            with self.subTest(voice=level):
                v = self.silent() + level
                out = SFX.render(v, [(0.1, "tik"), (0.3, "ding"), (0.6, "whoosh"), (1.2, "thud")], SFX.GAIN_MAX)
                self.assertLessEqual(float(np.max(np.abs(out))), max(SFX.LIMIT, level) + 1e-6)
                if level >= SFX.LIMIT:
                    self.assertTrue(np.array_equal(out, v))                     # tepe zaten dolu: efekt eklenmez

    def test_loud_voice_with_alternating_sign_still_fits(self):
        t = np.arange(2 * SFX.SR) / SFX.SR
        v = (0.8 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        v = np.stack([v, v], axis=1)
        out = SFX.render(v, [(0.2, "ding"), (0.9, "thud")], SFX.GAIN_MAX)
        self.assertLessEqual(float(np.max(np.abs(out))), SFX.LIMIT + 1e-6)

    def test_bad_events_are_ignored(self):
        v = self.silent()
        out = SFX.render(v, [(-5, "tik"), (999, "tik"), (None, "tik"), ("x", "tik"), (0.5, "yok"), (float("nan"), "tik")], 1.0)
        self.assertTrue(np.array_equal(out, v))

    def test_event_at_the_very_end_is_cut_not_crashed(self):
        v = self.silent(1.0)
        out = SFX.render(v, [(0.99, "ding")], 1.0)
        self.assertEqual(out.shape, v.shape)

    def test_gain_of_clamps_and_survives_junk(self):
        self.assertEqual(SFX.gain_of(0.5), 0.5)
        self.assertEqual(SFX.gain_of(-3), 0.0)
        self.assertEqual(SFX.gain_of(99), SFX.GAIN_MAX)
        for junk in (None, "x", [], {}, float("nan")):
            self.assertEqual(SFX.gain_of(junk), SFX.GAIN_DEFAULT)


@unittest.skipUnless(_OK, f"bagimliliklar yok: {_WHY if not _OK else ''}")
class MixFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        t = np.arange(SFX.SR * 2) / SFX.SR
        v = (0.4 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
        write_wav(self.tmp / "voice.wav", np.stack([v, v], axis=1))

    def test_mix_writes_16bit_stereo_48k_same_length_and_is_deterministic(self):
        ev = [(0.3, "tik"), (0.8, "whoosh"), (1.4, "ding")]
        a = SFX.mix(self.tmp / "voice.wav", ev, self.tmp / "a.wav", 0.6)
        b = SFX.mix(self.tmp / "voice.wav", ev, self.tmp / "b.wav", 0.6)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        with wave.open(str(a)) as w, wave.open(str(self.tmp / "voice.wav")) as v:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (2, 2, 48000))
            self.assertEqual(w.getnframes(), v.getnframes())
        self.assertNotEqual(a.read_bytes(), (self.tmp / "voice.wav").read_bytes())

    def test_mix_failures_return_none_instead_of_raising(self):
        ev = [(0.3, "tik")]
        self.assertIsNone(SFX.mix(self.tmp / "yok.wav", ev, self.tmp / "o.wav"))
        self.assertIsNone(SFX.mix(self.tmp / "voice.wav", [], self.tmp / "o.wav"))
        (self.tmp / "bozuk.wav").write_bytes(b"RIFFxxxx")
        self.assertIsNone(SFX.mix(self.tmp / "bozuk.wav", ev, self.tmp / "o.wav"))
        write_wav(self.tmp / "mono44.wav", np.zeros((44100, 1)), sr=44100, ch=1)
        self.assertIsNone(SFX.mix(self.tmp / "mono44.wav", ev, self.tmp / "o.wav"))
        self.assertFalse((self.tmp / "o.wav").exists())

    def test_mono_48k_voice_is_accepted(self):
        write_wav(self.tmp / "mono.wav", np.zeros((SFX.SR, 1)), sr=SFX.SR, ch=1)
        self.assertIsNotNone(SFX.mix(self.tmp / "mono.wav", [(0.2, "tik")], self.tmp / "m.wav"))


@unittest.skipUnless(_OK, f"bagimliliklar yok: {_WHY if not _OK else ''}")
class Settings(unittest.TestCase):
    ON = {"cartoon": {"enabled": True, "alternate": True, "share": 1.0}}

    def test_sfx_is_off_unless_explicitly_true(self):
        self.assertFalse(TOON.settings(self.ON)["sfx"])
        for raw in ("true", 1, "yes", None):
            self.assertFalse(TOON.settings({"cartoon": {"enabled": True, "sfx": raw}})["sfx"], raw)
        self.assertTrue(TOON.settings({"cartoon": {"enabled": True, "sfx": True}})["sfx"])

    def test_profile_carries_the_switch(self):
        s = spec_g("sfx1")
        TOON.apply(s, {"cartoon": {"enabled": True, "sfx": True, "sfx_gain": 0.3}})
        self.assertTrue(s["_cartoon"]["sfx"])
        self.assertEqual(s["_cartoon"]["sfx_gain"], 0.3)
        s2 = spec_g("sfx2")
        TOON.apply(s2, self.ON)
        self.assertFalse(s2["_cartoon"]["sfx"])

    def test_shipped_brand_is_valid(self):
        raw = json.loads((ROOT / "brand.json").read_text())["cartoon"]
        self.assertIsInstance(raw["sfx"], bool)
        self.assertTrue(0.0 <= raw["sfx_gain"] <= SFX.GAIN_MAX)


@unittest.skipUnless(_OK, f"bagimliliklar yok: {_WHY if not _OK else ''}")
class Events(unittest.TestCase):
    def toon(self):
        paths = sorted((ROOT / "content" / "scripts").glob("p04*.json"))
        return build_toon(json.loads(paths[0].read_text()))

    def test_events_are_sorted_in_range_and_known(self):
        tn = self.toon()
        ev = tn.sfx_events()
        self.assertEqual(ev, sorted(ev))
        for t, k in ev:
            self.assertIn(k, SFX.KINDS)
            self.assertGreaterEqual(t, 0.0)
            self.assertLess(t, tn.duration)

    def test_one_whoosh_per_stage_change_and_one_tik_per_keyword(self):
        tn = self.toon()
        ev = tn.sfx_events()
        self.assertEqual(sum(1 for _t, k in ev if k == "whoosh"), len(tn.stages) - 1)
        self.assertEqual(sum(1 for _t, k in ev if k == "tik"), sum(len(p["items"]) for p in tn.plan))

    def test_marks_and_guess_add_their_sounds(self):
        tn = self.toon()
        ev0 = tn.sfx_events()
        n = lambda ev, kind: sum(1 for _t, k in ev if k == kind)           # noqa: E731
        first = tn.plan[0]["items"][0]["id"] if tn.plan[0]["items"] else "b1"
        tn.plan[0]["items"].append({"id": first, "kw": "x", "mark": "check"})
        tn.plan[0]["items"].append({"id": first, "kw": "y", "mark": "x"})
        ev = tn.sfx_events()
        self.assertEqual(len(ev), len(ev0) + 4)                            # iki tik + ding + thud
        self.assertEqual(n(ev, "ding"), n(ev0, "ding") + 1)
        self.assertEqual(n(ev, "thud"), n(ev0, "thud") + 1)
        tn.plan[1]["name"] = "guess"
        self.assertEqual(n(tn.sfx_events(), "ding"), n(ev, "ding") + 1)

    def test_whoosh_comes_just_before_each_iris(self):
        tn = self.toon()
        wh = [t for t, k in tn.sfx_events() if k == "whoosh"]
        for k, t in enumerate(wh, start=1):
            self.assertAlmostEqual(t, tn.stages[k][0] - TOON.IRIS_LEAD, places=6)


if __name__ == "__main__":
    unittest.main()
