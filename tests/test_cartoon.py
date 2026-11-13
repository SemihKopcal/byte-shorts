"""
Karton / cizgi film stili (worker/cartoon.py): ayar, kimlik, anahtar kelime, ses zarfi, iris, tema
okunurlugu ve -- fontlar varsa -- her senaryonun her sahnesinin karton modunda kare kare cizilmesi.

Gercek render (ses + ffmpeg) burada yok: render-smoke workflow'u onu yapiyor. Burada her senaryo sahte
bir zaman cizelgesiyle sessiz cizilir; amac gece 04:15'te kirmizi yakacak cizim hatalarini (eksik alan,
tema anahtari, tasma, bos kare) PR'da yakalamak.

    python -m unittest tests.test_cartoon -v
"""
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = os.environ.get("REQUIRE_RENDER_DEPS") == "1"

try:
    import importlib
    import numpy as np
    from PIL import Image, ImageDraw
    from worker import cartoon as TOON
    from worker import draw as D
    from worker import themes as TH
    from worker import themes as T
    from worker import build as BUILD
    from worker import cta as CTA
    from worker import style as STYLE
    from worker.byte import draw_byte_sticker
    from tests.test_scripts_draw import fake_timeline
    D.F_DISP(20)
    _OK, _WHY = True, ""
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)

SCRIPTS = sorted((ROOT / "content" / "scripts").glob("*.json"))
G_SCRIPTS = [p for p in SCRIPTS if json.loads(p.read_text()).get("series") == "G"]
ON = {"cartoon": {"enabled": True, "alternate": True, "share": 1.0}}


def lum(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def spec_g(i="x1"):
    return {"id": i, "series": "G", "beats": []}


@unittest.skipUnless(_OK or REQUIRED, f"render bagimliliklari yok: {_WHY}")
class Settings(unittest.TestCase):
    def test_default_is_off_and_garbage_is_off(self):
        self.assertFalse(TOON.settings({})["enabled"])
        self.assertFalse(TOON.settings({"cartoon": "yes"})["enabled"])
        self.assertFalse(TOON.settings({"cartoon": {"enabled": "true"}})["enabled"])   # yalniz gercek True
        self.assertTrue(TOON.settings(ON)["enabled"])

    def test_share_is_clamped(self):
        for raw, want in ((2, 1.0), (-1, 0.0), ("x", 1.0), (0.4, 0.4)):
            self.assertEqual(TOON.settings({"cartoon": {"enabled": True, "share": raw}})["share"], want)

    def test_apply_only_for_series_g_and_only_once(self):
        s = spec_g()
        self.assertTrue(TOON.apply(s, ON))
        self.assertFalse(TOON.apply(s, ON))                      # ikinci kez dokunmaz
        for ser in ("A", "B"):
            self.assertFalse(TOON.apply({**spec_g(), "series": ser}, ON), ser)
        self.assertFalse(TOON.apply(spec_g(), {}))
        self.assertFalse(TOON.apply(spec_g(), {"cartoon": {"enabled": False}}))

    def test_identity_is_deterministic_and_share_splits_videos(self):
        a, b = spec_g("same"), spec_g("same")
        TOON.apply(a, ON)
        TOON.apply(b, ON)
        self.assertEqual(a["_cartoon"], b["_cartoon"])
        self.assertIn(a["_cartoon"]["start"], (0, 1))
        half = {"cartoon": {"enabled": True, "share": 0.5}}
        n = sum(TOON.apply(spec_g(f"v{i}"), half) for i in range(200))
        self.assertTrue(70 < n < 130, n)                          # kabaca yarisi, hep ya da hic degil
        self.assertEqual(sum(TOON.apply(spec_g(f"v{i}"), {"cartoon": {"enabled": True, "share": 0}})
                             for i in range(20)), 0)

    def test_palette_variants_are_assigned_from_the_id_and_never_random(self):
        ids = [f"p{n:03d}-x" for n in range(300)]
        paper = [TOON.pick_palette(i, "paper") for i in ids]
        ink = [TOON.pick_palette(i, "ink") for i in ids]
        self.assertEqual(paper, [TOON.pick_palette(i, "paper") for i in ids])      # ayni kimlik, ayni renk
        self.assertEqual(set(paper), {"paper", *TH.PAPER_VARIANTS})
        self.assertEqual(set(ink), {"ink", *TH.INK_VARIANTS})
        share = paper.count("paper") / len(paper)
        self.assertTrue(0.25 < share < 0.45, share)                                # klasik krem ~%34
        self.assertTrue(0.40 < ink.count("ink") / len(ink) < 0.60)

    def test_profile_carries_the_variants_and_stage_themes_use_them(self):
        spec = spec_g("p077-x")
        TOON.apply(spec, {"cartoon": {"enabled": True}})
        prof = spec["_cartoon"]
        self.assertIn(prof["paper"], ("paper", *TH.PAPER_VARIANTS))
        self.assertIn(prof["ink"], ("ink", *TH.INK_VARIANTS))
        forced = {"alternate": True, "start": 0, "paper": "mint", "ink": "burgundy"}
        self.assertEqual(TOON.stage_themes(forced, 4), ["mint", "burgundy", "mint", "burgundy"])
        self.assertEqual(TOON.stage_themes({**forced, "alternate": False}, 2), ["mint", "mint"])
        # bilinmeyen / yanlis aileden gelen ad klasige duser (profil bozuksa video yine cizilir)
        self.assertEqual(TOON.stage_themes({"alternate": True, "start": 0, "paper": "forest", "ink": "mint"}, 2),
                         ["paper", "ink"])

    def test_old_profiles_without_variants_keep_the_classic_faces(self):
        self.assertEqual(TOON.stage_themes({"alternate": True, "start": 0}, 2), ["paper", "ink"])

    def test_every_variant_paints_its_own_background(self):
        seen = {}
        for name in ("paper", *TH.PAPER_VARIANTS, "ink", *TH.INK_VARIANTS):
            D.use_theme(name)
            img = D.build_bg()
            seen[name] = tuple(int(x) for x in np.asarray(img, np.float32)[200:1700].mean(axis=(0, 1)))
            self.assertTrue(D.STICKER, name)
        self.assertEqual(len(set(seen.values())), len(seen), seen)
        for name in TH.PAPER_VARIANTS:
            self.assertGreater(sum(seen[name]) / 3, 200, name)                       # kagit acik kalir
        for name in TH.INK_VARIANTS:
            self.assertLess(sum(seen[name]) / 3, 70, name)                            # koyu yuz koyu kalir
        D.use_theme("midnight")

    def test_stage_themes_alternate_or_stay_paper(self):
        alt = TOON.stage_themes({"alternate": True, "start": 0}, 5)
        self.assertEqual(alt, ["paper", "ink", "paper", "ink", "paper"])
        self.assertEqual(TOON.stage_themes({"alternate": True, "start": 1}, 3), ["ink", "paper", "ink"])
        self.assertEqual(TOON.stage_themes({"alternate": False, "start": 1}, 3), ["paper"] * 3)

    def test_shipped_brand_block_is_valid(self):
        raw = json.loads((ROOT / "brand.json").read_text())["cartoon"]
        self.assertIsInstance(raw["enabled"], bool)
        self.assertTrue(0.0 <= raw["share"] <= 1.0)
        self.assertIsInstance(raw["alternate"], bool)


@unittest.skipUnless(_OK or REQUIRED, f"render bagimliliklari yok: {_WHY}")
class Keywords(unittest.TestCase):
    def test_echo_scenes_get_no_automatic_keyword(self):
        """counter/equation/contrast ana sayiyi zaten dev puntoyla yaziyor: ustte tekrar etme."""
        self.assertIsNone(TOON.auto_kw("counter", {"to": 750, "suffix": " MB"}))
        self.assertIsNone(TOON.auto_kw("equation", {"result": {"value": "6 billion"}}))
        self.assertIsNone(TOON.auto_kw("contrast", {"verdict": "Raw"}))
        self.assertIsNone(TOON.auto_kw("dots", {"label": "95 printable"}))      # etiketi dev yaziyor
        self.assertIsNone(TOON.auto_kw("close", {"lines": ["a"]}))
        self.assertIsNone(TOON.auto_kw("byte_says", {"line": "hi"}))

    def test_title_and_label_scenes(self):
        self.assertEqual(TOON.auto_kw("title", {"kicker": "ASCII", "lines": ["128 characters"]}), "ASCII")
        self.assertEqual(TOON.auto_kw("title", {"lines": ["Tay"]}), "Tay")
        self.assertEqual(TOON.auto_kw("bits", {"label": "A · C · G · T"}), "A · C · G · T")
        self.assertEqual(TOON.auto_kw("terminal", {"label": "request"}), "request")

    def test_unsafe_or_long_text_is_dropped_not_drawn_as_boxes(self):
        self.assertIsNone(TOON.auto_kw("bits", {"label": "x" * (TOON.KW_MAX_CHARS + 1)}))
        self.assertIsNone(TOON.auto_kw("bits", {"label": "日本語"}))
        self.assertEqual(TOON.auto_kw("bits", {"label": "≈ 750"}), "~ 750")
        self.assertIsNone(TOON.auto_kw("bits", {"label": "   "}))
        self.assertIsNone(TOON.auto_kw("bits", ["not", "a", "dict"]))

    def test_plan_explicit_kw_overrides_and_empty_kw_suppresses(self):
        spec = {"beats": [{"id": "b1", "kw": "Hello"}, {"id": "b2"}, {"id": "b3", "kw": ""},
                          {"id": "b4", "kw": "Yes", "mark": "check"}, {"id": "b5", "kw": "No", "mark": "weird"}]}
        groups = [("title", {"kicker": "AUTO"}, ["b1"]), ("title", {"kicker": "AUTO"}, ["b2"]),
                  ("title", {"kicker": "AUTO"}, ["b3"]), ("counter", {"tone": "bad"}, ["b4"]),
                  ("bits", {"label": "L"}, ["b5"])]
        p = TOON.plan(spec, groups)
        self.assertEqual([x["kw"] for x in p], ["Hello", "AUTO", None, "Yes", "No"])
        self.assertEqual([x["mark"] for x in p], [None, None, None, "check", None])   # bilinmeyen isaret yok sayilir
        self.assertEqual(p[3]["tone"], "bad")

    def test_plan_is_per_beat_inside_a_scene(self):
        """Bir sahne birkac cumle surer: her cumlenin kendi kelimesi, kendi cumlesinde gorunur."""
        spec = {"beats": [{"id": "b1", "kw": "first"}, {"id": "b2"}, {"id": "b3", "kw": "third", "mark": "x"}]}
        p = TOON.plan(spec, [("title", {"kicker": "AUTO"}, ["b1", "b2", "b3"])])[0]
        self.assertEqual([(i["id"], i["kw"], i["mark"]) for i in p["items"]],
                         [("b1", "first", None), ("b3", "third", "x")])
        # elle kw ilk beat'te varsa otomatik eklenmez; yoksa otomatik en basa girer
        spec2 = {"beats": [{"id": "b1"}, {"id": "b2", "kw": "second"}]}
        p2 = TOON.plan(spec2, [("title", {"kicker": "AUTO"}, ["b1", "b2"])])[0]
        self.assertEqual([i["kw"] for i in p2["items"]], ["AUTO", "second"])
        spec3 = {"beats": [{"id": "b1", "kw": ""}, {"id": "b2", "kw": "second"}]}
        p3 = TOON.plan(spec3, [("title", {"kicker": "AUTO"}, ["b1", "b2"])])[0]
        self.assertEqual([i["kw"] for i in p3["items"]], ["second"])

    def test_mark_without_kw_is_ignored(self):
        p = TOON.plan({"beats": [{"id": "b1", "mark": "check"}]}, [("counter", {}, ["b1"])])[0]
        self.assertEqual(p["items"], [])
        self.assertIsNone(p["mark"])

    def test_item_at_follows_the_sentence_that_is_spoken(self):
        class Fake:                                              # Toon'un yalniz _item_at'in kullandigi alanlari
            plan = [{"items": [{"id": "b1", "kw": "one", "mark": None}, {"id": "b3", "kw": "three", "mark": None}]}]
            stages = [(0.0, 10.0)]
            S = {"b1": (0.0, 3.0), "b2": (3.0, 6.0), "b3": (6.0, 9.5)}
            _item_at = TOON.Toon._item_at
        f = Fake()
        self.assertIsNone(f._item_at(0, 0.1))                    # KW_DELAY dolmadan yok
        j, it, ts, te = f._item_at(0, 1.0)
        self.assertEqual((j, it["kw"]), (0, "one"))
        self.assertAlmostEqual(ts, TOON.KW_DELAY)
        self.assertLessEqual(te, 6.0 + TOON.KW_DELAY)            # sonraki kelime baslayinca oncekinin suresi biter
        self.assertEqual(f._item_at(0, 4.5)[1]["kw"], "one")     # b2'de kelime yok: sonuncu kapanma durumunda kalir
        self.assertEqual(f._item_at(0, 7.0)[1]["kw"], "three")
        self.assertLessEqual(f._item_at(0, 9.9)[3], 10.0 - 0.12)  # sahne bitisinden once kapanir

    def test_tone_of_reads_nested_tones(self):
        self.assertEqual(TOON.tone_of({"tone": "good"}), "good")
        self.assertEqual(TOON.tone_of({"a": {"tone": "bad"}}), "bad")
        self.assertEqual(TOON.tone_of({"accent": "mid"}), "mid")
        self.assertEqual(TOON.tone_of(None), "base")
        self.assertEqual(TOON.tone_of({"tone": ["x"]}), "base")


@unittest.skipUnless(_OK or REQUIRED, f"render bagimliliklari yok: {_WHY}")
class VoiceEnvelope(unittest.TestCase):
    def _wav(self, path, ch=2, sr=48000):
        t = np.arange(int(sr * 2.0)) / sr
        x = np.sin(2 * np.pi * 220 * t) * (t < 1.0)                 # 1 sn ses + 1 sn sessizlik
        x = np.repeat(x[:, None], ch, axis=1)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((x * 12000).astype(np.int16).tobytes())

    def test_envelope_follows_the_audio(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "v.wav"
            self._wav(p)
            env = TOON.voice_env(p, 60, 30, None)
        self.assertEqual(len(env), 60)
        self.assertGreater(env[:25].mean(), 0.5)
        self.assertLess(env[40:].mean(), 0.05)
        self.assertTrue(0.0 <= env.min() and env.max() <= 1.0)

    def test_missing_or_broken_audio_falls_back_to_word_timings(self):
        beats = [{"words": [{"w": "a", "s": 0.0, "e": 0.5}, {"w": "b", "s": 1.0, "e": 1.4}]}]
        env = TOON.voice_env("/nonexistent.wav", 60, 30, beats)
        self.assertGreater(env[5], 0.3)
        self.assertEqual(env[20], 0.0)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.wav"
            p.write_bytes(b"not a wav")
            self.assertEqual(len(TOON.voice_env(p, 30, 30, beats)), 30)
        self.assertEqual(len(TOON.voice_env("/nonexistent.wav", 10, 30, None)), 10)


@unittest.skipUnless(_OK or REQUIRED, f"render bagimliliklari yok: {_WHY}")
class Themes(unittest.TestCase):
    def test_cartoon_themes_are_not_in_the_dark_palette_pool(self):
        """editorial'in sanat yonetmeni ve pick() yalniz koyu paletten secer; karton temalari ayri."""
        self.assertEqual(set(T.NAMES), set(T.THEMES))
        self.assertTrue(set(T.TOON_THEMES).isdisjoint(T.NAMES))
        self.assertEqual(set(T.TOON_THEMES), {"paper", "ink", *T.PAPER_VARIANTS, *T.INK_VARIANTS})
        self.assertEqual(T.colors("paper"), T.TOON_THEMES["paper"])
        self.assertEqual(T.colors("midnight"), T.THEMES["midnight"])
        self.assertEqual(T.colors("nope"), {})

    def test_text_and_tones_are_readable_on_both_faces(self):
        for name, th in T.TOON_THEMES.items():
            self.assertGreaterEqual(contrast(th["ink"], th["bg0"]), 10, name)
            self.assertGreaterEqual(contrast(th["mute"], th["bg0"]), 4.0, name)
            for tone in ("good", "mid", "bad"):
                self.assertGreaterEqual(contrast(th[tone], th["bg0"]), 3.0, f"{name}/{tone}")
            self.assertGreaterEqual(contrast(th["on_accent"], th["good"]), 3.0, name)

    def test_dark_themes_keep_their_old_chrome_values(self):
        """Tema-duyarli panel/iz/ustu-yazi renkleri eklendi; koyu temalar ESKI sabit degerleri korumali."""
        for name in T.NAMES:
            D.use_theme(name)
            self.assertEqual((D.PANEL, D.PANEL2, D.ON_ACCENT, D.TRACK),
                             ((22, 22, 36), (16, 16, 28), (10, 10, 18), (20, 20, 32)), name)
            self.assertFalse(D.STICKER, name)
        D.use_theme("paper")
        self.assertTrue(D.STICKER)
        D.use_theme("midnight")

    def test_paper_background_is_light_cream_and_deterministic(self):
        D.use_theme("paper")
        a, b = D.build_bg(), D.build_bg()
        arr = np.asarray(a, np.float32)
        self.assertEqual(a.tobytes(), b.tobytes())
        self.assertGreater(arr.mean(), 200)
        self.assertGreater(arr[..., 0].mean(), arr[..., 2].mean() + 15)          # sicak (krem) ton
        D.use_theme("midnight")


@unittest.skipUnless(_OK or REQUIRED, f"render bagimliliklari yok: {_WHY}")
class Sprites(unittest.TestCase):
    def test_sticker_gets_a_light_outline_on_navy(self):
        """Koyu govdeli BYTE lacivert zeminde kayboluyordu: dis cizgi krem olmali."""
        bg = T.TOON_THEMES["ink"]["bg0"]
        img = Image.new("RGB", (500, 500), bg)
        draw_byte_sticker(ImageDraw.Draw(img), 250, 230, 0.6, pen=T.TOON_THEMES["ink"]["outline"],
                          shadow=T.TOON_THEMES["ink"]["shadow"])
        a = np.asarray(img, np.int16)
        light = (a.sum(axis=2) > 600).sum()
        self.assertGreater(light, 400)
        self.assertEqual(tuple(a[2, 2]), bg)                                  # kose dokunulmadi

    def test_scene_byte_goes_through_the_sticker_only_on_cartoon_themes(self):
        D.use_theme("midnight")
        img = Image.new("RGB", (500, 500), (7, 7, 12))
        D.byte(ImageDraw.Draw(img), 250, 230, 0.6)
        plain = np.asarray(img, np.int16).sum(axis=2).max()
        D.use_theme("ink")
        img2 = Image.new("RGB", (500, 500), (24, 31, 52))
        D.byte(ImageDraw.Draw(img2), 250, 230, 0.6)
        self.assertGreater(np.asarray(img2, np.int16).sum(axis=2).max(), 600)
        self.assertLess(plain, 600)                                           # koyu tema: eski cizim, cizgi yok
        D.use_theme("midnight")

    def test_caption_falls_back_to_inter_for_glyphs_fredoka_lacks(self):
        """'≈' Fredoka'da yok: bos fosforlu hap olarak cikiyordu (p031 'TWO SETS: ≈ 1.5')."""
        self.assertIs(TOON.caption_font("1.5"), TOON.caption_font("WORD"))
        self.assertIsNot(TOON.caption_font("≈"), TOON.caption_font("WORD"))
        self.assertIsNot(TOON.caption_font("→"), TOON.caption_font("WORD"))
        self.assertIsNot(TOON.caption_font("É"), TOON.caption_font("WORD"))

    def test_keyword_masks_fit_the_strip_and_are_cached(self):
        a = TOON.keyword_masks("A testing slip.", 1.0)
        self.assertIs(a, TOON.keyword_masks("A testing slip.", 1.0))
        strip, txt, w, h = a
        self.assertLessEqual(w, TOON.STRIP_X1 - TOON.STRIP_X0)
        self.assertEqual(strip.size, txt.size)
        self.assertGreater(np.asarray(strip).sum(), 0)
        long_ = TOON.keyword_masks("W" * TOON.KW_MAX_CHARS, 2.0)
        self.assertLessEqual(long_[2], TOON.STRIP_X1 - TOON.STRIP_X0)


def build_toon(spec, with_cta=True):
    """Sahte zaman cizelgesiyle Toon (ses/ffmpeg yok)."""
    brand = json.loads((ROOT / "brand.json").read_text())
    BUILD._inject_brand(spec, brand)
    if with_cta:
        CTA.apply(spec, brand, ROOT)
    STYLE.apply(spec, brand)
    assert TOON.apply(spec, brand), "brand.json'da karton acik olmali"
    mod = importlib.import_module("worker.series_g")
    S, dur = fake_timeline(spec)
    beats = []
    for b in spec["beats"]:
        s, e = S[b["id"]]
        ws = b.get("cap", b["say"]).split()
        n = max(1, len(ws))
        beats.append({"id": b["id"], "start": s, "end": e,
                      "words": [{"w": w, "s": s + (e - s) * i / n, "e": s + (e - s) * (i + 0.9) / n}
                                for i, w in enumerate(ws)]})
    tl = {"beats": beats, "duration": dur}
    stages = BUILD._stages(mod, S, dur, spec)
    close_t0 = stages[-1][0]
    corner = CTA.corner_window(dur, close_t0, spec["_cta"]["corner"]) if CTA.active(spec) else None
    D.use_theme("paper")
    return TOON.Toon(spec, stages, S, dur, tl, D.build_captions(beats), TOON.plan(spec, mod._group(spec["beats"])),
                     corner, spec["_cta"]["corner"].get("text", "") if corner else "", None, close_t0)


@unittest.skipUnless(_OK or REQUIRED, f"render bagimliliklari yok: {_WHY}")
class FirstFrame(unittest.TestCase):
    """Instagram/TikTok kapagi ve kaydirma karari ilk kareye bagli: t=0 karesi bos gelmemeli."""

    def test_intro_time_is_continuous_monotonic_and_ends_on_real_time(self):
        self.assertAlmostEqual(TOON.intro_time(0.0), TOON.INTRO_LEAD)
        self.assertAlmostEqual(TOON.intro_time(TOON.INTRO_END), TOON.INTRO_END)
        for t in (0.9, 1.0, 5.0, 40.0):
            self.assertEqual(TOON.intro_time(t), t)
        self.assertLess(TOON.INTRO_LEAD, TOON.INTRO_END, "turev pozitif kalmali: animasyon geri sarmaz")
        prev = -1.0
        for k in range(0, 121):
            v = TOON.intro_time(k / 120 * 1.2)
            self.assertGreater(v, prev, k)
            prev = v

    @staticmethod
    def _build(spec):
        """Gercek synth ilk beat'i t=0'da baslatir; testlerdeki sahte zaman cizelgesi 0,4 sn'de baslatiyor."""
        keep = globals()["fake_timeline"]

        def from_zero(sp):
            S, t = {}, 0.0
            for b in sp["beats"]:
                dur = len(b["say"].split()) / 2.6 * 0.86 + 0.18
                S[b["id"]] = (t, t + dur)
                t += dur + 0.18
            return S, t + 0.45
        globals()["fake_timeline"] = from_zero
        try:
            return build_toon(spec)
        finally:
            globals()["fake_timeline"] = keep

    @staticmethod
    def _ink(tn, img):
        """Orta bantta (sahne alani) ilk sahnenin ZEMININDEN belirgin farkli piksel sayisi (kagit de lacivert de olur)."""
        bg = np.asarray(tn.bgs[tn.themes[0]].convert("L"), np.int16)[600:1300]
        a = np.asarray(img.convert("L"), np.int16)[600:1300]
        return int((np.abs(a - bg) > 50).sum())

    def test_first_frame_already_shows_the_hook_scene(self):
        for p in G_SCRIPTS[:6]:
            tn = self._build(json.loads(p.read_text()))
            first, settled = self._ink(tn, tn.frame(0)), self._ink(tn, tn.frame(int(1.0 * D.FPS)))
            self.assertGreater(settled, 0, p.name)
            self.assertGreaterEqual(first, 0.5 * settled, f"{p.name}: t=0 karesi bos ({first} vs {settled})")

    def test_the_old_behaviour_would_have_failed_this(self):
        """Gercekten bir seyi olctugumuzu kanitla: ilk-kare kaymasi kapaliyken t=0 karesi bos."""
        tn = self._build(json.loads(G_SCRIPTS[0].read_text()))
        keep = TOON.intro_time
        try:
            TOON.intro_time = lambda t: t
            blank, settled = self._ink(tn, tn.frame(0)), self._ink(tn, tn.frame(int(1.0 * D.FPS)))
        finally:
            TOON.intro_time = keep
        self.assertLess(blank, 0.5 * settled)


@unittest.skipUnless(_OK or REQUIRED, f"render bagimliliklari yok: {_WHY}")
class Composition(unittest.TestCase):
    def test_iris_starts_on_the_old_scene_and_ends_on_the_new_one(self):
        tn = build_toon(json.loads(G_SCRIPTS[0].read_text()))
        old, new = Image.new("RGB", (D.W, D.H), (200, 30, 30)), Image.new("RGB", (D.W, D.H), (30, 30, 200))
        self.assertEqual(tn._iris(old, new, 0.0, 1), old)
        early, late = tn._iris(old, new, 0.1, 1), tn._iris(old, new, 0.97, 1)
        self.assertEqual(early.getpixel((2, 2)), (200, 30, 30))               # kose hala eski
        self.assertGreater(late.getpixel((D.W // 2, D.H // 2))[2], 150)       # orta yeni
        mid = np.asarray(tn._iris(old, new, 0.5, 1))
        self.assertTrue(((mid[..., 2] > 150).any()) and ((mid[..., 0] > 150).any()))

    def test_frame_is_deterministic_and_not_blank(self):
        spec = json.loads(next(p for p in SCRIPTS if "p031" in p.name).read_text())
        tn = build_toon(spec)
        t_mid = (tn.stages[2][0] + tn.stages[2][1]) / 2
        i = int(t_mid * D.FPS)
        f1, f2 = tn.frame(i), tn.frame(i)
        self.assertEqual(f1.size, (D.W, D.H))
        self.assertEqual(f1.tobytes(), f2.tobytes())
        self.assertGreater(np.asarray(f1, np.float32).std(), 20)
        # ust bant: BYTE sunucu solda (koyu/acik cikartma), saga dogru bos
        top = np.asarray(f1.crop((0, 100, 300, 330)), np.float32)
        self.assertGreater(top.std(), 15, "BYTE sunucu yok")

    def test_both_faces_appear_when_alternating(self):
        tn = build_toon(json.loads(next(p for p in SCRIPTS if "p031" in p.name).read_text()))
        self.assertEqual({TOON.family(x) for x in tn.themes}, {"paper", "ink"})
        means = []
        for k in (0, 1):
            t = (tn.stages[k][0] + tn.stages[k][1]) / 2
            means.append(float(np.asarray(tn.frame(int(t * D.FPS)))[400:1400].mean()))
        self.assertGreater(max(means) - min(means), 60)                        # biri acik, biri koyu

    def test_there_are_series_g_scripts_to_check(self):
        self.assertGreaterEqual(len(G_SCRIPTS), 30)

    def test_every_script_draws_in_cartoon_mode(self):
        """Her senaryo: iris, orta ve kapanis karelerinde patlama yok, bos kare yok, kare boyutu dogru."""
        problems = []
        for path in SCRIPTS:
            spec = json.loads(path.read_text())
            if spec.get("series") != "G":
                continue
            try:
                tn = build_toon(spec)
                n = len(tn.stages)
                times = [tn.stages[min(1, n - 1)][0] - TOON.IRIS_LEAD + 0.25 * TOON.IRIS_SECONDS,
                         (tn.stages[n // 2][0] + tn.stages[n // 2][1]) / 2,
                         tn.stages[-1][0] + 1.0]
                for t in times:
                    im = tn.frame(int(t * D.FPS))
                    if im.size != (D.W, D.H):
                        problems.append(f"{path.name}: kare boyutu {im.size}")
                    if np.asarray(im, np.float32).std() < 12:
                        problems.append(f"{path.name}: t={t:.1f} bos kare")
            except Exception as e:                                              # noqa: BLE001
                problems.append(f"{path.name}: {type(e).__name__}: {e}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_unknown_scene_still_raises_in_series_g(self):
        """Karton modu bozuk senaryoyu sessizce yutmamali (eski davranis: bilinmeyen sahne = hata)."""
        spec = json.loads(G_SCRIPTS[0].read_text())
        spec["beats"][1]["scene"] = "does_not_exist"
        with self.assertRaises(ValueError):
            importlib.import_module("worker.series_g")._group(spec["beats"])


if __name__ == "__main__":
    unittest.main()
