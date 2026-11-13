"""
Sozlesme testi: CI'nin yazdigi kayitlari panel GERCEKTEN okuyabiliyor mu?

tools/r2_push.py ve tools/panel_publish.py (depo kokunde) panelin ayni sekilde
kullandigi MemoryStorage uzerinde calistirilir. Iki taraf birbirinden habersiz
degisirse bu test kirilir. tools/ yoksa (ornegin yalniz panel kopyalandiysa) atlanir.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

from tests.helpers import make_service, pubs

TOOLS = Path(__file__).resolve().parents[2] / "tools"
HAVE_TOOLS = (TOOLS / "r2_push.py").exists() and (TOOLS / "panel_publish.py").exists()
if HAVE_TOOLS:
    sys.path.insert(0, str(TOOLS))
    import panel_publish as pp
    import r2_push
HAVE_SCRIPT_TOOLS = (TOOLS / "panel_scripts.py").exists() and (TOOLS.parent / "editorial" / "formscript.py").exists()
if HAVE_SCRIPT_TOOLS:
    import panel_scripts as ps
    from publish import manifest as M

SID = "p001-tay-chatbot-under-a-day"
NOW = datetime(2026, 11, 8, 15, 0, 0, tzinfo=timezone.utc)


class NotFound(Exception):
    """botocore.exceptions.ClientError (404) gibi."""

    def __init__(self):
        self.response = {"Error": {"Code": "404"}}


class S3OverMemory:
    """boto3 istemcisi gibi davranir, ama panelin MemoryStorage'ina yazar."""

    def __init__(self, st):
        self.st = st

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.st.put_bytes(key, Path(path).read_bytes())

    def head_object(self, Bucket, Key):
        if Key not in self.st.objects:
            raise NotFound()
        return {"ContentLength": len(self.st.objects[Key])}

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.st.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.st.put_bytes(Key, Body)

    def delete_object(self, Bucket, Key):
        self.st.delete(Key)

    def download_file(self, bucket, key, dest):
        Path(dest).write_bytes(self.st.objects[key])

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return self.st.presign_get(Params["Key"], ExpiresIn)


@unittest.skipUnless(HAVE_TOOLS, "tools/ yok")
class Contract(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)
        self.svc, self.st, self.gh, self.clock = make_service()
        self.client = S3OverMemory(self.st)
        out = self.root / "out" / SID
        out.mkdir(parents=True)
        (out / f"{SID}.mp4").write_bytes(b"V" * 4096)
        (out / "captions.md").write_text("# c")
        (out / "manifest.json").write_text(json.dumps(
            {"id": SID, "series": "G", "title": "Bir video", "duration": 37.2,
             "video": f"{SID}.mp4", "captions": {"youtube": "y", "instagram": "i", "tiktok": "t"}}))
        self.out = out

    def test_what_ci_pushes_the_panel_ingests(self):
        r2_push.push(self.client, "b", self.out, "https://github.com/o/r/actions/runs/5", now=NOW)
        self.assertEqual(self.svc.ingest_inbox(), 1)
        v = self.svc.video(SID)
        self.assertEqual((v["title"], v["size_bytes"], v["approval"]), ("Bir video", 4096, "pending"))
        self.assertEqual(v["run_url"], "https://github.com/o/r/actions/runs/5")
        self.assertFalse(self.st.exists(f"inbox/{SID}.json"))
        self.assertFalse(any(k.startswith('inbox-rejected/') for k in self.st.objects))

    def test_the_whole_loop_push_approve_dispatch_publish_result(self):
        r2_push.push(self.client, "b", self.out, now=NOW)
        self.svc.ingest_inbox()
        self.svc.approve(SID, "t")
        self.clock.set(2026, 11, 8, 23, 0)                    # slot gecti
        self.assertEqual(self.svc.dispatch_due(), 1)
        sent = self.gh.calls[0]                                # panelin GitHub'a gonderdigi
        env = {"SCRIPT_ID": sent["script_id"], "PLATFORM": sent["platform"],
               "PRIVACY": sent["privacy"], "REQUEST_ID": sent["request_id"],
               "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "9"}

        # yayin runner'i temiz bir checkout'ta calisir: out/ yok, yalniz R2'den iner
        runner_root = self.root / "runner"
        runner_root.mkdir()

        def uploader(cmd, **kw):
            man = runner_root / "out" / SID / "manifest.json"
            m = json.loads(man.read_text())
            m["youtube_id"] = "uHYCPlQttiE"
            man.write_text(json.dumps(m))
            return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        self.assertEqual(pp.run(env, self.client, "b", root=runner_root, runner=uploader, now=NOW), 0)
        self.assertEqual(self.svc.ingest_results(), 1)
        p = pubs(self.svc, SID)["youtube"]
        self.assertEqual((p["status"], p["remote_id"]), ("published", "uHYCPlQttiE"))
        self.assertEqual(p["remote_url"], "https://youtu.be/uHYCPlQttiE")

    @unittest.skipIf(yaml is None, "pyyaml yok")
    def test_the_workflow_takes_exactly_the_inputs_the_panel_sends(self):
        wf = TOOLS.parent / "ci" / "panel-publish.yml"
        d = yaml.safe_load(wf.read_text())
        declared = set((d.get(True) or d["on"])["workflow_dispatch"]["inputs"])
        r2_push.push(self.client, "b", self.out, now=NOW)
        self.svc.ingest_inbox()
        self.svc.approve(SID, "t")
        self.clock.set(2026, 11, 8, 23, 0)
        self.svc.dispatch_due()
        self.assertEqual(set(self.gh.calls[0]), declared)
        self.assertEqual(wf.name, self.svc.cfg.gh_workflow)             # panelin cagirdigi dosya adi
        self.assertIn(self.gh.calls[0]["privacy"], ("public", "unlisted", "private"))

    def test_a_failed_publish_arrives_as_failed_with_the_reason(self):
        r2_push.push(self.client, "b", self.out, now=NOW)
        self.svc.ingest_inbox()
        self.svc.approve(SID, "t")
        self.clock.set(2026, 11, 8, 23, 0)
        self.svc.dispatch_due()
        sent = self.gh.calls[0]
        env = {"SCRIPT_ID": SID, "PLATFORM": "youtube", "PRIVACY": "public",
               "REQUEST_ID": sent["request_id"]}
        runner_root = self.root / "runner2"
        runner_root.mkdir()

        def bad(cmd, **kw):
            return type("P", (), {"returncode": 1, "stdout": "", "stderr": "quotaExceeded"})()
        self.assertEqual(pp.run(env, self.client, "b", root=runner_root, runner=bad, now=NOW), 1)
        self.assertEqual(self.svc.ingest_results(), 1)
        p = pubs(self.svc, SID)["youtube"]
        self.assertEqual(p["status"], "failed")
        self.assertIn("quotaExceeded", p["error"])


if __name__ == "__main__":
    unittest.main()


# ── hikayeler: panel formu -> depodaki kapi -> panele sonuc ──────────────────
# Panel imajinda editorial/ kodu yok; kapi depoda. Bu testler iki tarafin ayni dili konustugunu kilitler.
SCENE_NAMES = ("title", "contrast", "table", "bars", "counter", "split", "timeline", "byte_says", "close",
               "steps", "flow", "equation", "ring", "dots", "chat", "terminal", "tokens", "probs", "layers",
               "checklist", "headline", "scale", "cycle", "bits", "guess")
REPO = TOOLS.parent
KEEP = ("p038-nvidia-dennys-booth", "p045-deepmind-atari", "p047-hugging-face-teen-chatbot")


@unittest.skipUnless(HAVE_SCRIPT_TOOLS, "tools/ ya da editorial/ yok")
class ScriptsContract(unittest.TestCase):
    def setUp(self):
        import shutil
        from unittest import mock
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)
        (self.root / "content" / "scripts").mkdir(parents=True)
        self.keep = [n for n in KEEP if (REPO / "content" / "scripts" / f"{n}.json").exists()]
        for n in self.keep:
            shutil.copy(REPO / "content" / "scripts" / f"{n}.json", self.root / "content" / "scripts")
        self.write("order.json", self.keep)
        for name in ("built", "published"):
            self.write(f"{name}.json", [])
        self.write("experiments.json", {})
        self.svc, self.st, self.gh, self.clock = make_service()
        self.gh.queue = list(self.keep)
        self.client = S3OverMemory(self.st)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(ps, "RESULT_FILE", self.root / "out" / "result.json").start()

    def write(self, name, data):
        (self.root / "content" / name).write_text(json.dumps(data))

    def order(self):
        return json.loads((self.root / "content" / "order.json").read_text())

    def run_workflow(self, call):
        """GitHub'a gonderilen girdilerle depo tarafini calistirir (apply -> push varsay -> report)."""
        env = {"ACTION": call["action"], "SCRIPT_ID": call["script_id"], "REQUEST_ID": call["request_id"]}
        brand = M.load_brand(REPO)
        res = ps.apply(env, self.client, "b", root=self.root, now=NOW, scene_names=SCENE_NAMES, brand=brand)
        ps.report({**env, "PUSH_OK": "true"}, self.client, "b", now=NOW)
        return res

    def good_form(self):
        from tests.test_scripts import good_form
        return good_form()

    def test_a_panel_form_becomes_a_script_and_the_panel_hears_back(self):
        rid = self.svc.submit_script(self.good_form(), "t")
        res = self.run_workflow(self.gh.calls[0])
        self.assertEqual((res["status"], res["problems"]), ("ok", []))
        self.assertEqual(self.svc.ingest_script_results(), 1)
        (r,) = self.svc.script_requests()
        self.assertEqual((r["request_id"], r["status"]), (rid, "ok"))
        self.assertRegex(r["script_id"], r"^p\d{3}-[a-z0-9-]+$")
        self.assertEqual(self.order()[-1], r["script_id"])               # kuyrugun sonuna
        self.assertTrue((self.root / "content" / "scripts" / f"{r['script_id']}.json").exists())
        self.assertEqual(self.st.list_keys("scripts-in/", 10), [])        # istek kaydi temizlendi
        self.assertEqual(self.st.list_keys("scripts-out/", 10), [])
        self.assertEqual(self.st.list_keys("scripts-orphan/", 10) + self.st.list_keys("scripts-rejected/", 10), [])

    def test_a_form_the_gate_refuses_comes_back_with_reasons_and_the_form(self):
        form = self.good_form()
        form["beats"][8].update(cap="$7.77 billion deal", kw="$7.77 billion")        # kaynakta yok
        self.assertEqual(__import__("bytepanel.scripts", fromlist=["x"]).precheck(form), [])   # panel gecirir
        self.svc.submit_script(form, "t")
        res = self.run_workflow(self.gh.calls[0])
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(self.order(), self.keep)                                       # hicbir sey yazilmadi
        self.svc.ingest_script_results()
        (r,) = self.svc.script_requests()
        self.assertEqual(r["status"], "rejected")
        self.assertTrue(r["problems"])
        self.assertTrue(r["can_fix"])
        self.assertIn("7.77", r["problems"][0] + " ".join(r["problems"]))

    def test_move_first_and_remove_round_trip(self):
        if len(self.keep) < 3:
            self.skipTest("depoda yeterli senaryo yok")
        a, b, c = self.keep
        self.svc.queue_action("move_first", c, "t")
        self.assertEqual(self.run_workflow(self.gh.calls[-1])["status"], "ok")
        self.assertEqual(self.order(), [c, a, b])
        self.svc.ingest_script_results()
        self.svc.queue_action("remove", a, "t")
        self.assertEqual(self.run_workflow(self.gh.calls[-1])["status"], "ok")
        self.assertEqual(self.order(), [c, b])
        self.assertFalse((self.root / "content" / "scripts" / f"{a}.json").exists())
        self.assertEqual(self.svc.ingest_script_results(), 1)
        self.assertEqual([r["status"] for r in self.svc.script_requests()], ["ok", "ok"])

    def test_the_workflow_takes_exactly_the_inputs_the_panel_sends(self):
        wf = REPO / "ci" / "panel-scripts.yml"
        d = yaml.safe_load(wf.read_text())
        inputs = (d.get(True) or d["on"])["workflow_dispatch"]["inputs"]
        self.svc.submit_script(self.good_form(), "t")
        self.svc.queue_action("remove", self.keep[-1], "t")
        for call in self.gh.calls:
            self.assertEqual(set(call), set(inputs))
        self.assertEqual(wf.name, self.svc.cfg.gh_scripts_workflow)
        self.assertEqual(tuple(inputs["action"]["options"]), ps.ACTIONS)

    def test_both_sides_agree_on_the_wire_format(self):
        from bytepanel import scripts as pscripts
        from bytepanel import service
        self.assertEqual((ps.IN_PREFIX, ps.OUT_PREFIX), (pscripts.IN_PREFIX, pscripts.OUT_PREFIX))
        self.assertEqual(ps.ACTIONS, pscripts.ACTIONS)
        self.assertEqual(ps.SID.pattern, service.SCRIPT_ID.pattern)
        self.assertEqual(ps.MAX_IN, pscripts.MAX_RECORD)
        self.assertEqual(ps.REQ.pattern, service.REQ_ID.pattern)
        self.assertFalse(ps.IN_PREFIX.startswith(service.INBOX) or ps.OUT_PREFIX.startswith(service.INBOX))
        self.assertFalse(ps.OUT_PREFIX.startswith(service.RESULTS))
