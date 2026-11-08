"""
Workflow guvenligi ve panel modu. YAML'i okur, kabuk parcalarini gercekten calistirir
(sahte `python` ile); ag, secret ve hesap YOK.
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:                                         # yerelde pyyaml olmayabilir; CI'da var
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# workflow girdileri, depo disindan gelen metinler ve onlardan turetilen ciktilar
UNTRUSTED = re.compile(r"\$\{\{[^}]*\b(inputs\.|github\.event|github\.head_ref|steps\.[\w-]+\.outputs)", re.I)


def wf(name):
    return yaml.safe_load((ROOT / "ci" / name).read_text())


def steps(doc, job=None):
    jobs = doc["jobs"]
    job = job or next(iter(jobs))
    return jobs[job]["steps"]


def step(doc, name, job=None):
    found = [s for s in steps(doc, job) if s.get("name") == name]
    assert len(found) == 1, (name, len(found))
    return found[0]


def triggers(doc):
    return doc.get(True) or doc.get("on")           # YAML 1.1: `on` -> True


@unittest.skipIf(yaml is None, "pyyaml yok")
class Injection(unittest.TestCase):
    def test_no_run_block_interpolates_untrusted_expressions(self):
        bad = []
        for f in sorted((ROOT / "ci").glob("*.yml")):
            for jname, job in yaml.safe_load(f.read_text())["jobs"].items():
                for s in job.get("steps", []):
                    if UNTRUSTED.search(s.get("run", "")):
                        bad.append(f"{f.name}:{jname}:{s.get('name', s.get('id', '?'))}")
        self.assertEqual(bad, [], "girdileri env ile ver, run: icine ${{ }} gomme")

    def test_every_workflow_copy_exists_and_matches(self):
        gh = ROOT / ".github" / "workflows"
        if not gh.exists():
            self.skipTest("bu agacta .github/workflows yok")
        for f in sorted((ROOT / "ci").glob("*.yml")):
            self.assertTrue((gh / f.name).exists(), f"{f.name} icin .github/workflows kopyasi yok")
            self.assertEqual((gh / f.name).read_text(), f.read_text(), f.name)

    def test_the_guard_itself_catches_the_pattern(self):
        for s in ('echo "${{ inputs.x }}"', "echo ${{ github.event.pull_request.title }}",
                  'f "${{ steps.m.outputs.dir }}"', "${{ github.head_ref }}"):
            self.assertTrue(UNTRUSTED.search(s), s)
        for s in ('echo "$X"', "echo ${{ runner.temp }}", "${{ secrets.A }}", "${{ github.run_number }}"):
            self.assertFalse(UNTRUSTED.search(s), s)


@unittest.skipIf(yaml is None, "pyyaml yok")
class PanelPublish(unittest.TestCase):
    def setUp(self):
        self.d = wf("panel-publish.yml")

    def test_only_dispatch_and_read_only_permissions(self):
        self.assertEqual(list(triggers(self.d)), ["workflow_dispatch"])
        self.assertEqual(self.d["permissions"], {"contents": "read"})
        for job in self.d["jobs"].values():
            self.assertNotIn("permissions", job)               # isi kendi basina yetki genisletemez

    def test_runs_for_the_same_video_and_platform_never_overlap(self):
        c = self.d["concurrency"]
        self.assertIn("inputs.script_id", c["group"])
        self.assertIn("inputs.platform", c["group"])
        self.assertIs(c["cancel-in-progress"], False)

    def test_inputs_match_what_the_script_and_the_panel_use(self):
        import panel_publish as pp
        ins = triggers(self.d)["workflow_dispatch"]["inputs"]
        self.assertEqual(set(ins), {"script_id", "platform", "privacy", "request_id"})
        self.assertEqual(tuple(ins["platform"]["options"]), pp.PLATFORMS)
        self.assertEqual(tuple(ins["privacy"]["options"]), pp.PRIVACY)
        for name in ("youtube", "instagram", "tiktok"):
            env = step(self.d, name)["env"]
            for k in ("SCRIPT_ID", "PLATFORM", "PRIVACY", "REQUEST_ID"):
                self.assertIn(k, env, f"{name}: {k}")

    def test_each_platform_step_gets_only_its_own_tokens(self):
        own = {"youtube": "YOUTUBE_", "instagram": "INSTAGRAM_", "tiktok": "TIKTOK_"}
        for name, prefix in own.items():
            s = step(self.d, name)
            self.assertEqual(s["if"], f"inputs.platform == '{name}'")
            keys = set(s["env"])
            self.assertTrue(any(k.startswith(prefix) for k in keys), name)
            for other, p in own.items():
                if other != name:
                    self.assertFalse(any(k.startswith(p) for k in keys), f"{name} adimi {other} token'i goruyor")
            self.assertNotIn("GH_PAT", keys)
            for k in ("R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
                self.assertIn(k, keys)

    def test_only_the_token_rotation_step_sees_the_pat(self):
        for s in steps(self.d):
            has = "GH_PAT" in s.get("env", {})
            self.assertEqual(has, s.get("name") == "tiktok yeni token", s.get("name"))

    def test_nothing_in_it_writes_to_the_repo(self):
        text = (ROOT / "ci" / "panel-publish.yml").read_text()
        for bad in ("git push", "git commit", "contents: write"):
            self.assertNotIn(bad, text)

    def test_third_party_actions_are_the_known_ones(self):
        used = {s["uses"].split("@")[0] for s in steps(self.d) if "uses" in s}
        self.assertEqual(used, {"actions/checkout", "actions/setup-python"})

    def test_the_slim_requirements_agree_with_the_main_ones(self):
        def pins(p):
            return dict(re.findall(r"^([A-Za-z0-9_.-]+)==(\S+)", p.read_text(), re.M))
        slim, main = pins(ROOT / "requirements-publish.txt"), pins(ROOT / "requirements.txt")
        self.assertTrue(slim)
        for k, v in slim.items():
            self.assertEqual(main.get(k), v, f"{k}: requirements.txt ile ayni surum olmali")


@unittest.skipIf(yaml is None, "pyyaml yok")
class DailyPanelMode(unittest.TestCase):
    def setUp(self):
        self.d = wf("daily.yml")

    def cond(self, name):
        c = step(self.d, name)["if"]
        return " ".join(str(c).split())

    def test_direct_publishing_steps_are_off_in_panel_mode(self):
        for name in ("youtube secrets kontrol", "youtube'a yukle", "instagram'a yukle", "tiktok taslagi"):
            self.assertIn("vars.PANEL_MODE != 'on'", self.cond(name), name)

    def test_nothing_is_made_public_before_approval_in_panel_mode(self):
        """Depo public: Release ve artifact herkese acik. Onay bekleyen video oraya konmamali."""
        for name in ("release", "artifact"):
            self.assertIn("vars.PANEL_MODE != 'on'", self.cond(name), name)

    def test_the_panel_step_pushes_to_r2_only_in_panel_mode(self):
        s = step(self.d, "panele gonder")
        self.assertIn("vars.PANEL_MODE == 'on'", s["if"])
        self.assertIn("steps.render.outcome == 'success'", s["if"])
        self.assertIn("tools/r2_push.py", s["run"])
        for k in ("R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
            self.assertIn(k, s["env"])
        self.assertEqual({k for k in s["env"] if "TOKEN" in k or "YOUTUBE" in k or "INSTAGRAM" in k}, set())

    def test_panel_step_comes_after_render_and_before_the_ledger_commit(self):
        names = [s.get("name") for s in steps(self.d)]
        self.assertLess(names.index("uret"), names.index("panele gonder"))
        self.assertLess(names.index("panele gonder"), names.index("defteri isle"))

    # ── kabuk parcalarini gercekten calistir ─────────────────────────────
    def run_shell(self, script, env, workdir):
        bin_ = Path(workdir) / "bin"
        bin_.mkdir(exist_ok=True)
        py = bin_ / "python"
        py.write_text('#!/bin/sh\necho "$@" >> "$CALLS"\n')
        py.chmod(py.stat().st_mode | stat.S_IEXEC)
        calls = Path(workdir) / "calls"
        e = {"PATH": f"{bin_}:{os.environ['PATH']}", "CALLS": str(calls), **env}
        p = subprocess.run(["bash", "-e", "-c", script], env=e, cwd=workdir, capture_output=True, text=True)
        return p, (calls.read_text() if calls.exists() else "")

    def mark_block(self):
        run = step(self.d, "defteri isle")["run"]
        return run[:run.index("git config")]               # git/push kismina girmeden

    def test_a_failed_panel_push_does_not_mark_the_script_built(self):
        base = {"SCRIPT": "content/scripts/p002-x.json"}
        cases = [({"PANEL_MODE": "on", "RENDER": "success", "PANEL": "failure"}, False),
                 ({"PANEL_MODE": "on", "RENDER": "success", "PANEL": "success"}, True),
                 ({"PANEL_MODE": "on", "RENDER": "failure", "PANEL": "skipped"}, True),   # bozuk senaryo tikamaz
                 ({"PANEL_MODE": "", "RENDER": "success", "PANEL": "skipped"}, True),
                 ({"PANEL_MODE": "", "RENDER": "failure", "PANEL": "skipped"}, True)]
        for env, marked in cases:
            with tempfile.TemporaryDirectory() as w:
                p, calls = self.run_shell(self.mark_block(), {**base, **env}, w)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual("--mark p002-x.json" in calls, marked, (env, calls, p.stdout))

    def result_block(self):
        return step(self.d, "sonuc")["run"]

    def test_the_run_turns_red_when_the_panel_push_failed(self):
        ok = {"RENDER": "success", "UPLOAD": "skipped", "YTCHECK": "skipped", "RELEASE": "success",
              "INSTAGRAM": "skipped", "TIKTOK": "skipped"}
        cases = [({"PANEL_MODE": "on", "PANEL": "failure"}, 1),
                 ({"PANEL_MODE": "on", "PANEL": "success"}, 0),
                 ({"PANEL_MODE": "", "PANEL": "skipped"}, 0),
                 ({"PANEL_MODE": "on", "PANEL": "failure", "RENDER": "failure"}, 1)]    # render zaten kirmizi
        for extra, code in cases:
            with tempfile.TemporaryDirectory() as w:
                p, _ = self.run_shell(self.result_block(), {**ok, **extra}, w)
                self.assertEqual(p.returncode, code, (extra, p.stdout, p.stderr))

    def test_the_old_direct_path_still_fails_on_a_bad_youtube_upload(self):
        env = {"RENDER": "success", "UPLOAD": "failure", "YTCHECK": "success", "RELEASE": "success",
               "INSTAGRAM": "skipped", "TIKTOK": "skipped", "PANEL_MODE": "", "PANEL": "skipped"}
        with tempfile.TemporaryDirectory() as w:
            p, _ = self.run_shell(self.result_block(), env, w)
            self.assertEqual(p.returncode, 1)


@unittest.skipIf(yaml is None, "pyyaml yok")
class CheckAndAudit(unittest.TestCase):
    def test_check_runs_the_panel_tests(self):
        d = wf("check.yml")
        self.assertIn("panel", d["jobs"])
        text = json.dumps(d["jobs"]["panel"])
        self.assertIn("panel/requirements.txt", text)
        self.assertIn("unittest discover -s tests", text)

    def test_audit_is_weekly_read_only_and_covers_both_requirement_sets(self):
        d = wf("audit.yml")
        t = triggers(d)
        self.assertIn("schedule", t)
        self.assertEqual(d["permissions"], {"contents": "read"})
        text = (ROOT / "ci" / "audit.yml").read_text()
        for f in ("panel/requirements.txt", "requirements.txt", "requirements-publish.txt"):
            self.assertIn(f, text)

    def test_dependabot_watches_pip_docker_and_actions(self):
        p = ROOT / ".github" / "dependabot.yml"
        if not p.exists():
            self.skipTest("bu agacta .github yok")
        eco = {(u["package-ecosystem"], u["directory"]) for u in yaml.safe_load(p.read_text())["updates"]}
        self.assertEqual(eco, {("pip", "/panel"), ("pip", "/"), ("docker", "/panel"), ("github-actions", "/")})


if __name__ == "__main__":
    unittest.main()
