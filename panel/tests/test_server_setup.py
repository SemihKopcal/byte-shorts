"""
deploy/server-setup.sh: sunucuda sirlari ve .env'i yazan script. Gercek docker/sudo yerine
sahte komutlarla, gecici bir /srv/www/byte benzeri agacta calistirilir.

Burada korunanlar: sirlar ekrana dusmez, dosya izinleri sikidir, .env anahtarlari
.env.example ile birebir ayni, yanlis giris reddedilir, ikinci calistirma var olana dokunmaz.
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parents[1]
DEPLOY = PANEL / "deploy"
SCRIPT = DEPLOY / "server-setup.sh"
BASH = shutil.which("bash")

SECRETS = {
    "r2_key": "SENTINEL_R2_KEY_ID_0123456789",
    "r2_secret": "SENTINEL_R2_SECRET_0123456789abcdef",
    "gh": "SENTINEL_GH_TOKEN_0123456789abcdef",
    "tunnel": "SENTINEL_TUNNEL_0123456789abcdef",
}
ENDPOINT = "https://" + "b7d9ce8f54efef4953cd2c36d3229d0c" + ".r2.cloudflarestorage.com"

FAKE_DOCKER = """#!/bin/sh
echo "docker $*" >> "$STUB_LOG"
[ "$1" = info ] && exit 0
if [ "$1" = compose ]; then
  case "$2" in
    version|config) exit 0;;
    up) exit 0;;
    ps) [ "$3" = -q ] && { echo cid123; exit 0; }; exit 0;;
  esac
fi
[ "$1" = inspect ] && { echo healthy; exit 0; }
exit 9
"""
# sudo yalniz chown'u taklit eder (testi calistiran kullanici 10001'e chown yapamaz)
FAKE_SUDO = """#!/bin/sh
if [ "$1" = chown ]; then echo "chown $*" >> "$STUB_LOG"; exit 0; fi
exec "$@"
"""


@unittest.skipIf(BASH is None, "bash yok")
class ServerSetup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.deploy = root / "srv/www/byte/app/panel/deploy"
        (self.deploy / "secrets").mkdir(parents=True)
        for n in ("docker-compose.yml", ".env.example", ".gitignore", "server-setup.sh"):
            shutil.copy(DEPLOY / n, self.deploy / n)
        (self.deploy / "secrets/.gitkeep").touch()
        self.stub = root / "stub"
        self.stub.mkdir()
        for n, body in (("docker", FAKE_DOCKER), ("sudo", FAKE_SUDO)):
            (self.stub / n).write_text(body)
            (self.stub / n).chmod(0o755)
        self.log = root / "stub.log"
        self.log.touch()
        self.base = root / "srv/www/byte"

    def run_script(self, answers):
        env = {**os.environ, "PATH": f"{self.stub}:{os.environ['PATH']}", "STUB_LOG": str(self.log)}
        p = subprocess.run([BASH, str(self.deploy / "server-setup.sh")], input="\n".join(answers) + "\n",
                           capture_output=True, text=True, env=env, timeout=60)
        return p

    def first_run_answers(self, endpoint=ENDPOINT, extra_first=()):
        return [*extra_first, endpoint, "", "", "", "byte-team.cloudflareaccess.com", "a" * 64,
                "Semih@Example.com", "2026.1.0",
                SECRETS["r2_key"], SECRETS["r2_secret"], SECRETS["gh"], SECRETS["tunnel"], ""]

    def test_first_run_writes_env_and_secrets_with_tight_permissions(self):
        p = self.run_script(self.first_run_answers())
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

        env = dict(ln.split("=", 1) for ln in (self.deploy / ".env").read_text().splitlines()
                   if ln and not ln.startswith("#"))
        example = [ln.split("=", 1)[0] for ln in (DEPLOY / ".env.example").read_text().splitlines()
                   if ln.strip() and not ln.lstrip().startswith("#") and "=" in ln]
        self.assertEqual(list(env), example, ".env anahtarlari .env.example ile ayni ve ayni sirada olmali")
        self.assertEqual(env["R2_ENDPOINT"], ENDPOINT)
        self.assertEqual(env["R2_BUCKET"], "byte-videos")
        self.assertEqual(env["PANEL_ALLOWED_EMAILS"], "semih@example.com")
        self.assertEqual(stat.S_IMODE((self.deploy / ".env").stat().st_mode), 0o600)

        s = self.deploy / "secrets"
        self.assertEqual((s / "r2_access_key_id").read_text(), SECRETS["r2_key"])
        self.assertEqual((s / "r2_secret_access_key").read_text(), SECRETS["r2_secret"])
        self.assertEqual((s / "github_token").read_text(), SECRETS["gh"])
        self.assertEqual((s / "tunnel.env").read_text(), f"TUNNEL_TOKEN={SECRETS['tunnel']}\n")
        self.assertRegex((s / "csrf_secret").read_text(), r"^[0-9a-f]{64}$")
        for n in ("r2_access_key_id", "r2_secret_access_key", "github_token", "csrf_secret"):
            self.assertEqual(stat.S_IMODE((s / n).stat().st_mode), 0o400, n)
        self.assertEqual(stat.S_IMODE((s / "tunnel.env").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(s.stat().st_mode), 0o700)
        self.assertTrue((self.base / "backups").is_dir())

        log = self.log.read_text()
        self.assertIn("docker compose up -d --build", log)
        if os.geteuid() == 0:        # root: sudo yok, chown gercekten yapilir
            for n in ("r2_access_key_id", "r2_secret_access_key", "github_token", "csrf_secret"):
                self.assertEqual((s / n).stat().st_uid, 10001, n)
        else:                        # normal kullanici: sudo taklidi chown'u kaydeder
            self.assertEqual(log.count("chown 10001:10001"), 4)

    def test_no_secret_ever_reaches_the_output_or_the_log(self):
        p = self.run_script(self.first_run_answers())
        blob = p.stdout + p.stderr + self.log.read_text() + (self.deploy / ".env").read_text()
        for v in SECRETS.values():
            self.assertNotIn(v, blob)

    def test_a_wrong_endpoint_is_rejected_and_asked_again(self):
        bad = ENDPOINT + "/byte-videos"          # S3 API adresini bucket adiyla kopyalamak: gercek hata
        p = self.run_script(self.first_run_answers(extra_first=[bad]))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("bucket-adi olmamali", p.stdout)
        self.assertIn(f"R2_ENDPOINT={ENDPOINT}\n", (self.deploy / ".env").read_text())

    def test_second_run_keeps_everything_and_only_asks_to_start(self):
        self.run_script(self.first_run_answers())
        before = {n: (self.deploy / n).read_bytes() for n in (".env", "secrets/csrf_secret", "secrets/tunnel.env")}
        p = self.run_script(["n"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(".env var, korundu", p.stdout)
        self.assertIn("Baslatmadim", p.stdout)
        for n, b in before.items():
            self.assertEqual((self.deploy / n).read_bytes(), b, n)

    def write_env(self, **override):
        env = {k: v for k, v in (ln.split("=", 1) for ln in (DEPLOY / ".env.example").read_text().splitlines()
                                 if ln.strip() and not ln.lstrip().startswith("#") and "=" in ln)}
        env.update({"R2_ENDPOINT": ENDPOINT, "CF_ACCESS_TEAM_DOMAIN": "byte-team.cloudflareaccess.com",
                    "CF_ACCESS_AUD": "a" * 64, "PANEL_ALLOWED_EMAILS": "semih@example.com", "CLOUDFLARED_TAG": "2026.1.0"})
        env.update(override)
        p = self.deploy / ".env"
        p.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
        p.chmod(0o644)
        return p

    def secret_answers(self):
        return [SECRETS["r2_key"], SECRETS["r2_secret"], SECRETS["gh"], SECRETS["tunnel"], ""]

    def test_a_complete_env_from_elsewhere_is_kept_and_locked_down(self):
        p = self.write_env()
        before = p.read_bytes()
        r = self.run_script(self.secret_answers())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("eksiksiz", r.stdout)
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_an_env_with_an_empty_value_is_refused_and_names_the_key(self):
        self.write_env(CF_ACCESS_AUD="")
        r = self.run_script(self.secret_answers())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CF_ACCESS_AUD", r.stdout)
        self.assertFalse(list((self.deploy / "secrets").glob("r2_*")), "hata varken sir dosyasi yazilmamali")

    def test_an_env_holding_secrets_is_refused_without_printing_them(self):
        self.write_env(R2_SECRET_ACCESS_KEY=SECRETS["r2_secret"], R2_ACCESS_KEY_ID=SECRETS["r2_key"])
        r = self.run_script(self.secret_answers())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("R2_SECRET_ACCESS_KEY", r.stdout)
        self.assertIn("R2_ACCESS_KEY_ID", r.stdout)
        for v in SECRETS.values():
            self.assertNotIn(v, r.stdout + r.stderr)

    def test_the_script_never_traces_or_echoes_the_secret_variable(self):
        text = SCRIPT.read_text()
        self.assertNotRegex(text, r"(?m)^\s*set\s+-[a-z]*x")
        self.assertIn("read -rs", text)
        for ln in text.splitlines():
            if re.search(r"\$\{?v\}?(?![A-Za-z0-9_])", ln):
                self.assertNotRegex(ln, r"\b(echo|say)\b", ln)
                if "printf" in ln:
                    self.assertIn(">", ln, ln)       # sir yalniz dosyaya yazilir, ekrana basilmaz

    def test_chmod_comes_before_chown_for_the_secret_files(self):
        """chown 10001 sonrasi normal kullanici chmod yapamaz; sira bozulursa kurulum yarida kalir."""
        text = SCRIPT.read_text()
        self.assertLess(text.index('chmod 400 "$SECRETS/$f"'), text.index('chown 10001:10001 "$SECRETS/$f"'))


if __name__ == "__main__":
    unittest.main()
