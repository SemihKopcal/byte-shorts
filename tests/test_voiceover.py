"""
Klon ses (kendi sesin): sozlesme, kesme/bicim, synth entegrasyonu, R2 gidis-donus, CTA cumlesi dahil.
Ag yok, GPU yok, Piper yok: Piper sahte, R2 sahte, ses dosyalari sinus. ffmpeg yoksa ilgili testler atlanir.

    python -m unittest tests.test_voiceover -v
"""
import contextlib
import io
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from worker import voiceover as V                # noqa: E402
import r2_voice                                  # noqa: E402
import voice_lines                               # noqa: E402

try:
    from worker import synth
    _FF = shutil.which("ffmpeg") is not None
except Exception:                                # noqa: BLE001
    _FF = False


def write_tone(path, seconds=1.0, sr=24000, lead=0.0, tail=0.0, amp=9000):
    """lead/tail: basta/sonda sessizlik (sn). Ortada 440 Hz."""
    n_l, n_t, n = int(lead * sr), int(tail * sr), int(seconds * sr)
    frames = [0] * n_l + [int(amp * math.sin(2 * math.pi * 440 * k / sr)) for k in range(n)] + [0] * n_t
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack(f"<{len(frames)}h", *frames))


def spec_of(*says):
    beats = [{"id": f"b{i + 1}", "say": s} for i, s in enumerate(says[:-1])]
    beats.append({"id": "cta", "say": says[-1], "scene": "close"})
    return {"id": "t001-demo", "beats": beats}


def make_dir(spec, tmp, **tone):
    d = Path(tmp) / spec["id"]
    d.mkdir(parents=True)
    for b in spec["beats"]:
        write_tone(d / f"{b['id']}.wav", **tone)
    (d / "manifest.json").write_text(json.dumps(V.make_manifest(spec, "semih")))
    return d


class Contract(unittest.TestCase):
    def test_sha_ignores_whitespace_but_not_words(self):
        self.assertEqual(V.say_sha("One  two\nthree."), V.say_sha("One two three."))
        self.assertNotEqual(V.say_sha("One two three."), V.say_sha("One two four."))

    def test_manifest_lists_every_beat_including_the_cta(self):
        s = spec_of("First.", "Second.", "Like it, and follow Byte for more.")
        m = V.make_manifest(s, "semih")
        self.assertEqual(list(m["beats"]), ["b1", "b2", "cta"])
        self.assertEqual(m["v"], V.VERSION)

    def test_check_accepts_a_complete_directory(self):
        s = spec_of("First.", "Second.", "Follow.")
        with tempfile.TemporaryDirectory() as t:
            d = make_dir(s, t)
            self.assertEqual(V.check(s, d), "")

    def test_check_names_the_problem(self):
        s = spec_of("First.", "Second.", "Follow.")
        with tempfile.TemporaryDirectory() as t:
            d = make_dir(s, t)
            changed = json.loads(json.dumps(s))
            changed["beats"][1]["say"] = "Second, but edited."
            self.assertIn("cumle degismis", V.check(changed, d))
            (d / "b1.wav").unlink()
            self.assertIn("b1.wav yok", V.check(s, d))
            (d / "manifest.json").write_text("{bozuk")
            self.assertIn("okunamadi", V.check(s, d))
            (d / "manifest.json").write_text(json.dumps({"v": 99, "beats": {}}))
            self.assertIn("tanimsiz", V.check(s, d))

    def test_check_rejects_path_tricks_in_beat_ids(self):
        s = {"id": "t001-demo", "beats": [{"id": "../x", "say": "A."}]}
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "t001-demo"
            d.mkdir()
            (d / "manifest.json").write_text(json.dumps({"v": 1, "beats": {"../x": {"sha": V.say_sha("A.")}}}))
            self.assertIn("gecersiz beat", V.check(s, d))

    def test_find_is_quiet_when_there_is_no_clone_and_loud_when_it_is_stale(self):
        s = spec_of("First.", "Follow.")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {"BYTE_CLONE_DIR": t}):
            self.assertEqual(V.find(s, {}, ROOT), (None, "klon ses yok"))
            d = make_dir(s, t)
            self.assertEqual(V.find(s, {}, ROOT), (d, ""))
            stale = json.loads(json.dumps(s))
            stale["beats"][0]["say"] = "Rewritten."
            got, note = V.find(stale, {}, ROOT)
            self.assertIsNone(got)
            self.assertIn("klon ses kullanilamiyor", note)

    def test_switch_in_brand_json_turns_it_off(self):
        s = spec_of("First.", "Follow.")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {"BYTE_CLONE_DIR": t}):
            make_dir(s, t)
            self.assertEqual(V.find(s, {"voice_clone": {"enabled": False}}, ROOT), (None, ""))
            self.assertTrue(V.settings({})["enabled"])
            self.assertFalse(V.settings({})["require"])
            self.assertTrue(V.settings({"voice_clone": {"require": True}})["require"])

    def test_shipped_brand_block_is_valid(self):
        raw = json.loads((ROOT / "brand.json").read_text())["voice_clone"]
        self.assertIsInstance(raw["enabled"], bool)
        self.assertIsInstance(raw["require"], bool)

    def test_tempo_follows_the_pace_shift_and_stays_sane(self):
        self.assertEqual(V.tempo_for(0.0, 1.06), 1.0)
        self.assertLess(V.tempo_for(0.06, 1.06), 1.0)           # daha yavas anlatim -> daha yavas ses
        self.assertGreater(V.tempo_for(-0.06, 1.06), 1.0)
        self.assertEqual(V.tempo_for(5.0, 1.06), V.TEMPO_RANGE[0])
        self.assertEqual(V.tempo_for(-0.9, 1.06), V.TEMPO_RANGE[1])


class WithTheRealScript(unittest.TestCase):
    def test_lines_are_what_the_renderer_will_speak_cta_included(self):
        d = voice_lines.describe(voice_lines.spec_for("p031"))
        ids = [b["id"] for b in d["beats"]]
        self.assertEqual(list(d["manifest"]["beats"]), ids)
        brand = json.loads((ROOT / "brand.json").read_text())
        if brand["cta"].get("spoken") is False:
            self.assertNotIn("cta", ids, "sessiz CTA: Colab'in okuyacagi listede CTA cumlesi olmamali")
        else:
            self.assertEqual(ids[-1], "cta")
            self.assertEqual(d["beats"][-1]["say"], " ".join(brand["cta"]["voice"].split()))

    def test_next_lists_queued_script_ids(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(voice_lines.main(["--next", "3"]), 0)
        ids = buf.getvalue().split()
        self.assertTrue(1 <= len(ids) <= 3)
        for i in ids:
            self.assertTrue(any(f.name.startswith(i) for f in (ROOT / "content/scripts").glob("*.json")))


@unittest.skipUnless(_FF, "ffmpeg yok")
class Prepare(unittest.TestCase):
    def test_trims_silence_and_converts_format(self):
        with tempfile.TemporaryDirectory() as t:
            src, dst = Path(t) / "a.wav", Path(t) / "b.wav"
            write_tone(src, seconds=1.0, sr=24000, lead=0.6, tail=0.7)
            dur = V.prepare(src, dst, 22050)
            with wave.open(str(dst)) as w:
                self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (22050, 1, 2))
            self.assertTrue(0.95 <= dur <= 1.25, dur)           # 2,3 sn degil: bosluklar gitti

    def test_tempo_changes_the_length(self):
        with tempfile.TemporaryDirectory() as t:
            src = Path(t) / "a.wav"
            write_tone(src, seconds=2.0)
            slow = V.prepare(src, Path(t) / "s.wav", 22050, 0.9)
            norm = V.prepare(src, Path(t) / "n.wav", 22050, 1.0)
            self.assertGreater(slow, norm * 1.05)

    def test_silent_or_broken_files_raise(self):
        with tempfile.TemporaryDirectory() as t:
            quiet = Path(t) / "q.wav"
            write_tone(quiet, seconds=1.0, amp=0)
            with self.assertRaises(ValueError):
                V.prepare(quiet, Path(t) / "o.wav", 22050)
            junk = Path(t) / "j.wav"
            junk.write_bytes(b"not audio")
            with self.assertRaises(ValueError):
                V.prepare(junk, Path(t) / "o2.wav", 22050)


@unittest.skipUnless(_FF, "ffmpeg yok")
class SynthUsesTheClone(unittest.TestCase):
    SPEC = spec_of("One two three four.", "Five six.", "Like it, and follow Byte for more.")

    @staticmethod
    def boom(*a, **k):
        raise AssertionError("klon varken Piper cagrildi")

    def run_synth(self, clone, **kw):
        with tempfile.TemporaryDirectory() as out, mock.patch.object(synth, "_piper", kw.pop("piper", self.boom)):
            tl = synth.synthesize(self.SPEC, Path(out), Path("unused.onnx"), clone, **kw)
            self.assertTrue((Path(out) / "voice.wav").is_file())
            return tl

    def test_clone_replaces_piper_and_timeline_matches_the_files(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_dir(self.SPEC, t, seconds=1.0, lead=0.4, tail=0.4)
            tl = self.run_synth(d)
        self.assertEqual(tl["voice"], "clone")
        self.assertEqual([b["id"] for b in tl["beats"]], ["b1", "b2", "cta"])
        for b in tl["beats"]:
            self.assertTrue(0.9 <= b["end"] - b["start"] <= 1.2)
            self.assertTrue(all(w["e"] <= b["end"] + 1e-6 for w in b["words"]))
        self.assertGreater(tl["duration"], tl["beats"][-1]["end"])

    def test_broken_clone_falls_back_to_piper_whole_video(self):
        def fake_piper(text, path, voice, i=0, shift=0.0):
            write_tone(path, seconds=0.5, sr=synth.SR)
            return 0.5
        with tempfile.TemporaryDirectory() as t:
            d = make_dir(self.SPEC, t)
            (d / "b2.wav").write_bytes(b"corrupt")
            tl = self.run_synth(d, piper=fake_piper)
        self.assertEqual(tl["voice"], "piper")

    def test_required_clone_never_falls_back(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_dir(self.SPEC, t)
            (d / "b2.wav").write_bytes(b"corrupt")
            with self.assertRaises(SystemExit):
                self.run_synth(d, clone_required=True)

    def test_no_clone_is_the_old_behaviour(self):
        def fake_piper(text, path, voice, i=0, shift=0.0):
            write_tone(path, seconds=0.5, sr=synth.SR)
            return 0.5
        tl = self.run_synth(None, piper=fake_piper)
        self.assertEqual(tl["voice"], "piper")


class BuildStopsWhenTheCloneIsRequired(unittest.TestCase):
    def test_require_true_without_a_clone_exits_before_any_work(self):
        from worker import build
        brand = json.loads((ROOT / "brand.json").read_text())
        brand["voice_clone"] = {"enabled": True, "require": True}
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {"BYTE_CLONE_DIR": t}), \
                mock.patch.object(build, "load_brand", return_value=brand), \
                mock.patch.object(sys, "argv", ["build", str(next((ROOT / "content/scripts").glob("p031*.json"))),
                                                "--out", str(Path(t) / "o")]):
            with self.assertRaises(SystemExit) as cm:
                build.main()
        self.assertIn("klon ses zorunlu", str(cm.exception))


# ── R2 ──────────────────────────────────────────────────────────────────────────────────
class NotFound(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    def __init__(self):
        self.objects, self.log = {}, []

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.objects[(bucket, key)] = Path(path).read_bytes()
        self.log.append(key)

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[(Bucket, Key)] = Body
        self.log.append(Key)

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise NotFound()
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def download_file(self, bucket, key, dest):
        Path(dest).write_bytes(self.objects[(bucket, key)])

    def list_objects_v2(self, Bucket, Prefix, Delimiter, **kw):
        seen = sorted({k.split("/")[1] for (b, k) in self.objects if b == Bucket and k.startswith(Prefix)})
        return {"CommonPrefixes": [{"Prefix": f"{Prefix}{s}/"} for s in seen], "IsTruncated": False}


class R2RoundTrip(unittest.TestCase):
    def test_push_uploads_wavs_first_manifest_last_and_pull_restores_it(self):
        s = spec_of("First.", "Second.", "Follow.")
        c = FakeS3()
        with tempfile.TemporaryDirectory() as t:
            make_dir(s, t)
            ids = r2_voice.push(c, "bkt", Path(t))
            self.assertEqual(ids, ["t001-demo"])
            self.assertEqual(c.log[-1], "voice/t001-demo/manifest.json")
            self.assertEqual(r2_voice.listing(c, "bkt"), ["t001-demo"])
            dest = Path(t) / "indirilen"
            man = r2_voice.pull(c, "bkt", "t001-demo", dest)
            self.assertEqual(list(man["beats"]), ["b1", "b2", "cta"])
            self.assertEqual(V.check(s, dest), "")                      # indirilen dizin render icin gecerli

    def test_pull_without_a_voice_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(r2_voice.pull(FakeS3(), "bkt", "t009-none", Path(t) / "x"))
            self.assertFalse((Path(t) / "x").exists())

    def test_hostile_ids_are_refused(self):
        with self.assertRaises(SystemExit):
            r2_voice.pull(FakeS3(), "bkt", "../etc", Path("/tmp/never"))
        c = FakeS3()
        c.objects[("bkt", "voice/t001-demo/manifest.json")] = json.dumps(
            {"v": 1, "beats": {"../../evil": {"sha": "x"}}}).encode()
        with tempfile.TemporaryDirectory() as t, self.assertRaises(SystemExit):
            r2_voice.pull(c, "bkt", "t001-demo", Path(t) / "d")

    def test_push_refuses_a_manifest_that_lists_a_missing_file(self):
        s = spec_of("First.", "Follow.")
        with tempfile.TemporaryDirectory() as t:
            d = make_dir(s, t)
            (d / "b1.wav").unlink()
            with self.assertRaises(SystemExit):
                r2_voice.push(FakeS3(), "bkt", Path(t))

    def test_size_mismatch_after_upload_fails_loudly(self):
        class Short(FakeS3):
            def head_object(self, Bucket, Key):
                return {"ContentLength": 1}
        s = spec_of("First.", "Follow.")
        with tempfile.TemporaryDirectory() as t:
            make_dir(s, t)
            with self.assertRaises(SystemExit):
                r2_voice.push(Short(), "bkt", Path(t))

    def test_pull_cli_is_silent_when_r2_is_not_configured(self):
        env = {k: "" for k in r2_voice.NEED}
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buf):
            self.assertEqual(r2_voice.main(["pull", "t001-demo", "/tmp/nowhere"]), 0)
        self.assertIn("R2 ayari yok", buf.getvalue())

    def test_missing_voice_prints_a_github_warning_in_actions(self):
        env = {"R2_ENDPOINT": "https://x.example", "R2_BUCKET": "b", "R2_ACCESS_KEY_ID": "k",
               "R2_SECRET_ACCESS_KEY": "s", "GITHUB_ACTIONS": "true"}
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(r2_voice, "client_from_env",
                                                                  return_value=(FakeS3(), "b")), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(r2_voice.main(["pull", "t001-demo", "/tmp/nowhere"]), 0)
        self.assertIn("::warning title=Klon ses yok::", buf.getvalue())


class ColabNotebook(unittest.TestCase):
    NB = ROOT / "colab" / "byte_colab_ses_uret.ipynb"

    def test_is_valid_and_every_code_cell_compiles(self):
        import ast
        nb = json.loads(self.NB.read_text())
        code = [c for c in nb["cells"] if c["cell_type"] == "code"]
        self.assertGreaterEqual(len(code), 6)
        for c in code:
            src = "\n".join("pass" if l.lstrip().startswith("!") else l for l in "".join(c["source"]).splitlines())
            ast.parse(src)

    def test_uses_the_names_the_tools_expect_and_holds_no_secret(self):
        text = self.NB.read_text()
        for needed in (*r2_voice.NEED, "tools/voice_lines.py", "tools/r2_voice.py", "userdata.get"):
            self.assertIn(needed, text)
        self.assertNotRegex(text, r"(?i)(secret_?access_?key|token)\s*=\s*[\"'][A-Za-z0-9/+_-]{16,}")
        self.assertIn("unassign", text)                                   # GPU acik kalmasin


class Workflows(unittest.TestCase):
    def test_daily_and_publish_pull_the_voice_before_the_render_and_share_one_directory(self):
        for name, render in (("daily.yml", "worker.build"), ("publish.yml", "worker.build")):
            txt = (ROOT / ".github/workflows" / name).read_text()
            self.assertEqual(txt, (ROOT / "ci" / name).read_text())
            self.assertLess(txt.index("klon ses indir"), txt.index(render + ' "'))
            self.assertEqual(txt.count("BYTE_CLONE_DIR: out/_clone"), 2)       # indirme + render ayni dizin


if __name__ == "__main__":
    unittest.main()
