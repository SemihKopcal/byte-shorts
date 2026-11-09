"""
daily.yml ve pick_script: kuyruk bossa Gemini'ye DUSMEYEN, hizli duran akis.

Kullanici karari (8 Kasim): "daily hic Gemini denemesin". Kuyruk bosken eski
akis 2-7 dakika yanip her seferinde kirmizi bitiyordu. AG YOK.

    python -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:                       # lokal makinede olmayabilir
    yaml = None

ROOT = Path(__file__).resolve().parent.parent


def load_pick():
    spec = importlib.util.spec_from_file_location(
        "pick_script", ROOT / "tools" / "pick_script.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PickScript(unittest.TestCase):
    def run_pick(self, scripts, built=(), argv=()):
        pick = load_pick()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "content" / "scripts").mkdir(parents=True)
            for name, sid in scripts:
                (root / "content" / "scripts" / name).write_text(
                    json.dumps({"id": sid}))
            (root / "content" / "built.json").write_text(json.dumps(list(built)))
            pick.ROOT = root
            pick.SCRIPTS = root / "content" / "scripts"
            pick.PUBLISHED = root / "content" / "published.json"
            pick.BUILT = root / "content" / "built.json"
            buf, old = io.StringIO(), sys.argv
            sys.argv = ["pick_script.py", *argv]
            try:
                with contextlib.redirect_stdout(buf):
                    pick.main()
            finally:
                sys.argv = old
        return dict(line.split("=", 1) for line in buf.getvalue().splitlines())

    SCRIPTS = [("p001-a.json", "p001-a"), ("p002-b.json", "p002-b"),
               ("p003-c.json", "p003-c")]

    def test_picks_the_first_unbuilt_in_file_order_and_counts_what_is_left(self):
        out = self.run_pick(self.SCRIPTS, built=["p001-a"])
        self.assertEqual(out["path"], "content/scripts/p002-b.json")
        self.assertEqual(out["left"], "2")          # bu video dahil

    def test_empty_queue_prints_an_empty_path_and_zero_left(self):
        out = self.run_pick(self.SCRIPTS, built=["p001-a", "p002-b", "p003-c"])
        self.assertEqual(out, {"path": "", "left": "0"})

    def run_with_order(self, order, built=(), argv=(), raw=None):
        """run_pick'in order.json'lu hali (order.json scripts klasorunun yaninda)."""
        pick = load_pick()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "content" / "scripts").mkdir(parents=True)
            for name, sid in self.SCRIPTS:
                (root / "content" / "scripts" / name).write_text(
                    json.dumps({"id": sid}))
            (root / "content" / "built.json").write_text(json.dumps(list(built)))
            if raw is not None:
                (root / "content" / "order.json").write_text(raw)
            elif order is not None:
                (root / "content" / "order.json").write_text(json.dumps(order))
            pick.ROOT = root
            pick.SCRIPTS = root / "content" / "scripts"
            pick.PUBLISHED = root / "content" / "published.json"
            pick.BUILT = root / "content" / "built.json"
            buf, old = io.StringIO(), sys.argv
            sys.argv = ["pick_script.py", *argv]
            try:
                with contextlib.redirect_stdout(buf):
                    pick.main()
            finally:
                sys.argv = old
        return dict(line.split("=", 1) for line in buf.getvalue().splitlines())

    def test_order_json_puts_listed_scripts_first_in_list_order(self):
        out = self.run_with_order(["p003-c", "p002-b"])
        self.assertEqual(out["path"], "content/scripts/p003-c.json")
        self.assertEqual(out["left"], "3")

    def test_order_json_skips_built_unknown_and_duplicate_ids(self):
        out = self.run_with_order(["nope", "p003-c", "p003-c", "p002-b"],
                                  built=["p003-c"])
        self.assertEqual(out["path"], "content/scripts/p002-b.json")
        self.assertEqual(out["left"], "2")

    def test_unlisted_scripts_follow_in_file_order(self):
        out = self.run_with_order(["p003-c"], built=["p003-c"])
        self.assertEqual(out["path"], "content/scripts/p001-a.json")

    def test_a_broken_or_wrong_shape_order_file_changes_nothing(self):
        for raw in ("{not json", '{"a": 1}', '[1, null, {"x": 2}]', "[]"):
            out = self.run_with_order(None, raw=raw)
            self.assertEqual(out["path"], "content/scripts/p001-a.json", raw)
            self.assertEqual(out["left"], "3", raw)

    def test_newest_still_takes_the_last_of_the_queue(self):
        out = self.run_with_order(["p002-b"], argv=["--newest"])
        self.assertEqual(out["path"], "content/scripts/p003-c.json")

    def test_a_named_script_reports_no_queue_length(self):
        out = self.run_pick(self.SCRIPTS, argv=["p003-c.json"])
        self.assertEqual(out["path"], "content/scripts/p003-c.json")
        self.assertNotIn("left", out)


@unittest.skipIf(yaml is None, "pyyaml yok")
class Daily(unittest.TestCase):
    def setUp(self):
        self.y = yaml.safe_load((ROOT / "ci" / "daily.yml").read_text())
        self.steps = self.y["jobs"]["build"]["steps"]
        self.names = [s.get("name") or s.get("uses") for s in self.steps]

    def step(self, name):
        return self.steps[self.names.index(name)]

    def test_gemini_is_not_wired_into_daily(self):
        # yaml ayristirmasi yorumlari atiyor: yalniz gercek adimlar ve girdiler
        text = json.dumps(self.y)
        self.assertNotIn("GEMINI", text)
        self.assertNotIn("python -m editorial", text)
        self.assertNotIn("topic", self.y[True]["workflow_dispatch"]["inputs"])
        self.assertNotIn("konu uret", self.names)

    def test_the_queue_is_checked_before_anything_is_installed(self):
        stop = self.names.index("kuyruk bos")
        self.assertLess(self.names.index("sirada senaryo var mi"), stop)
        for later in ("arac cache", "ffmpeg + fontlar", "ses modeli cache"):
            self.assertGreater(self.names.index(later), stop, later)
        for i, n in enumerate(self.names):
            if str(n).startswith("actions/setup-python"):
                self.assertGreater(i, stop)
        # pick_script yalniz standart kutuphane: python3 yeter, kurulum beklemez
        self.assertIn("python3 tools/pick_script.py",
                      self.step("sirada senaryo var mi")["run"])

    def test_an_empty_queue_stops_the_run_red(self):
        s = self.step("kuyruk bos")
        self.assertEqual(s["if"], "steps.pick.outputs.path == ''")
        self.assertIn("exit 1", s["run"])

    def test_the_closing_steps_do_not_run_on_an_empty_queue(self):
        # yoksa "video uretilemedi" diye yaniltici ikinci bir hata yazar
        for n in ("defteri isle", "sonuc"):
            self.assertIn("steps.pick.outputs.path != ''", self.step(n)["if"], n)

    def test_the_render_uses_the_queued_script(self):
        env = self.step("uret")["env"]
        self.assertEqual(env["SCRIPT"], "${{ steps.pick.outputs.path }}")

    def test_two_runs_a_day_twelve_hours_apart(self):
        # Kullanici karari (8 Kasim): ilk 30 gun gunde 2 video + A/B testi.
        # Saat :15 (tam saat GitHub'da en kalabalik), aralar esit; fazla/eksik
        # satir sessizce sayiyi degistirmesin. 4/gune donmek icin buradaki
        # sayilari ve workflow'daki cron satirlarini birlikte degistir.
        crons = [c["cron"] for c in self.y[True]["schedule"]]
        self.assertEqual(len(crons), 2)
        self.assertEqual(len(set(crons)), 2)
        hours = []
        for c in crons:
            minute, hour, *rest = c.split()
            self.assertEqual(minute, "15", c)
            self.assertEqual(rest, ["*", "*", "*"], c)
            hours.append(int(hour))
        hours.sort()
        gaps = [(b - a) % 24 for a, b in zip(hours, hours[1:] + hours[:1])]
        self.assertEqual(gaps, [12, 12])

    def test_a_short_queue_raises_a_warning_not_an_error(self):
        s = self.step("kuyruk az kaldi mi")
        self.assertIn("::warning", s["run"])
        # gunde 2 videoda 12 senaryo = 6 gun onceden haber
        self.assertIn('"$LEFT" -le 12', s["run"])
        self.assertNotIn("exit 1", s["run"])


class WorkflowCopies(unittest.TestCase):
    """GitHub yalniz .github/workflows'u calistirir; ci/ onun kopyasi. Ikisi
    ayrisirsa eski hali calismaya devam eder (tam olarak bu oldu)."""

    def test_ci_and_github_workflows_are_identical(self):
        gh = ROOT / ".github" / "workflows"
        if not gh.exists():
            self.skipTest("bu agacta .github/workflows yok")
        drift = [f.name for f in sorted((ROOT / "ci").glob("*.yml"))
                 if (gh / f.name).exists()
                 and (gh / f.name).read_text() != f.read_text()]
        self.assertEqual(drift, [], "cp ci/*.yml .github/workflows/")


if __name__ == "__main__":
    unittest.main()
