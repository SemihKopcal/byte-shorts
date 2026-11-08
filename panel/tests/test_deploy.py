"""
Dagitim sertlestirmesi: Dockerfile, compose ve ornek ayarlar. Biri gevsetilirse
(port acmak, root calistirmak, 'latest' etiketi...) bu testler kirilir.
"""
import re
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

from bytepanel import config

PANEL = Path(__file__).resolve().parents[1]
DEPLOY = PANEL / "deploy"


def compose():
    return yaml.safe_load((DEPLOY / "docker-compose.yml").read_text())


def dockerfile_lines():
    return [ln.strip() for ln in (PANEL / "Dockerfile").read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def env_example():
    out = {}
    for ln in (DEPLOY / ".env.example").read_text().splitlines():
        if ln.strip() and not ln.lstrip().startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@unittest.skipIf(yaml is None, "pyyaml yok")
class Compose(unittest.TestCase):
    def setUp(self):
        self.c = compose()
        self.s = self.c["services"]

    def test_nothing_is_published_or_privileged(self):
        for name, svc in self.s.items():
            for bad in ("ports", "privileged", "cap_add", "devices", "pid", "ipc", "userns_mode",
                        "extra_hosts", "sysctls"):
                self.assertNotIn(bad, svc, f"{name}: {bad}")
            self.assertNotIn(svc.get("network_mode"), ("host", "bridge"), name)
            for v in svc.get("volumes", []):
                src = str(v).split(":")[0] if isinstance(v, str) else str(v.get("source", ""))
                self.assertFalse(src.startswith(("/", ".", "~")), f"{name}: sunucu klasoru baglanmis: {v}")
                self.assertNotIn("docker.sock", str(v))

    def test_every_container_is_locked_down(self):
        for name, svc in self.s.items():
            self.assertIs(svc.get("read_only"), True, name)
            self.assertEqual(svc.get("cap_drop"), ["ALL"], name)
            self.assertIn("no-new-privileges:true", svc.get("security_opt", []), name)
            self.assertRegex(str(svc.get("user", "")), r"^[1-9]\d*:[1-9]\d*$", f"{name}: root olmayan sayisal kullanici")
            self.assertIn("pids_limit", svc, name)
            self.assertIn("mem_limit", svc, name)

    def test_the_panel_has_a_writable_tmp_that_cannot_execute(self):
        tmp = [t for t in self.s["panel"]["tmpfs"] if str(t).startswith("/tmp")]
        self.assertEqual(len(tmp), 1)
        for flag in ("noexec", "nosuid", "nodev"):
            self.assertIn(flag, tmp[0])

    def test_secrets_are_files_not_environment_values(self):
        env = self.s["panel"]["environment"]
        self.assertEqual(env["PANEL_ENV"], "prod")
        for k, v in env.items():
            if re.search(r"SECRET|TOKEN|KEY|PASSWORD", k):
                self.assertTrue(k.endswith("_FILE"), f"{k}: sir ortam degiskeninde olmamali")
                self.assertTrue(str(v).startswith("/run/secrets/"), k)
        for name, sec in self.c["secrets"].items():
            self.assertTrue(set(sec) == {"file"} and sec["file"].startswith("./secrets/"), name)
        self.assertEqual(set(self.s["panel"]["secrets"]), set(self.c["secrets"]))

    def test_the_tunnel_image_must_be_chosen_explicitly(self):
        image = self.s["cloudflared"]["image"]
        self.assertIn("${CLOUDFLARED_TAG:?", image)
        self.assertNotIn("latest", image)
        self.assertIn("--no-autoupdate", self.s["cloudflared"]["command"])
        self.assertEqual(self.s["cloudflared"]["env_file"], "secrets/tunnel.env")

    def test_only_the_tunnel_reaches_the_panel_and_it_waits_for_health(self):
        self.assertEqual(set(self.s), {"panel", "cloudflared"})
        self.assertEqual(self.s["cloudflared"]["depends_on"]["panel"]["condition"], "service_healthy")
        for svc in self.s.values():
            self.assertEqual(svc["networks"], ["internal"])
        self.assertIn("healthcheck", self.s["panel"])

    def test_compose_plus_example_env_satisfy_the_prod_config_and_nothing_else_is_needed(self):
        example = {**env_example(), "CF_ACCESS_TEAM_DOMAIN": "takim.cloudflareaccess.com",
                   "R2_ENDPOINT": "https://abc.r2.cloudflarestorage.com",
                   "PANEL_ALLOWED_EMAILS": "ben@example.com", "CF_ACCESS_AUD": "a" * 64}
        with tempfile.TemporaryDirectory() as d:
            env = {k: str(v) for k, v in {**example, **self.s["panel"]["environment"]}.items()}
            for k, v in list(env.items()):
                if k.endswith("_FILE"):
                    p = Path(d) / k
                    p.write_text("x" * 40)
                    env[k] = str(p)
            cfg = config.load(env)
            self.assertTrue(cfg.is_prod)
            # eksik olan her zorunlu ayar prod'da ACMAMALI: compose varsayilana yaslanmiyor
            for k in list(env):
                if k in ("PANEL_ENV", "PANEL_DB", "CLOUDFLARED_TAG"):     # sonuncusu yalniz compose okur
                    continue
                broken = {a: b for a, b in env.items() if a != k}
                with self.assertRaises(config.ConfigError, msg=k):
                    config.load(broken)


@unittest.skipIf(yaml is None, "pyyaml yok")
class Files(unittest.TestCase):
    def test_example_env_holds_no_secrets_and_only_known_keys(self):
        known = set(re.findall(r'(?:_read|_int)\(env, "([A-Z0-9_]+)"', (PANEL / "bytepanel/config.py").read_text()))
        known |= {"CLOUDFLARED_TAG"}
        ex = env_example()
        self.assertTrue(set(ex) <= known, set(ex) - known)
        for k, v in ex.items():
            self.assertNotRegex(k, r"SECRET|TOKEN|PASSWORD|ACCESS_KEY", k)
            self.assertLess(len(v), 80, k)

    def test_nothing_secret_is_tracked_in_deploy(self):
        self.assertEqual(sorted(p.name for p in (DEPLOY / "secrets").iterdir()), [".gitkeep"])
        ig = (DEPLOY / ".gitignore").read_text().split()
        for want in (".env", "secrets/*", "!secrets/.gitkeep"):
            self.assertIn(want, ig)

    def test_dockerignore_keeps_tests_deploy_and_secrets_out_of_the_image(self):
        ig = set((PANEL / ".dockerignore").read_text().split())
        for want in ("tests", "deploy", ".env", "*.db", "venv"):
            self.assertIn(want, ig)

    def test_requirements_are_fully_pinned_and_come_from_pypi(self):
        lines = [ln.strip() for ln in (PANEL / "requirements.txt").read_text().splitlines()
                 if ln.strip() and not ln.startswith("#")]
        self.assertGreater(len(lines), 10)
        for ln in lines:
            self.assertRegex(ln, r"^[A-Za-z0-9_.-]+==[\w.]+$", ln)
        text = (PANEL / "requirements.txt").read_text()
        for bad in ("--extra-index-url", "--index-url", "git+", "http://", "https://"):
            self.assertNotIn(bad, text)


class Dockerfile(unittest.TestCase):
    def test_runs_as_a_numeric_unprivileged_user_and_has_a_healthcheck(self):
        lines = dockerfile_lines()
        users = [ln for ln in lines if ln.startswith("USER ")]
        self.assertEqual(users[-1], "USER 10001:10001")
        self.assertTrue(any(ln.startswith("HEALTHCHECK") for ln in lines))
        self.assertIn("--no-create-home", " ".join(lines))

    def test_base_images_have_explicit_tags_and_the_final_stage_is_separate(self):
        froms = [ln for ln in dockerfile_lines() if ln.startswith("FROM ")]
        self.assertEqual(len(froms), 2)
        for ln in froms:
            image = ln.split()[1]
            self.assertIn(":", image)
            self.assertNotIn("latest", image)
        self.assertIn("AS build", froms[0])
        self.assertFalse(any("AS" in ln for ln in froms[1:]))

    def test_nothing_risky_is_copied_or_downloaded(self):
        text = "\n".join(dockerfile_lines())
        for bad in ("COPY . ", "ADD ", "curl ", "wget ", "| sh", "| bash", "apt-get", "chmod 777", "sudo"):
            self.assertNotIn(bad, text)
        copies = [ln for ln in dockerfile_lines() if ln.startswith("COPY ")]
        self.assertEqual(len(copies), 3)

    def test_the_server_does_not_leak_its_identity_and_the_entrypoint_exists(self):
        from bytepanel import web
        text = "\n".join(dockerfile_lines())
        self.assertIn("--no-server-header", text)
        self.assertIn("bytepanel.web:main", text)
        self.assertIn("--factory", text)
        self.assertTrue(callable(web.main))


if __name__ == "__main__":
    unittest.main()
