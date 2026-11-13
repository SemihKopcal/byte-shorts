"""
Begen / takip CTA'si (worker/cta.py, kapanis karti, kose etiketi, aciklama + sabitlenecek yorum).

Uc sey denetleniyor:
  1. KARAR saf ve deterministik: ayni senaryo + brand.json + experiments.json -> hep ayni sonuc
     (publish.yml bazi akislarda videoyu yeniden uretiyor; iki render birebir ayni olmali),
     deney kollarindaki senaryolara CTA eklenmiyor;
  2. METIN: aciklamaya platforma ozel satir (hashtag'lerden once), TikTok 300'u asmiyor,
     iki kez eklenmiyor, sabitlenecek yorum captions.md'ye giriyor;
  3. CIZIM (yalniz font/Pillow varsa): chip'ler yalniz CTA'li videoda ve kapanista cikiyor,
     kose etiketi yalniz penceresinde, altyazi bandina (y>=1430) hicbir sey dusmuyor.

    python -m unittest tests.test_cta -v
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from editorial import rules
from publish import manifest as M
from tests.fixtures import SCENES, good_spec
from worker import cta as C

ROOT = Path(__file__).resolve().parent.parent

BRAND = {
    "name": "BYTE", "handle": "@byte-knowledge",
    "handles": {"youtube": "@byte-knowledge", "instagram": "@byte_knows", "tiktok": "@byte_knows"},
    "description_footer": "BYTE measures things.",
    "tags_base": ["ai", "tech"],
    "hashtags": {"core": ["#ai", "#tech"], "per_series": {"G": ["#data"]}},
    "title_rules": {"max_chars": 60, "ban": ["SHOCKING", "!!!"]},
    "cta": {
        "enabled": True,
        "voice": "Like it, and follow Byte for more.",
        "card": {"like": "LIKE", "follow": "FOLLOW BYTE"},
        "corner": {"enabled": True, "text": "LIKE · FOLLOW", "at": 0.42, "seconds": 2.6},
        "description": {"youtube": "Like it? Subscribe to BYTE.",
                        "instagram": "Follow {handle} for more.",
                        "tiktok": "Follow {handle} for more."},
        "pinned_comment": "Sourced in the description.",
    },
}


def spec_g(sid="p900-test"):
    s = good_spec()
    s.update(id=sid, series="G")
    return s


def root_with(experiments=None) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    r = Path(tmp.name)
    (r / "content").mkdir()
    if experiments is not None:
        (r / "content" / "experiments.json").write_text(
            experiments if isinstance(experiments, str) else json.dumps(experiments))
    (r / "brand.json").write_text(json.dumps(BRAND))
    return tmp


EXP = {"e1": {"arms": {"a": ["p900-test", "p901"], "b": ["p902"]}}}


# ═══ settings ═══════════════════════════════════════════════════════════
class Settings(unittest.TestCase):
    def test_missing_block_means_disabled(self):
        for brand in ({}, {"cta": None}, {"cta": "x"}, {"cta": []}):
            cfg = C.settings(brand)
            self.assertFalse(cfg["enabled"], brand)
            self.assertTrue(cfg["voice"])

    def test_enabled_must_be_literally_true(self):
        for v in (1, "true", "yes", None, [1]):
            self.assertFalse(C.settings({"cta": {"enabled": v}})["enabled"], v)
        self.assertTrue(C.settings({"cta": {"enabled": True}})["enabled"])

    def test_skip_experiment_default_off_only_literal_true_turns_it_on(self):
        self.assertFalse(C.settings({"cta": {}})["skip_experiment_scripts"])
        for v in (1, "true", "yes", [1]):
            self.assertFalse(C.settings({"cta": {"skip_experiment_scripts": v}})["skip_experiment_scripts"], v)
        self.assertTrue(C.settings({"cta": {"skip_experiment_scripts": True}})["skip_experiment_scripts"])

    def test_spoken_defaults_on_and_only_literal_false_silences(self):
        self.assertTrue(C.settings({"cta": {}})["spoken"])
        for v in (0, "false", "no", None, [], {}):
            self.assertTrue(C.settings({"cta": {"spoken": v}})["spoken"], v)
        self.assertFalse(C.settings({"cta": {"spoken": False}})["spoken"])

    def test_voice_is_normalised_and_capped(self):
        cfg = C.settings({"cta": {"voice": "  Like   it\n now  "}})
        self.assertEqual(cfg["voice"], "Like it now")
        self.assertLessEqual(len(C.settings({"cta": {"voice": "x" * 999}})["voice"]), 120)

    def test_corner_numbers_are_clamped_and_junk_falls_back(self):
        c = C.settings({"cta": {"corner": {"at": 5, "seconds": 99}}})["corner"]
        self.assertEqual((c["at"], c["seconds"]), (0.9, 5.0))
        c = C.settings({"cta": {"corner": {"at": -3, "seconds": 0}}})["corner"]
        self.assertEqual((c["at"], c["seconds"]), (0.1, 1.0))
        c = C.settings({"cta": {"corner": {"at": "abc", "seconds": None}}})["corner"]
        self.assertEqual((c["at"], c["seconds"]), (0.42, 2.6))
        self.assertFalse(C.settings({"cta": {"corner": {"enabled": False}}})["corner"]["enabled"])

    def test_card_labels_upper_short_and_filled_in(self):
        card = C.settings({"cta": {"card": {"like": "like it", "follow": "x" * 99}}})["card"]
        self.assertEqual(card["like"], "LIKE IT")
        self.assertEqual(len(card["follow"]), 16)
        self.assertEqual(len(C.settings({"cta": {"card": {"like": "y" * 99}}})["card"]["like"]), 12)
        self.assertEqual(C.settings({"cta": {}})["card"], {"like": "LIKE", "follow": "FOLLOW BYTE"})

    def test_defaults_are_not_mutated_between_calls(self):
        C.settings({"cta": {"card": {"like": "mutated"}, "corner": {"at": 0.8}}})
        self.assertEqual(C.DEFAULTS["card"]["like"], "LIKE")
        self.assertEqual(C.DEFAULTS["corner"]["at"], 0.42)

    def test_repo_brand_json_is_valid_and_sane(self):
        brand = json.loads((ROOT / "brand.json").read_text())
        cfg = C.settings(brand)
        self.assertTrue(cfg["enabled"])
        self.assertFalse(cfg["spoken"], "13 Kasim karari: sonda konusulan CTA yok (olu zaman + dongu)")
        self.assertFalse(cfg["skip_experiment_scripts"], "deney videolari da CTA'li (iki kola ayni)")
        self.assertLessEqual(len(cfg["voice"].split()), 10, "sesli cumle kisa kalmali")
        self.assertIn("Byte", cfg["voice"], "Piper icin 'Byte' yazilmali (BYTE harf harf okunur)")
        for k in ("youtube", "instagram", "tiktok"):
            self.assertTrue(cfg["description"].get(k), k)
        self.assertTrue(cfg["pinned_comment"])
        self.assertIn("{handle}", cfg["description"]["instagram"])


# ═══ experiment_ids ═════════════════════════════════════════════════════
class ExperimentIds(unittest.TestCase):
    def test_collects_every_arm(self):
        with root_with(EXP) as t:
            self.assertEqual(C.experiment_ids(Path(t)), {"p900-test", "p901", "p902"})

    def test_missing_or_broken_file_is_empty_not_an_error(self):
        with root_with(None) as t:
            self.assertEqual(C.experiment_ids(Path(t)), set())
        for bad in ("{not json", "[]", "null", '"x"', "{}", '{"e": 5}', '{"e": {"arms": 3}}',
                    '{"e": {"arms": {"a": "p1"}}}', '{"e": {"arms": {"a": [1, null, "p2"]}}}'):
            with root_with(bad) as t:
                ids = C.experiment_ids(Path(t))
                self.assertIsInstance(ids, set, bad)
                self.assertTrue(all(isinstance(x, str) for x in ids), bad)
        with root_with('{"e": {"arms": {"a": [1, null, "p2"]}}}') as t:
            self.assertEqual(C.experiment_ids(Path(t)), {"p2"})

    def test_real_repo_file_parses(self):
        ids = C.experiment_ids(ROOT)
        self.assertIsInstance(ids, set)


# ═══ applies / apply ════════════════════════════════════════════════════
class Decision(unittest.TestCase):
    def test_plain_series_g_script_gets_cta(self):
        with root_with(None) as t:
            self.assertTrue(C.applies(spec_g(), BRAND, Path(t)))

    def test_disabled_never_applies(self):
        b = copy.deepcopy(BRAND)
        b["cta"]["enabled"] = False
        with root_with(None) as t:
            s = spec_g()
            self.assertFalse(C.apply(s, b, Path(t)))
            self.assertEqual(s, spec_g())
        self.assertFalse(C.applies(spec_g(), {}, ROOT))

    def test_experiment_arm_scripts_get_the_same_cta_by_default(self):
        """Iki kola da ayni CTA: kol karsilastirmasi bozulmaz."""
        with root_with(EXP) as t:
            for sid in ("p900-test", "p901", "p902", "p903"):
                self.assertTrue(C.applies(spec_g(sid), BRAND, Path(t)), sid)

    def test_experiment_arm_scripts_are_skipped_when_asked(self):
        b = copy.deepcopy(BRAND)
        b["cta"]["skip_experiment_scripts"] = True
        with root_with(EXP) as t:
            for sid in ("p900-test", "p901", "p902"):
                self.assertFalse(C.applies(spec_g(sid), b, Path(t)), sid)
            self.assertTrue(C.applies(spec_g("p903"), b, Path(t)))

    def test_only_series_g_with_a_close_beat(self):
        with root_with(None) as t:
            r = Path(t)
            s = spec_g()
            s["series"] = "A"
            self.assertFalse(C.applies(s, BRAND, r))
            s = spec_g()
            del s["beats"][-1]["scene"]
            self.assertFalse(C.applies(s, BRAND, r))
            s = spec_g()
            s["beats"][-1]["scene"] = "title"
            self.assertFalse(C.applies(s, BRAND, r))
            for beats in ([], None):
                s = spec_g()
                s["beats"] = beats
                self.assertFalse(C.applies(s, BRAND, r))
            self.assertFalse(C.applies({}, BRAND, r))

    def test_apply_adds_one_spoken_beat_and_card_data(self):
        with root_with(None) as t:
            s = spec_g()
            n = len(s["beats"])
            self.assertTrue(C.apply(s, BRAND, Path(t)))
        self.assertEqual(len(s["beats"]), n + 1)
        last = s["beats"][-1]
        self.assertEqual(last["id"], C.BEAT_ID)
        self.assertEqual(last["say"], BRAND["cta"]["voice"])
        self.assertEqual(last["cap"], last["say"])
        self.assertNotIn("scene", last, "sahnesiz: kapanis grubuna katilmali, yeni sahne acmamali")
        self.assertEqual(s["beats"][-2]["data"]["cta"], {"like": "LIKE", "follow": "FOLLOW BYTE"})
        self.assertEqual(s["beats"][-2]["data"]["lines"], ["Length sets the bill."], "eski veri korunmali")
        self.assertTrue(C.active(s))
        self.assertEqual(s["_cta"]["corner"]["text"], "LIKE · FOLLOW")

    def test_silent_mode_adds_card_and_corner_but_no_spoken_beat(self):
        b = copy.deepcopy(BRAND)
        b["cta"]["spoken"] = False
        with root_with(None) as t:
            s = spec_g()
            n = len(s["beats"])
            self.assertTrue(C.apply(s, b, Path(t)))
        self.assertEqual(len(s["beats"]), n, "sessiz kipte yeni beat yok")
        self.assertNotEqual(s["beats"][-1]["id"], C.BEAT_ID)
        self.assertEqual(s["beats"][-1]["data"]["cta"], {"like": "LIKE", "follow": "FOLLOW BYTE"})
        self.assertEqual(s["beats"][-1]["data"]["lines"], ["Length sets the bill."], "eski veri korunmali")
        self.assertTrue(C.active(s))
        self.assertFalse(s["_cta"]["spoken"])
        self.assertEqual(s["_cta"]["corner"]["text"], "LIKE · FOLLOW")

    def test_silent_mode_is_idempotent_and_does_not_need_a_voice_line(self):
        b = copy.deepcopy(BRAND)
        b["cta"]["spoken"] = False
        b["cta"]["voice"] = ""
        with root_with(None) as t:
            s = spec_g()
            self.assertTrue(C.apply(s, b, Path(t)))
            once = copy.deepcopy(s)
            self.assertFalse(C.apply(s, b, Path(t)), "ikinci kez dokunmamali (beat yok, _cta isareti var)")
        self.assertEqual(s, once)

    def test_spoken_mode_with_an_empty_voice_still_means_no_cta(self):
        b = copy.deepcopy(BRAND)
        b["cta"]["voice"] = ""
        with root_with(None) as t:
            s = spec_g()
            self.assertFalse(C.apply(s, b, Path(t)))
            self.assertEqual(s, spec_g())

    def test_apply_is_idempotent(self):
        with root_with(None) as t:
            s = spec_g()
            self.assertTrue(C.apply(s, BRAND, Path(t)))
            once = copy.deepcopy(s)
            self.assertFalse(C.apply(s, BRAND, Path(t)))
        self.assertEqual(s, once)

    def test_decision_is_deterministic(self):
        """Ayni girdi -> ayni cikti; zamana/built.json'a bagli degil (publish.yml yeniden render eder)."""
        with root_with(EXP) as t:
            r = Path(t)
            (r / "content" / "built.json").write_text("[]")
            a, b = spec_g("p950"), spec_g("p950")
            C.apply(a, BRAND, r)
            (r / "content" / "built.json").write_text('["p950", "p001"]')
            C.apply(b, BRAND, r)
        self.assertEqual(a, b)

    def test_not_applicable_leaves_spec_untouched(self):
        b = copy.deepcopy(BRAND)
        b["cta"]["skip_experiment_scripts"] = True
        with root_with(EXP) as t:
            s = spec_g("p901")
            before = copy.deepcopy(s)
            self.assertFalse(C.apply(s, b, Path(t)))
        self.assertEqual(s, before)
        self.assertFalse(C.active(s))

    def test_authoring_rules_still_ban_cta_in_script_text(self):
        """CTA'yi hat ekler; senaryoda yazarsan iki kez soylenir -> gate hala reddeder."""
        s = spec_g()
        s["beats"][2]["say"] = "Subscribe for more of these."
        problems = rules.validate_script(s, SCENES)
        self.assertTrue(any("yasakli" in p for p in problems), problems)


# ═══ kose etiketi penceresi ═════════════════════════════════════════════
class CornerWindow(unittest.TestCase):
    CFG = {"enabled": True, "at": 0.42, "seconds": 2.6}

    def test_normal_video(self):
        w = C.corner_window(39.0, 34.0, self.CFG)
        self.assertAlmostEqual(w[0], 0.42 * 39.0, places=2)
        self.assertAlmostEqual(w[1] - w[0], 2.6, places=2)

    def test_never_overlaps_the_close_card(self):
        for dur, close in ((39.0, 34.0), (30.0, 12.0), (50.0, 49.0)):
            w = C.corner_window(dur, close, self.CFG)
            if w:
                self.assertLessEqual(w[1], close - 0.59, (dur, close))
                self.assertGreaterEqual(w[0], 3.0)

    def test_too_early_or_disabled_is_none(self):
        self.assertIsNone(C.corner_window(39.0, 5.0, self.CFG))       # kapanis 5. sn'de: yer yok
        self.assertIsNone(C.corner_window(6.0, 5.0, {**self.CFG, "at": 0.1}))
        self.assertIsNone(C.corner_window(39.0, 34.0, {**self.CFG, "enabled": False}))
        self.assertIsNone(C.corner_window(39.0, 34.0, {}))

    def test_clamped_window_is_inside_the_video(self):
        w = C.corner_window(20.0, 14.0, {"enabled": True, "at": 0.9, "seconds": 5.0})
        self.assertIsNotNone(w)
        self.assertLessEqual(w[1], 14.0)


# ═══ aciklama / manifest ════════════════════════════════════════════════
class DescriptionLines(unittest.TestCase):
    CFG = C.settings(BRAND)

    def test_line_for_fills_the_platform_handle(self):
        self.assertEqual(C.line_for(self.CFG, "instagram", BRAND), "Follow @byte_knows for more.")
        self.assertEqual(C.line_for(self.CFG, "youtube", BRAND), "Like it? Subscribe to BYTE.")
        self.assertEqual(C.line_for(self.CFG, "unknown", BRAND), "")
        b = {**BRAND, "handles": {}}
        self.assertEqual(C.line_for(self.CFG, "tiktok", b), "Follow @byte-knowledge for more.")

    def copy(self):
        return {"title": "T", "youtube": "Hook sentence.\n\nSources / method:\n- https://a.example\n\n#ai #tech",
                "instagram": "Hook sentence.\n\nSources / method:\n- a\n\n#ai", "tiktok": "Hook. #ai #tech"}

    def test_cta_line_follows_the_hook_paragraph(self):
        out = M.with_cta(self.copy(), BRAND, self.CFG)
        self.assertTrue(out["youtube"].startswith("Hook sentence.\n\nLike it? Subscribe to BYTE.\n\nSources / method:"))
        self.assertTrue(out["instagram"].startswith("Hook sentence.\n\nFollow @byte_knows for more.\n\nSources"))

    def test_tiktok_line_goes_before_the_hashtags(self):
        out = M.with_cta(self.copy(), BRAND, self.CFG)
        self.assertEqual(out["tiktok"], "Hook. Follow @byte_knows for more. #ai #tech")

    def test_tiktok_without_hashtags_appends(self):
        c = self.copy()
        c["tiktok"] = "Just a caption."
        self.assertEqual(M.with_cta(c, BRAND, self.CFG)["tiktok"], "Just a caption. Follow @byte_knows for more.")

    def test_tiktok_never_goes_over_300(self):
        c = self.copy()
        c["tiktok"] = "x" * 285 + " #ai"
        out = M.with_cta(c, BRAND, self.CFG)
        self.assertEqual(out["tiktok"], c["tiktok"], "300'u asacaksa eklenmemeli")

    def test_single_paragraph_description(self):
        c = self.copy()
        c["youtube"] = "Only one paragraph. Sources"
        out = M.with_cta(c, BRAND, self.CFG)
        self.assertEqual(out["youtube"], "Only one paragraph. Sources\n\nLike it? Subscribe to BYTE.")

    def test_idempotent_and_does_not_mutate_input(self):
        c = self.copy()
        before = copy.deepcopy(c)
        once = M.with_cta(c, BRAND, self.CFG)
        self.assertEqual(c, before)
        self.assertEqual(M.with_cta(once, BRAND, self.CFG), once)

    def test_no_line_for_a_platform_means_untouched(self):
        cfg = C.settings({"cta": {"enabled": True, "description": {"youtube": "Only YT."}}})
        out = M.with_cta(self.copy(), BRAND, cfg)
        self.assertEqual(out["instagram"], self.copy()["instagram"])
        self.assertEqual(out["tiktok"], self.copy()["tiktok"])
        self.assertIn("Only YT.", out["youtube"])

    def test_result_still_passes_copy_validation(self):
        out = M.with_cta(self.copy(), BRAND, self.CFG)
        self.assertEqual(M.validate_copy(out, BRAND), [])


class ManifestAndCaptions(unittest.TestCase):
    def build(self, spec, cta_on, root=None):
        if cta_on:
            with root_with(None) as t:
                C.apply(spec, BRAND, Path(t))
        with tempfile.TemporaryDirectory() as tmp:
            r = Path(tmp)
            (r / "brand.json").write_text(json.dumps(BRAND))
            return M.build_manifest(spec, {"duration": 41.2}, Path("v.mp4"), r)

    def test_manifest_with_cta(self):
        man = self.build(spec_g(), True)
        self.assertIn("Like it? Subscribe to BYTE.", man["description"])
        self.assertEqual(man["description"], man["captions"]["youtube"])
        self.assertIn("Follow @byte_knows for more.", man["captions"]["instagram"])
        self.assertIn("Follow @byte_knows for more.", man["captions"]["tiktok"])
        self.assertEqual(man["cta"], {"pinned_comment": "Sourced in the description."})
        self.assertEqual(M.validate_copy({**man["captions"], "title": man["title"]}, BRAND), [])

    def test_manifest_without_cta_is_exactly_as_before(self):
        man = self.build(spec_g(), False)
        self.assertNotIn("cta", man)
        self.assertNotIn("Subscribe", man["description"])
        self.assertNotIn("Follow @byte_knows", man["captions"]["tiktok"])

    def test_captions_markdown_has_the_manual_pin_section_only_with_cta(self):
        md = M.captions_markdown(self.build(spec_g(), True))
        self.assertIn("## YouTube sabitlenecek yorum (elle)", md)
        self.assertIn("Sourced in the description.", md)
        self.assertIn("API yorum sabitlemeye izin vermiyor", md)
        md0 = M.captions_markdown(self.build(spec_g(), False))
        self.assertNotIn("sabitlenecek", md0)

    def test_empty_pinned_comment_adds_no_section(self):
        man = self.build(spec_g(), False)
        man["cta"] = {"pinned_comment": ""}
        self.assertNotIn("sabitlenecek", M.captions_markdown(man))


# ═══ cizim ══════════════════════════════════════════════════════════════
try:
    from PIL import Image, ImageChops, ImageDraw
    from worker import draw as D
    from worker import scenes as S
    from worker.series_g import stages
    D.F_DISP(20)                       # font yoksa burada patlar
    _OK, _WHY = True, ""
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)

CAPTION_Y = 1430                       # bunun alti Shorts altyazi / arayuz bandi


def _canvas():
    im = Image.new("RGB", (D.W, D.H), D.BG0)
    return im, ImageDraw.Draw(im)


def _changed(a, b, box=None):
    diff = ImageChops.difference(a, b).convert("L")
    if box:
        diff = diff.crop(box)
    return diff.getbbox()


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY}")
class Drawing(unittest.TestCase):
    CLOSE = {"lines": ["Length sets the bill."], "handle": "@byte-knowledge"}
    CARD = {"like": "LIKE", "follow": "FOLLOW BYTE"}

    def close_frame(self, t, cta=None, cta_t0=1.5):
        data = dict(self.CLOSE)
        if cta:
            data["cta"] = cta
            data["cta_t0"] = cta_t0
        im, d = _canvas()
        S.close(d, t, 0.0, 6.0, data)
        return im

    def test_silent_cta_chips_come_from_the_close_scene_not_from_a_beat(self):
        """cta.spoken=false: 'cta' beat'i yok; chip'ler kapanis sahnesi baslayinca (SILENT_CTA_DELAY) cikar."""
        b = copy.deepcopy(BRAND)
        b["cta"]["spoken"] = False
        silent, plain = spec_g(), spec_g()
        with root_with(None) as t:
            C.apply(silent, b, Path(t))
        S_, t_ = {}, 0.0
        for bt in plain["beats"]:
            S_[bt["id"]] = (t_, t_ + 2.0)
            t_ += 2.2

        def frame(spec, t):
            fn = stages(spec, S_, t_ + 0.45)[-1][2]
            im, d = _canvas()
            fn(d, t, S_, spec)
            return im

        t0 = stages(plain, S_, t_ + 0.45)[-1][0]
        self.assertIsNone(_changed(frame(silent, t0 + 0.1), frame(plain, t0 + 0.1)), "chip'ler gec cikmali")
        self.assertIsNotNone(_changed(frame(silent, t0 + 2.5), frame(plain, t0 + 2.5)), "chip'ler cikmali")

    def test_chips_appear_only_with_cta_and_after_it_starts(self):
        before = self.close_frame(1.0, self.CARD)
        plain = self.close_frame(1.0)
        self.assertIsNone(_changed(before, plain), "CTA konusmadan chip cizilmemeli")
        later = self.close_frame(3.5, self.CARD)
        self.assertIsNotNone(_changed(later, self.close_frame(3.5)), "chip'ler cizilmedi")

    def test_chips_fill_in_sequence(self):
        t0 = 1.5
        shown = self.close_frame(t0 + 0.6, self.CARD, t0)
        like_on = self.close_frame(t0 + 1.2, self.CARD, t0)
        both = self.close_frame(t0 + 2.4, self.CARD, t0)
        self.assertIsNotNone(_changed(shown, like_on))
        self.assertIsNotNone(_changed(like_on, both))

    def test_nothing_drawn_in_the_caption_band(self):
        for t in (1.2, 2.0, 3.0, 5.5):
            with_cta = self.close_frame(t, self.CARD)
            plain = self.close_frame(t)
            self.assertIsNone(_changed(with_cta, plain, (0, CAPTION_Y, D.W, D.H)), f"t={t}")

    def test_chip_row_stays_inside_the_margins_even_with_long_labels(self):
        long_card = {"like": "W" * 12, "follow": "W" * 16}   # settings() sinirinin en uzunu
        im = self.close_frame(5.0, long_card)
        plain = self.close_frame(5.0)
        box = _changed(im, plain)
        self.assertIsNotNone(box)
        self.assertGreaterEqual(box[0], S.MARGIN - 4)
        self.assertLessEqual(box[2], D.W - S.MARGIN + 4)

    def test_malformed_cta_data_does_not_crash_or_draw(self):
        for junk in (None, "x", 5, [], {"like": None, "follow": 3}):
            im, d = _canvas()
            S.close(d, 5.0, 0.0, 6.0, {**self.CLOSE, "cta": junk, "cta_t0": 1.0})

    def test_byte_points_right_while_the_cta_is_spoken(self):
        idle = self.close_frame(1.0, self.CARD, 1.5)
        pointing = self.close_frame(3.0, self.CARD, 1.5)
        box = (int(D.W / 2 - 200), int(S.MID - 330 + 300), int(D.W / 2 + 260), int(S.MID - 330 + 620))
        self.assertIsNotNone(_changed(idle, pointing, box))

    def test_corner_label_only_inside_its_window_and_above_the_scene_area(self):
        window = (10.0, 12.6)
        base, _ = _canvas()

        def frame(t):
            im, d = _canvas()
            D.draw_cta_corner(d, t, window, "LIKE · FOLLOW")
            return im

        self.assertIsNone(_changed(frame(9.0), base))
        self.assertIsNone(_changed(frame(13.0), base))
        mid = frame(11.3)
        box = _changed(mid, base)
        self.assertIsNotNone(box)
        self.assertGreaterEqual(box[1], 150, "BYTE rozetinin altinda baslamali")
        self.assertLessEqual(box[3], 330, "sahne alanina (330+) girmemeli")
        self.assertLessEqual(box[2], D.W / 2, "sag ust Shorts arayuzune dusmemeli")
        self.assertLess(_changed(frame(10.05), base)[2], box[2] + 1)

    def test_corner_label_handles_empty_inputs(self):
        im, d = _canvas()
        D.draw_cta_corner(d, 5.0, None, "x")
        D.draw_cta_corner(d, 5.0, (1.0, 2.0), "")

    def test_stage_passes_the_cta_start_to_the_close_card(self):
        """Kapanis grubu cta beat'ini kapsar ve chip'ler o beat'in basladigi anda cikar."""
        s = spec_g()
        with root_with(None) as t:
            C.apply(s, BRAND, Path(t))
        ids = [b["id"] for b in s["beats"]]
        S_ = {bid: (i * 3.0, i * 3.0 + 2.7) for i, bid in enumerate(ids)}
        dur = S_[ids[-1]][1]
        st = stages(s, S_, dur)
        t0, t1, fn = st[-1]
        self.assertEqual(t0, S_["b11"][0], "kapanis sahnesi b11'de baslar, cta beat'i ayni grupta")
        cta_t = S_["cta"][0]
        im, d = _canvas()
        fn(d, cta_t - 0.5, S_, s)
        pre = im
        im2, d2 = _canvas()
        fn(d2, cta_t + 2.5, S_, s)
        self.assertIsNotNone(_changed(pre, im2))
        # CTA'siz senaryoda ayni sahne chip cizmez
        plain = spec_g()
        ids0 = [b["id"] for b in plain["beats"]]
        S0 = {bid: (i * 3.0, i * 3.0 + 2.7) for i, bid in enumerate(ids0)}
        fn0 = stages(plain, S0, S0[ids0[-1]][1])[-1][2]
        a, da = _canvas()
        fn0(da, S0["b11"][0] + 2.5, S0, plain)
        b_, db = _canvas()
        S.close(db, S0["b11"][0] + 2.5, S0["b11"][0], S0[ids0[-1]][1], plain["beats"][-1]["data"])
        self.assertIsNone(_changed(a, b_))


if __name__ == "__main__":
    unittest.main()
