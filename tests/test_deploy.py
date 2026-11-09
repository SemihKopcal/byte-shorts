"""
Panelin sunucuya dagitimi: compose sertlesmesi ve panel/deploy/update.sh.

update.sh gercekten calistirilir; `docker` yerine PATH'e konan SAHTE bir docker var
(cagrilari gunluge yazar, saglik durumunu testin istedigi gibi dondurur). Git gercek:
gecici bir "origin" ve bir "sunucu kopyasi" kurulur. Ag, docker, sir YOK.

    python -m unittest tests.test_deploy -v
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:                                         # yerelde pyyaml olmayabilir; CI'da var
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "panel" / "deploy" / "update.sh"

FAKE_DOCKER = r"""#!/usr/bin/env bash
# sahte docker: cagriyi yaz, durumu $STATE altindaki dosyalardan oku
echo "docker $*" >> "$STATE/calls.log"
cmd="$1 $2"
case "$cmd" in
  "compose ps")      [ -f "$STATE/running" ] && echo cid123; exit 0 ;;
  "compose exec")    exit "${STUB_BACKUP_RC:-0}" ;;
  "compose build")   exit "${STUB_BUILD_RC:-0}" ;;
  "compose up")
      touch "$STATE/running"
      case "$*" in *--no-build*) echo healthy > "$STATE/health" ;; *) echo "${STUB_NEW_HEALTH:-healthy}" > "$STATE/health" ;; esac
      exit 0 ;;
  "image inspect")   [ -f "$STATE/has_image" ] && exit 0 || exit 1 ;;
  "image prune")     exit 0 ;;
  "inspect -f")      cat "$STATE/health" 2>/dev/null || echo none; exit 0 ;;
esac
case "$1" in tag) exit 0 ;; esac
exit 0
"""


def sh(cwd, *args, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=check)


def git(cwd, *args):
    return sh(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", *args).stdout.strip()


class Server:
    """origin (bare) + sunucu kopyasi + sahte docker."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        self.dev = self.tmp / "dev"
        self.app = self.tmp / "app"
        self.state = self.tmp / "state"
        self.bin = self.tmp / "bin"
        self.state.mkdir()
        self.bin.mkdir()
        sh(self.tmp, "git", "init", "-q", "--bare", "-b", "main", str(self.origin))
        sh(self.tmp, "git", "clone", "-q", str(self.origin), str(self.dev))
        git(self.dev, "checkout", "-q", "-b", "main")
        (self.dev / "panel" / "deploy").mkdir(parents=True)
        shutil.copy(SCRIPT, self.dev / "panel" / "deploy" / "update.sh")
        (self.dev / "panel" / "deploy" / "update.sh").chmod(0o755)
        (self.dev / "panel" / "app.py").write_text("v1\n")
        (self.dev / "content.txt").write_text("c1\n")
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-qm", "v1")
        git(self.dev, "push", "-q", "-u", "origin", "main")
        sh(self.tmp, "git", "clone", "-q", str(self.origin), str(self.app))
        (self.state / "running").write_text("")
        (self.state / "has_image").write_text("")
        (self.state / "health").write_text("healthy\n")
        d = self.bin / "docker"
        d.write_text(FAKE_DOCKER)
        d.chmod(d.stat().st_mode | stat.S_IEXEC)

    def push(self, path, text, msg):
        (self.dev / path).write_text(text)
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-qm", msg)
        git(self.dev, "push", "-q", "origin", "main")

    def head(self):
        return git(self.app, "rev-parse", "HEAD")

    def calls(self):
        p = self.state / "calls.log"
        return p.read_text().splitlines() if p.exists() else []

    def update(self, *args, **extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state),
                   BYTE_HEALTH_WAIT="3", BYTE_POLL="0.1", **extra)
        return subprocess.run(["bash", str(self.app / "panel" / "deploy" / "update.sh"), *args],
                              env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def has_call(self, text):
        return any(text in c for c in self.calls())


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "git/bash yok")
class UpdateScript(unittest.TestCase):
    def setUp(self):
        self.s = Server()
        self.addCleanup(shutil.rmtree, self.s.tmp, ignore_errors=True)

    def test_already_up_to_date_does_nothing(self):
        r = self.s.update("-y")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("guncel", r.stdout)
        self.assertEqual(self.s.calls(), [])

    def test_content_only_change_advances_the_code_without_rebuilding(self):
        self.s.push("content.txt", "c2\n", "icerik")
        before = self.s.head()
        r = self.s.update("-y")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(self.s.head(), before)
        self.assertIn("yeniden derleme gerekmiyor", r.stdout)
        self.assertEqual(self.s.calls(), [])                     # docker'a hic dokunmadi

    def test_a_panel_change_is_backed_up_built_started_and_checked(self):
        self.s.push("panel/app.py", "v2\n", "panel")
        r = self.s.update("-y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.s.head(), git(self.s.dev, "rev-parse", "HEAD"))
        order = [i for i, c in enumerate(self.s.calls())
                 if any(k in c for k in ("compose exec", "compose build", "compose up"))]
        names = [self.s.calls()[i] for i in order]
        self.assertIn("bytepanel.backup", names[0])             # once yedek
        self.assertIn("compose build", names[1])
        self.assertIn("compose up", names[2])
        self.assertTrue(self.s.has_call("docker tag byte-panel:local byte-panel:prev"))
        self.assertIn("TAMAM", r.stdout)

    def test_an_unhealthy_panel_rolls_back_code_and_image(self):
        before = self.s.head()
        self.s.push("panel/app.py", "bozuk\n", "bozuk panel")
        r = self.s.update("-y", STUB_NEW_HEALTH="unhealthy")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(self.s.head(), before, "kod eski commit'e donmeli")
        self.assertEqual((self.s.app / "panel" / "app.py").read_text(), "v1\n")
        self.assertTrue(self.s.has_call("docker tag byte-panel:prev byte-panel:local"))
        self.assertTrue(self.s.has_call("--no-build --force-recreate"))
        self.assertIn("Geri alma tamam", r.stdout)

    def test_a_build_failure_leaves_the_running_panel_alone(self):
        before = self.s.head()
        self.s.push("panel/app.py", "v2\n", "panel")
        r = self.s.update("-y", STUB_BUILD_RC="1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.s.head(), before)
        self.assertFalse(self.s.has_call("compose up"), "derleme basarisizken yeni konteyner baslatilmamali")

    def test_a_failed_backup_changes_nothing(self):
        before = self.s.head()
        self.s.push("panel/app.py", "v2\n", "panel")
        r = self.s.update("-y", STUB_BACKUP_RC="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("yedek alinamadi", r.stderr)
        self.assertEqual(self.s.head(), before)
        self.assertFalse(self.s.has_call("compose build"))

    def test_local_edits_on_the_server_are_never_overwritten(self):
        (self.s.app / "panel" / "app.py").write_text("elle degistirildi\n")
        self.s.push("content.txt", "c2\n", "icerik")
        r = self.s.update("-y")
        self.assertEqual(r.returncode, 1)
        self.assertIn("yerel degisiklik", r.stderr)
        self.assertEqual((self.s.app / "panel" / "app.py").read_text(), "elle degistirildi\n")

    def test_a_rewritten_history_is_refused(self):
        git(self.s.dev, "reset", "-q", "--hard", "HEAD")
        (self.s.dev / "panel" / "app.py").write_text("baska tarih\n")
        git(self.s.dev, "commit", "-qa", "--amend", "-m", "yeniden yazildi")
        git(self.s.dev, "push", "-q", "--force", "origin", "main")
        before = self.s.head()
        r = self.s.update("-y")
        self.assertEqual(r.returncode, 1)
        self.assertIn("devami degil", r.stderr)
        self.assertEqual(self.s.head(), before)
        self.assertFalse(self.s.has_call("compose build"))

    def test_wrong_branch_is_refused(self):
        git(self.s.app, "switch", "-q", "-c", "baska")
        r = self.s.update("-y")
        self.assertEqual(r.returncode, 1)
        self.assertIn("main", r.stderr)

    def test_it_will_not_guess_consent_when_not_interactive(self):
        self.s.push("panel/app.py", "v2\n", "panel")
        before = self.s.head()
        r = self.s.update()                                     # -y yok, stdin terminal degil
        self.assertEqual(r.returncode, 1)
        self.assertIn("-y", r.stderr)
        self.assertEqual(self.s.head(), before)
        self.assertFalse(self.s.has_call("compose build"))

    def test_unknown_argument_is_a_usage_error(self):
        self.assertEqual(self.s.update("--sil").returncode, 2)

    def test_the_script_is_valid_bash_and_shellcheck_clean(self):
        self.assertEqual(sh(ROOT, "bash", "-n", str(SCRIPT), check=False).returncode, 0)
        if shutil.which("shellcheck"):
            r = sh(ROOT, "shellcheck", "-S", "warning", str(SCRIPT), check=False)
            self.assertEqual(r.returncode, 0, r.stdout)


@unittest.skipIf(yaml is None, "pyyaml yok")
class ComposeHardening(unittest.TestCase):
    """Panelin kisitlari sessizce gevsemesin: biri 'gecici' diye ports ekler, kimse fark etmez."""

    def setUp(self):
        self.c = yaml.safe_load((ROOT / "panel" / "deploy" / "docker-compose.yml").read_text())["services"]

    def test_nothing_is_published_to_the_internet(self):
        for name, svc in self.c.items():
            self.assertNotIn("ports", svc, f"{name}: ports yayinliyor; panele tek giris cloudflared tuneli")
            self.assertNotIn("network_mode", svc, name)
            self.assertIsNot(svc.get("privileged"), True, name)

    def test_containers_are_unprivileged_read_only_and_limited(self):
        for name, svc in self.c.items():
            self.assertIs(svc.get("read_only"), True, name)
            self.assertEqual(svc.get("cap_drop"), ["ALL"], name)
            self.assertIn("no-new-privileges:true", svc.get("security_opt", []), name)
            self.assertTrue(str(svc.get("user", "0")).split(":")[0] not in ("0", "root"), f"{name} root calisiyor")
            for k in ("mem_limit", "pids_limit", "cpus"):
                self.assertIn(k, svc, f"{name}: {k} yok")

    def test_secrets_come_from_files_not_from_the_environment(self):
        env = self.c["panel"].get("environment", {})
        for k in env:
            self.assertFalse(k in ("R2_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "PANEL_CSRF_SECRET"),
                             f"{k} duz ortam degiskeni olamaz (docker inspect'te gorunur); *_FILE kullan")

    def test_the_tunnel_version_is_chosen_by_the_owner_not_latest(self):
        img = self.c["cloudflared"]["image"]
        self.assertIn("CLOUDFLARED_TAG", img)
        self.assertNotIn(":latest", img)

    def test_dockerfile_drops_root_and_keeps_secrets_out_of_the_image(self):
        text = (ROOT / "panel" / "Dockerfile").read_text()
        self.assertIn("USER 10001:10001", text)
        for bad in ("COPY . ", "COPY .env", "ADD ", "secrets"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
