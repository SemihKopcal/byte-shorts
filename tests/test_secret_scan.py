"""
tools/secret_scan.py: sirlari bulur, degerini ASLA yazdirmaz, yer tutuculara tepki vermez.

Bu dosyadaki sahte sirlar parca parca birlestirilerek yazilir; yoksa tarayici
kendi testini yakalardi.
"""
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import secret_scan as ss                                    # noqa: E402

# Gercek degil: bicimleri tutan rastgele dizgiler.
GH = "gh" + "p_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5"
GH_PAT = "github" + "_pat_" + "11ABCDEFG0" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5hJ7kL9mN1pQ3sT5v"
GOOGLE = "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q"
GOCSPX = "GOC" + "SPX-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
SLACK = "xo" + "xb-" + "123456789012-abcdefghijklmnop"
AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
META = "EA" + "AG" + "Zb3Kq9XpL2mN8vR4tY6wU1cD5fH7jS0aE3gB9nM2kQ4"
JWT = "ey" + "J" + "hIjoiQUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5YWJjZGVmZ2hpamtsbW5vcHFy"
PEM = "-----BEGIN " + "PRIVATE KEY-----"
STRONG = "Zq8f3KxP0wLm9TnB7vRc2YhD5sJ1aEu4"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def repo(files: dict) -> Path:
    d = Path(tempfile.mkdtemp())
    git(d, "init", "-q")
    for name, text in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "x")
    return d


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(list(argv))
    return code, buf.getvalue()


class Patterns(unittest.TestCase):
    def test_each_provider_pattern_is_found(self):
        cases = {"GitHub token": GH, "Google API anahtari": GOOGLE, "Google OAuth istemci sirri": GOCSPX,
                 "Slack token": SLACK, "AWS erisim anahtari": AWS, "Meta/Instagram token": META,
                 "JWT / Cloudflare tunel token'i": JWT, "Ozel anahtar blogu": PEM}
        for kind, text in cases.items():
            self.assertIn(kind, ss.scan_line(f"x = {text}"), kind)
        self.assertIn("GitHub token", ss.scan_line(GH_PAT))

    def test_assignment_with_a_random_value_is_found(self):
        self.assertEqual(ss.scan_line(f'api_key = "{STRONG}"'), ["yuksek entropili atama"])
        self.assertEqual(ss.scan_line(f"TOKEN: '{STRONG}'"), ["yuksek entropili atama"])

    def test_ordinary_text_and_placeholders_are_not_flagged(self):
        for line in ('api_key = "changeme-changeme-changeme-1"',
                     'token = "your_token_goes_here_1234567890"',
                     'password = "aaaaaaaaaaaaaaaaaaaaaaaaaaaa"',      # uzun ama entropisiz
                     'secret = os.environ["YOUTUBE_CLIENT_SECRET"]',
                     "R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}",
                     'sha256 = "' + "ab12" * 16 + '"',                  # ozet, atama anahtari sir degil
                     "Instagram token'i 60 gun yasiyor",
                     f"{GH} # secret-scan: allow"):
            self.assertEqual(ss.scan_line(line), [], line)

    def test_tests_folder_only_gets_provider_patterns(self):
        d = repo({"tests/t.py": f'api_key = "{STRONG}"\n', "app.py": f'api_key = "{STRONG}"\n'})
        found = {f for f, _, _ in ss.scan_tree(d)}
        self.assertEqual(found, {"app.py"})

    def test_entropy(self):
        self.assertLess(ss.entropy("a" * 30), 0.1)
        self.assertGreater(ss.entropy(STRONG), 4.0)


class TreeAndHistory(unittest.TestCase):
    def test_a_leaked_token_is_reported_without_its_value(self):
        d = repo({"cfg.txt": f"hello\nkey: {GH}\n"})
        code, out = run("--root", str(d))
        self.assertEqual(code, 1)
        self.assertIn("cfg.txt:2", out)
        self.assertIn("GitHub token", out)
        self.assertNotIn(GH, out)
        self.assertNotIn(GH[:12], out)

    def test_a_clean_tree_passes(self):
        d = repo({"a.py": "print('merhaba')\n"})
        self.assertEqual(run("--root", str(d))[0], 0)

    def test_history_finds_a_secret_that_was_deleted_later(self):
        d = repo({"a.txt": f"k={GOOGLE}\n"})
        (d / "a.txt").write_text("k=ortam degiskeninden\n")
        git(d, "commit", "-qam", "sir silindi")
        self.assertEqual(run("--root", str(d))[0], 0)                     # simdiki agac temiz
        code, out = run("--root", str(d), "--history")
        self.assertEqual(code, 1)                                         # ama gecmiste duruyor
        self.assertIn("a.txt@", out)
        self.assertIn("Google API anahtari", out)
        self.assertNotIn(GOOGLE, out)

    def test_binary_and_missing_files_do_not_crash_the_scan(self):
        d = repo({"a.png": "x"})
        (d / "b.bin").write_bytes(b"\xff\xfe\x00\x01")
        git(d, "add", "-A")
        git(d, "commit", "-qm", "bin")
        self.assertEqual(run("--root", str(d))[0], 0)

    def test_this_repository_is_clean(self):
        self.assertEqual(ss.scan_tree(ROOT), [], "depoda sir olabilecek bir sey var: python tools/secret_scan.py")


if __name__ == "__main__":
    unittest.main()
