"""
Video, SON KELIMEDEN sonra biter: sesin son kelimesi kesilmez.

Eski hata: sure = son beat'in bitisi + bosluk - 0.18, ama son beat'ten sonra bosluk 0 oldugu icin
video sesten 0.18 sn once bitiyordu ("...for mo-" diye kesiliyordu). Piper yerine sahte bir
ses uretici, ffmpeg gercek; ffmpeg yoksa atlanir (sade CI "test" isi).

    python -m unittest tests.test_synth_tail -v
"""
import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

try:
    from worker import synth
    _OK = shutil.which("ffmpeg") is not None
    _WHY = "ffmpeg yok"
except Exception as e:                 # noqa: BLE001
    _OK, _WHY = False, str(e)


def fake_piper(text, path, voice, i=0, shift=0.0):
    """Kelime basina 0.3 sn'lik 440 Hz ton (sessizlik degil: esik testleri anlamli olsun)."""
    n = max(1, len(text.split())) * 3 * 2205
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(synth.SR)
        w.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 440 * k / synth.SR)))
                               for k in range(n)))
    return n / synth.SR


def rms(samples):
    return math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))


@unittest.skipUnless(_OK, f"render bagimliliklari yok: {_WHY}")
class VideoEndsAfterTheLastWord(unittest.TestCase):
    SPEC = {"beats": [{"id": "b1", "say": "One two three four."},
                      {"id": "b2", "say": "Five six.", "scene": "close"},
                      {"id": "cta", "say": "Like it, and follow Byte for more."}]}

    def run_synth(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(synth, "_piper", fake_piper):
            tl = synth.synthesize(self.SPEC, Path(tmp.name), Path("unused.onnx"))
        with wave.open(str(Path(tmp.name) / "voice.wav")) as w:
            sr, ch = w.getframerate(), w.getnchannels()
            raw = w.readframes(w.getnframes())
        samples = struct.unpack(f"<{len(raw) // 2}h", raw)[::ch]
        return tl, samples, sr

    def test_duration_is_last_word_plus_the_pad(self):
        tl, _, _ = self.run_synth()
        self.assertAlmostEqual(tl["duration"], tl["beats"][-1]["end"] + synth.END_PAD, places=2)
        self.assertGreater(tl["duration"], tl["beats"][-1]["end"], "video sesten ONCE bitiyor")

    def test_audio_file_is_at_least_as_long_as_the_video(self):
        tl, samples, sr = self.run_synth()
        self.assertGreaterEqual(len(samples) / sr, tl["duration"] - 0.02,
                                "ses videodan kisa: -shortest son kelimeyi keser")

    def test_last_word_is_fully_present_and_followed_by_silence(self):
        tl, samples, sr = self.run_synth()
        end = tl["beats"][-1]["end"]
        word = samples[int((end - 0.25) * sr):int((end - 0.05) * sr)]
        tail = samples[int((end + 0.10) * sr):int((tl["duration"] - 0.02) * sr)]
        self.assertGreater(rms(word), 500, "son kelimenin sonu sessiz: kesilmis")
        self.assertLess(rms(tail), 100, "son kelimeden sonra sessizlik olmali")

    def test_pace_shift_is_passed_to_piper_and_gaps_scale(self):
        calls = []

        def spy(text, path, voice, i=0, shift=0.0):
            calls.append(shift)
            return fake_piper(text, path, voice, i, shift)

        spec = {**self.SPEC, "_style": {"pace": {"length_delta": 0.03, "gap_scale": 1.1}}}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(synth, "_piper", spy):
            tl_fast = synth.synthesize(spec, Path(tmp), Path("u.onnx"))
        self.assertEqual(calls, [0.03] * 3)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(synth, "_piper", fake_piper):
            tl_neutral = synth.synthesize(self.SPEC, Path(tmp), Path("u.onnx"))
        b1, b2 = tl_fast["beats"][0], tl_fast["beats"][1]
        n1, n2 = tl_neutral["beats"][0], tl_neutral["beats"][1]
        self.assertAlmostEqual((b2["start"] - b1["end"]), (n2["start"] - n1["end"]) * 1.1, delta=0.01)

    def test_pace_is_neutral_without_a_style(self):
        calls = []

        def spy(text, path, voice, i=0, shift=0.0):
            calls.append(shift)
            return fake_piper(text, path, voice, i, shift)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(synth, "_piper", spy):
            synth.synthesize(self.SPEC, Path(tmp), Path("u.onnx"))
        self.assertEqual(calls, [0.0] * 3)

    def test_pad_is_a_breath_not_dead_air(self):
        self.assertTrue(0.2 <= synth.END_PAD <= 0.8)


if __name__ == "__main__":
    unittest.main()
