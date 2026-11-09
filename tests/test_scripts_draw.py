"""
Her senaryo, SESSIZ ve FFMPEG'SIZ, kare kare cizilebiliyor mu?

Gercek render ses sentezi + ffmpeg ister ve dakikalar surer. Ama bir senaryoyu
geceleyin kirmizi yakan seylerin cogu cizim hatasidir: bilinmeyen sahne turu,
eksik alan, tasan ya da bos kare. Burada her senaryonun her sahnesi, sesin
suresini kelime sayisindan tahmin eden sahte bir zaman cizelgesiyle, pencerenin
basinda / ortasinda / sonunda cizilir: patlama yok ve en az bir ornekte ekran bos
degil.

Font yoksa (sade CI "test" isi) atlanir. render-smoke workflow'u fontlari kurar ve
REQUIRE_RENDER_DEPS=1 ile calistirir: orada eksik bagimlilik atlama degil HATA.

    python -m unittest tests.test_scripts_draw -v
"""
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = os.environ.get("REQUIRE_RENDER_DEPS") == "1"

try:
    from PIL import Image, ImageChops, ImageDraw
    from worker import draw as D
    from worker import themes as T
    import importlib
    D.F_DISP(20)                       # font yoksa burada patlar
    _OK, _WHY = True, ""
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)

SCRIPTS = sorted((ROOT / "content" / "scripts").glob("*.json"))


def fake_timeline(spec):
    """Gercek sesin yaklasigi: ~2.6 kelime/sn x 0.86 (Piper), beat arasi 0.18 sn."""
    S, t = {}, 0.4
    for b in spec["beats"]:
        dur = len(b["say"].split()) / 2.6 * 0.86 + 0.18
        S[b["id"]] = (t, t + dur)
        t += dur + 0.18
    return S, t + 1.0


def draw_script(spec):
    """(sahne sayisi, ornek sayisi, bos kalan sahne adlari)"""
    theme = D.use_theme(T.pick(spec, []))
    spec["_theme"] = theme
    mod = importlib.import_module(f"worker.series_{spec['series'].lower()}")
    S, duration = fake_timeline(spec)
    blank = []
    if hasattr(mod, "stages"):                       # senaryodan okuyan seri (G)
        stages = mod.stages(spec, S, duration)
    else:                                            # elle yazilmis seriler (A, B)
        stages = [(S[a][0], duration if b is None else S[b][1] + 0.30, fn)
                  for a, b, fn in mod.STAGES]
    samples = 0
    for t0, t1, fn in stages:
        seen_ink = False
        for t in (t0 + 0.3, (t0 + t1) / 2, t1 - 0.35):
            img = Image.new("RGB", (D.W, D.H), (8, 8, 10))
            fn(ImageDraw.Draw(img), t, S, spec)
            samples += 1
            if ImageChops.difference(img, Image.new("RGB", (D.W, D.H), (8, 8, 10))).getbbox():
                seen_ink = True
        if not seen_ink:
            blank.append(f"{t0:.1f}-{t1:.1f}s")
    return len(stages), samples, blank


@unittest.skipUnless(_OK or REQUIRED, f"render bagimliliklari yok: {_WHY}")
class EveryScriptDraws(unittest.TestCase):
    def test_render_dependencies_are_present(self):
        self.assertTrue(_OK, f"render bagimliliklari eksik: {_WHY}")

    def test_there_are_scripts_to_check(self):
        self.assertGreaterEqual(len(SCRIPTS), 30)

    def test_every_script_draws_every_stage_without_error_and_not_blank(self):
        problems = []
        for path in SCRIPTS:
            spec = json.loads(path.read_text())
            try:
                n, samples, blank = draw_script(spec)
            except Exception as e:                                  # noqa: BLE001
                problems.append(f"{path.name}: {type(e).__name__}: {e}")
                continue
            if n < 3:
                problems.append(f"{path.name}: yalniz {n} sahne penceresi")
            if blank:
                problems.append(f"{path.name}: bos kalan pencereler {blank}")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
