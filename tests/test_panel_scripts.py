"""
tools/panel_scripts.py: panelden gelen senaryo islemleri (ekle / one al / sil). AG YOK, R2 sahte.

Her test KENDI gecici depo kopyasinda calisir; gercek content/ dosyalarina dokunmaz.
"""
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import panel_scripts as ps                                             # noqa: E402

from publish import manifest as M                                      # noqa: E402
from tests.fixtures import SCENES, story_form                          # noqa: E402

BRAND = M.load_brand(ROOT)
NOW = datetime(2026, 11, 13, 20, 0, 0, tzinfo=timezone.utc)
RID = "a" * 32
RID2 = "b" * 32


class FakeR2:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.fail_put = False

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        if self.fail_put:
            raise RuntimeError("r2 down")
        self.objects[Key] = bytes(Body)

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


def request(form, rid=RID, **over):
    rec = {"v": 1, "request_id": rid, "action": "new", "at": "2026-11-13T19:59:00Z", "form": form}
    rec.update(over)
    return json.dumps(rec).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)
        (self.root / "content" / "scripts").mkdir(parents=True)
        for name in ("p038-nvidia-dennys-booth", "p047-hugging-face-teen-chatbot", "p031-genome-three-billion"):
            shutil.copy(ROOT / "content" / "scripts" / f"{name}.json", self.root / "content" / "scripts")
        self.write("order.json", ["p038-nvidia-dennys-booth", "p047-hugging-face-teen-chatbot"])
        self.write("built.json", ["p031-genome-three-billion"])
        self.write("published.json", [])
        self.write("experiments.json", {"e1": {"arms": {"short": ["p047-hugging-face-teen-chatbot"], "standard": []}}})
        self.r2 = FakeR2()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(ps, "RESULT_FILE", self.root / "out" / "result.json").start()

    def write(self, name, data):
        (self.root / "content" / name).write_text(json.dumps(data))

    def read(self, name):
        return json.loads((self.root / "content" / name).read_text())

    def env(self, action="ingest", sid="", rid=RID, **extra):
        return {"ACTION": action, "SCRIPT_ID": sid, "REQUEST_ID": rid, **extra}

    def apply(self, **kw):
        return ps.apply(self.env(**kw), self.r2, "b", root=self.root, now=NOW, scene_names=SCENES, brand=BRAND)

    def files(self):
        return sorted(p.stem for p in (self.root / "content" / "scripts").glob("*.json"))


class Ingest(Base):
    def test_a_valid_form_becomes_the_next_numbered_script_at_the_end_of_the_queue(self):
        self.r2.objects[f"scripts-in/{RID}.json"] = request(story_form())
        res = self.apply()
        self.assertEqual((res["status"], res["changed"]), ("ok", True), res)
        self.assertEqual(res["script_id"], "p048-youtube-started-as-a-video-dating-site")
        spec = json.loads((self.root / "content" / "scripts" / f"{res['script_id']}.json").read_text())
        self.assertEqual(spec["authored"], {"by": "panel", "date": "2026-11-13"})
        self.assertEqual(self.read("order.json")[-1], res["script_id"])
        self.assertEqual(len(self.read("order.json")), 3)

    def test_the_number_skips_everything_already_used_even_if_the_file_is_gone(self):
        self.write("built.json", ["p031-genome-three-billion", "p090-built-and-removed"])
        self.r2.objects[f"scripts-in/{RID}.json"] = request(story_form())
        self.assertTrue(self.apply()["script_id"].startswith("p091-"))

    def test_an_invalid_form_adds_nothing_and_says_why(self):
        bad = story_form()
        bad["beats"][5]["cap"] = "Dec 2005: 37M views a day"       # hicbir olayda yok
        self.r2.objects[f"scripts-in/{RID}.json"] = request(bad)
        res = self.apply()
        self.assertEqual((res["status"], res["changed"]), ("rejected", False))
        self.assertTrue(any("37" in p for p in res["problems"]), res["problems"])
        self.assertEqual(self.files(), ["p031-genome-three-billion", "p038-nvidia-dennys-booth",
                                        "p047-hugging-face-teen-chatbot"])
        self.assertEqual(len(self.read("order.json")), 2)

    def test_the_gate_still_decides_what_the_compiler_lets_through(self):
        bad = story_form()
        bad["beats"][1]["say"] = "It cost 5 dollars."
        self.r2.objects[f"scripts-in/{RID}.json"] = request(bad)
        res = self.apply()
        self.assertEqual(res["status"], "rejected")
        self.assertTrue(any("rakam" in p for p in res["problems"]), res["problems"])
        self.assertEqual(len(self.files()), 3)

    def test_the_same_title_twice_is_refused(self):
        form = story_form()
        form["title"] = "YouTube started as a video dating site"
        self.r2.objects[f"scripts-in/{RID}.json"] = request(form)
        self.assertEqual(self.apply()["status"], "ok")
        self.r2.objects[f"scripts-in/{RID2}.json"] = request(form, rid=RID2)
        res = ps.apply(self.env(rid=RID2), self.r2, "b", root=self.root, now=NOW, scene_names=SCENES, brand=BRAND)
        self.assertEqual(res["status"], "rejected")
        self.assertTrue(any("ayni baslik" in p for p in res["problems"]), res["problems"])

    def test_two_forms_in_a_row_get_two_numbers(self):
        for rid, title in ((RID, "First story title here"), (RID2, "Second story title here")):
            form = story_form()
            form["title"] = title
            self.r2.objects[f"scripts-in/{rid}.json"] = request(form, rid=rid)
            res = ps.apply(self.env(rid=rid), self.r2, "b", root=self.root, now=NOW, scene_names=SCENES, brand=BRAND)
            self.assertEqual(res["status"], "ok", res)
        ids = self.read("order.json")[-2:]
        self.assertTrue(ids[0].startswith("p048-") and ids[1].startswith("p049-"), ids)

    def test_bad_requests_are_rejected_not_crashed(self):
        cases = [b"not json", b"[]", request(story_form(), v=2), request(story_form(), action="delete"),
                 request("form-as-string"), b"x" * (ps.MAX_IN + 5)]
        for raw in cases:
            self.r2.objects[f"scripts-in/{RID}.json"] = raw
            res = self.apply()
            self.assertIn(res["status"], ("rejected", "error"))
            self.assertFalse(res["changed"])
        res = self.apply(rid=RID2)                                      # kayit hic yok
        self.assertEqual(res["status"], "rejected")
        self.assertEqual(len(self.files()), 3)

    def test_inputs_are_validated(self):
        for env in (self.env(action="rm"), self.env(rid="short"), self.env(rid="A" * 32),
                    self.env(action="remove", sid="../etc"), self.env(action="remove", sid=""),
                    self.env(action="move_first", sid="p041-x/../y")):
            res = ps.apply(env, self.r2, "b", root=self.root, now=NOW, scene_names=SCENES, brand=BRAND)
            self.assertEqual(res["status"], "rejected", env)


class MoveAndRemove(Base):
    def test_move_first_puts_the_story_at_the_front(self):
        res = self.apply(action="move_first", sid="p047-hugging-face-teen-chatbot")
        self.assertEqual((res["status"], res["changed"]), ("ok", True))
        self.assertEqual(self.read("order.json"), ["p047-hugging-face-teen-chatbot", "p038-nvidia-dennys-booth"])
        again = self.apply(action="move_first", sid="p047-hugging-face-teen-chatbot")
        self.assertEqual((again["status"], again["changed"]), ("ok", False))

    def test_a_script_that_is_not_in_the_order_list_can_still_be_moved_first(self):
        shutil.copy(ROOT / "content" / "scripts" / "p045-deepmind-atari.json", self.root / "content" / "scripts")
        self.apply(action="move_first", sid="p045-deepmind-atari")
        self.assertEqual(self.read("order.json")[0], "p045-deepmind-atari")

    def test_built_or_missing_scripts_are_refused(self):
        for sid in ("p031-genome-three-billion", "p099-not-there"):
            for action in ("move_first", "remove"):
                res = self.apply(action=action, sid=sid)
                self.assertEqual(res["status"], "rejected", (action, sid))
                self.assertFalse(res["changed"])
        self.assertIn("p031-genome-three-billion", self.files())

    def test_remove_deletes_the_file_and_the_order_entry(self):
        res = self.apply(action="remove", sid="p038-nvidia-dennys-booth")
        self.assertEqual((res["status"], res["changed"]), ("ok", True))
        self.assertNotIn("p038-nvidia-dennys-booth", self.files())
        self.assertEqual(self.read("order.json"), ["p047-hugging-face-teen-chatbot"])

    def test_a_script_inside_an_experiment_arm_cannot_be_removed(self):
        res = self.apply(action="remove", sid="p047-hugging-face-teen-chatbot")
        self.assertEqual(res["status"], "rejected")
        self.assertIn("A/B", res["message"])
        self.assertIn("p047-hugging-face-teen-chatbot", self.files())

    def test_a_published_script_cannot_be_removed(self):
        self.write("published.json", [{"id": "p038-nvidia-dennys-booth"}])
        self.assertEqual(self.apply(action="remove", sid="p038-nvidia-dennys-booth")["status"], "rejected")


class Report(Base):
    def test_ok_is_reported_only_when_the_push_succeeded(self):
        self.r2.objects[f"scripts-in/{RID}.json"] = request(story_form())
        self.apply()
        out = ps.report(self.env(PUSH_OK="true"), self.r2, "b", now=NOW)
        self.assertEqual(out["status"], "ok")
        got = json.loads(self.r2.objects[f"scripts-out/{RID}.json"])
        self.assertEqual((got["v"], got["request_id"], got["status"]), (1, RID, "ok"))
        self.assertNotIn(f"scripts-in/{RID}.json", self.r2.objects)        # form kaydi temizlenir

    def test_a_change_that_could_not_be_pushed_is_an_error(self):
        self.r2.objects[f"scripts-in/{RID}.json"] = request(story_form())
        self.apply()
        out = ps.report(self.env(PUSH_OK="false"), self.r2, "b", now=NOW)
        self.assertEqual(out["status"], "error")
        self.assertIn("push", out["message"])

    def test_a_rejection_needs_no_push(self):
        self.r2.objects[f"scripts-in/{RID}.json"] = request({"title": ""})
        self.apply()
        out = ps.report(self.env(PUSH_OK="false"), self.r2, "b", now=NOW)
        self.assertEqual(out["status"], "rejected")
        self.assertTrue(out["problems"])

    def test_if_apply_never_ran_the_panel_still_gets_an_answer(self):
        out = ps.report(self.env(), self.r2, "b", now=NOW, result_file=self.root / "nope.json")
        self.assertEqual(out["status"], "error")
        self.assertIn(f"scripts-out/{RID}.json", self.r2.objects)

    def test_the_payload_is_bounded_and_clean(self):
        ps.RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
        ps.RESULT_FILE.write_text(json.dumps({"status": "rejected", "problems": ["x\x00y" * 400] * 50,
                                              "message": "m" * 999, "action": "ingest"}))
        out = ps.report(self.env(), self.r2, "b", now=NOW)
        self.assertLessEqual(len(out["problems"]), ps.MAX_PROBLEMS)
        self.assertTrue(all(len(p) <= ps.MAX_LINE and "\x00" not in p for p in out["problems"]))
        self.assertLessEqual(len(out["message"]), ps.MAX_LINE)

    def test_a_bad_request_id_stops_the_report(self):
        with self.assertRaises(SystemExit):
            ps.report(self.env(rid="nope"), self.r2, "b", now=NOW)


if __name__ == "__main__":
    unittest.main()
