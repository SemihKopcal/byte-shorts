"""
Instagram / TikTok yukleyicileri, token yenileme, defter ve video barindirma.
AG YOK: HTTP sahte, bekleme sahte.

    python -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from publish import instagram as IG
from publish import ledger, net
from publish import tiktok as TT

ROOT = Path(__file__).resolve().parent.parent


class Http:
    """Sirayla cevap veren sahte HTTP. Her cagri (yontem, url, kwargs) kaydedilir."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.replies.pop(0) if self.replies else (500, {})


def run_main(mod, argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}, clear=False), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ═══ net / ledger ═══════════════════════════════════════════════════════
class NetAndLedger(unittest.TestCase):
    def test_error_text_reads_the_common_shapes(self):
        self.assertIn("OAuthException", net.err_text(
            {"error": {"code": 190, "type": "OAuthException", "message": "bad token"}}))
        self.assertIn("invalid_grant", net.err_text(
            {"error": "invalid_grant", "error_description": "expired"}))
        self.assertEqual(net.err_text({"raw": "<html>"}), "<html>")
        self.assertEqual(net.err_text("x"), "x")

    def test_ledger_records_and_blocks_a_second_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(ledger.done("v1", "instagram", tmp))
            ledger.record("v1", "instagram", {"media_id": "9"}, tmp)
            self.assertTrue(ledger.done("v1", "instagram", tmp))
            self.assertFalse(ledger.done("v1", "tiktok", tmp))
            self.assertFalse(ledger.done("v2", "instagram", tmp))
            d = json.loads((Path(tmp) / "content/social.json").read_text())
            self.assertEqual(d["v1"]["instagram"]["media_id"], "9")
            self.assertIn("at", d["v1"]["instagram"])

    def test_ledger_survives_a_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "content/social.json"
            p.parent.mkdir(parents=True)
            p.write_text("{not json")
            self.assertFalse(ledger.done("v1", "instagram", tmp))
            ledger.record("v1", "instagram", {}, tmp)
            self.assertTrue(ledger.done("v1", "instagram", tmp))


# ═══ Instagram ══════════════════════════════════════════════════════════
class Instagram(unittest.TestCase):
    def go(self, http, **kw):
        sleeps = []
        res = IG.publish_reel("https://x.github.io/r/v.mp4", "caption", user_id="17",
                              token="T", http=http, sleep=sleeps.append,
                              log=lambda m: None, **kw)
        return res, sleeps

    def test_happy_path_waits_for_finished_then_publishes(self):
        http = Http((200, {"id": "C1"}),
                    (200, {"status_code": "IN_PROGRESS"}),
                    (200, {"status_code": "IN_PROGRESS"}),
                    (200, {"status_code": "FINISHED"}),
                    (200, {"id": "M1"}),
                    (200, {"permalink": "https://instagram.com/reel/abc"}))
        res, sleeps = self.go(http)
        self.assertEqual(res, {"media_id": "M1",
                               "permalink": "https://instagram.com/reel/abc"})
        self.assertEqual(len(sleeps), 2)
        create, publish = http.calls[0], http.calls[4]
        self.assertEqual(create[0], "POST")
        self.assertTrue(create[1].endswith("/17/media"))
        self.assertEqual(create[2]["form"]["media_type"], "REELS")
        self.assertEqual(create[2]["form"]["video_url"], "https://x.github.io/r/v.mp4")
        self.assertTrue(publish[1].endswith("/17/media_publish"))
        self.assertEqual(publish[2]["form"]["creation_id"], "C1")
        self.assertTrue(create[1].startswith("https://graph.instagram.com/"))

    def test_meta_cannot_process_the_video(self):
        http = Http((200, {"id": "C1"}),
                    (200, {"status_code": "ERROR", "status": "Error: 2207026"}))
        with self.assertRaises(IG.IGError) as cm:
            self.go(http)
        self.assertIn("ERROR", str(cm.exception))
        self.assertIn("2207026", str(cm.exception))
        self.assertEqual(len(http.calls), 2)              # yayinlamaya HIC gitmedi

    def test_container_failure_explains_why(self):
        http = Http((400, {"error": {"code": 190, "message": "Invalid OAuth token"}}))
        with self.assertRaises(IG.IGError) as cm:
            self.go(http)
        self.assertIn("Invalid OAuth token", str(cm.exception))

    def test_gives_up_when_never_ready(self):
        http = Http((200, {"id": "C1"}), *[(200, {"status_code": "IN_PROGRESS"})] * 50)
        with self.assertRaises(IG.IGError) as cm:
            self.go(http, poll_every=15, max_wait=45)
        self.assertIn("hazir olmadi", str(cm.exception))
        self.assertEqual(sum(1 for c in http.calls if "media_publish" in c[1]), 0)
        # 45 sn butce / 15 sn aralik: en fazla ~4 durum sorgusu. Sinir calismazsa yuzlerce olur.
        polls = [c for c in http.calls if c[0] == "GET"]
        self.assertLessEqual(len(polls), 5)

    def test_publish_failure_is_reported(self):
        http = Http((200, {"id": "C1"}), (200, {"status_code": "FINISHED"}),
                    (400, {"error": {"message": "daily limit"}}))
        with self.assertRaises(IG.IGError) as cm:
            self.go(http)
        self.assertIn("daily limit", str(cm.exception))

    def test_caption_over_limit_never_calls_the_api(self):
        http = Http()
        with self.assertRaises(IG.IGError):
            IG.publish_reel("u", "x" * 2201, user_id="1", token="T", http=http)
        self.assertEqual(http.calls, [])

    def test_polling_tolerates_a_transient_server_error(self):
        http = Http((200, {"id": "C1"}), (503, {}), (200, {"status_code": "FINISHED"}),
                    (200, {"id": "M1"}), (200, {}))
        res, _ = self.go(http)
        self.assertEqual(res["media_id"], "M1")

    def test_refresh_returns_the_new_token(self):
        http = Http((200, {"access_token": "NEW", "expires_in": 5183944}))
        self.assertEqual(IG.refresh("OLD", http), ("NEW", 5183944))
        self.assertIn("ig_refresh_token", http.calls[0][1])
        with self.assertRaises(IG.IGError):
            IG.refresh("OLD", Http((400, {"error": {"message": "too new"}})))

    def test_check(self):
        self.assertEqual(IG.check("T", Http((200, {"username": "byte_knowledge",
                                                   "user_id": "17"})))["username"],
                         "byte_knowledge")
        with self.assertRaises(IG.IGError):
            IG.check("T", Http((400, {"error": {"message": "bad"}})))

    # -- Facebook-tarzi token ("EAA...", Meta'nin yeni uygulamalarda verdigi Unified login) --
    FB = "EAAeTESTTOKEN"

    def test_token_kind_picks_the_host(self):
        self.assertTrue(IG.is_fb_token(self.FB))
        self.assertFalse(IG.is_fb_token("IGAAxyz"))
        self.assertTrue(IG._url("17/media", self.FB).startswith("https://graph.facebook.com/"))
        self.assertTrue(IG._url("17/media", "IGAAxyz").startswith("https://graph.instagram.com/"))
        self.assertTrue(IG._url("me").startswith("https://graph.instagram.com/"))   # eski cagri bicimi
        with mock.patch.dict(os.environ, {"IG_HOST": "facebook"}):
            self.assertTrue(IG.is_fb_token("IGAAxyz"))
        with mock.patch.dict(os.environ, {"IG_HOST": "instagram"}):
            self.assertFalse(IG.is_fb_token(self.FB))

    def test_fb_token_publishes_through_the_facebook_host(self):
        http = Http((200, {"id": "C1"}), (200, {"status_code": "FINISHED"}),
                    (200, {"id": "M1"}), (200, {"permalink": "https://instagram.com/reel/x"}))
        res = IG.publish_reel("https://v/m.mp4", "cap", user_id="17", token=self.FB, http=http,
                              sleep=lambda s: None, log=lambda m: None)
        self.assertEqual(res["media_id"], "M1")
        self.assertEqual(len(http.calls), 4)
        for _, url, _kw in http.calls:                     # dort cagrinin dordu de facebook adresine
            self.assertTrue(url.startswith("https://graph.facebook.com/"), url)
        self.assertTrue(http.calls[0][1].endswith("/17/media"))
        self.assertTrue(http.calls[2][1].endswith("/17/media_publish"))

    def test_fb_check_reads_the_account_by_id_and_probes_publish_permission(self):
        http = Http((200, {"id": "17", "username": "byte_knows"}),
                    (200, {"data": [{"quota_usage": 0}]}))
        me = IG.check(self.FB, http, user_id="17")
        self.assertEqual(me, {"user_id": "17", "username": "byte_knows"})
        self.assertEqual(len(http.calls), 2)
        self.assertEqual(http.calls[0][0], "GET")                    # okuma: hicbir sey yayinlanmaz
        self.assertEqual(http.calls[1][0], "GET")
        self.assertTrue(http.calls[0][1].startswith("https://graph.facebook.com/17?"))
        self.assertIn("/17/content_publishing_limit", http.calls[1][1])
        self.assertNotIn("/me", http.calls[0][1])

    def test_fb_check_needs_the_user_id_and_a_good_token(self):
        with self.assertRaises(IG.IGError) as cm:
            IG.check(self.FB, Http())
        self.assertIn("INSTAGRAM_USER_ID", str(cm.exception))
        with self.assertRaises(IG.IGError) as cm:
            IG.check(self.FB, Http((400, {"error": {"message": "Invalid OAuth"}})), user_id="17")
        self.assertIn("Invalid OAuth", str(cm.exception))

    def test_fb_check_warns_but_passes_when_the_publish_probe_fails(self):
        http = Http((200, {"id": "17", "username": "byte_knows"}),
                    (400, {"error": {"message": "(#10) permission"}}))
        me = IG.check(self.FB, http, user_id="17")
        self.assertEqual(me["username"], "byte_knows")
        self.assertIn("instagram_content_publish", me["publish_note"])

    def test_fb_token_is_never_refreshed_and_main_says_so_with_exit_3(self):
        http = Http()
        with self.assertRaises(IG.NoRefresh):
            IG.refresh(self.FB, http)
        self.assertEqual(http.calls, [])                              # aga hic gitmedi
        rc, out, _ = run_main(IG, ["--refresh"], {"INSTAGRAM_TOKEN": self.FB})
        self.assertEqual(rc, 3)
        self.assertIn("yenilenmez", out)

    def test_main_dry_run_and_double_send_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            man = Path(tmp) / "manifest.json"
            man.write_text(json.dumps({"id": "vid-1", "video": "vid-1.mp4",
                                       "captions": {"instagram": "hello"}}))
            env = {"INSTAGRAM_TOKEN": "T", "INSTAGRAM_USER_ID": "17"}
            rc, out, _ = run_main(IG, [str(man), "--video-url", "https://u", "--dry-run"], env)
            self.assertEqual(rc, 0)
            self.assertIn("hello", out)
            with mock.patch.object(ledger, "ROOT", Path(tmp)):
                ledger.record("vid-1", "instagram", {"media_id": "1"})
                rc, out, _ = run_main(IG, [str(man), "--video-url", "https://u"], env)
            self.assertEqual(rc, 0)
            self.assertIn("atlandi", out)

    def test_main_without_token_or_caption_fails_clearly(self):
        rc, _, err = run_main(IG, ["--check"], {"INSTAGRAM_TOKEN": ""})
        self.assertEqual(rc, 2)
        self.assertIn("INSTAGRAM_TOKEN", err)
        with tempfile.TemporaryDirectory() as tmp:
            man = Path(tmp) / "m.json"
            man.write_text(json.dumps({"id": "v", "video": "v.mp4", "captions": {}}))
            rc, _, err = run_main(IG, [str(man), "--video-url", "https://u"],
                                  {"INSTAGRAM_TOKEN": "T", "INSTAGRAM_USER_ID": "1"})
        self.assertEqual(rc, 1)
        self.assertIn("aciklamasi yok", err)

    def test_refresh_cli_writes_the_token_to_a_private_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "tok"
            with mock.patch.object(IG, "refresh", return_value=("NEWTOKEN", 5184000)):
                rc, out, _ = run_main(IG, ["--refresh", "--out", str(f)],
                                      {"INSTAGRAM_TOKEN": "OLD"})
            self.assertEqual(rc, 0)
            self.assertEqual(f.read_text(), "NEWTOKEN")
            self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")
            self.assertNotIn("NEWTOKEN", out)             # token loga yazilmaz


# ═══ TikTok ═════════════════════════════════════════════════════════════
class TikTok(unittest.TestCase):
    def test_chunk_plan(self):
        mb = TT.MB
        self.assertEqual(TT.chunk_plan(3 * mb), (3 * mb, 1))
        self.assertEqual(TT.chunk_plan(43 * mb), (43 * mb, 1))
        self.assertEqual(TT.chunk_plan(64 * mb), (64 * mb, 1))
        chunk, total = TT.chunk_plan(100 * mb)
        self.assertEqual((chunk, total), (32 * mb, 3))        # kalan SON parcaya eklenir
        self.assertGreaterEqual(100 * mb - (total - 1) * chunk, chunk)

    def init_ok(self):
        return (200, {"data": {"publish_id": "P1", "upload_url": "https://up/x?y=1"},
                      "error": {"code": "ok"}})

    def test_single_chunk_upload_to_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "v.mp4"
            v.write_bytes(b"x" * 1000)
            http = Http(self.init_ok(), (201, {}),
                        (200, {"data": {"status": "PROCESSING_UPLOAD"}}),
                        (200, {"data": {"status": "SEND_TO_USER_INBOX"}}))
            pid = TT.upload_draft(v, "AT", http=http, sleep=lambda s: None,
                                  log=lambda m: None)
        self.assertEqual(pid, "P1")
        init, put = http.calls[0], http.calls[1]
        self.assertTrue(init[1].endswith("/v2/post/publish/inbox/video/init/"))
        self.assertEqual(init[2]["headers"]["Authorization"], "Bearer AT")
        self.assertEqual(init[2]["json_body"]["source_info"], {
            "source": "FILE_UPLOAD", "video_size": 1000,
            "chunk_size": 1000, "total_chunk_count": 1})
        self.assertEqual(put[0], "PUT")
        self.assertEqual(put[1], "https://up/x?y=1")           # sorgu parametreleriyle
        self.assertEqual(put[2]["headers"]["Content-Range"], "bytes 0-999/1000")
        self.assertEqual(put[2]["headers"]["Content-Type"], "video/mp4")
        self.assertEqual(len(put[2]["data"]), 1000)

    def test_multi_chunk_ranges_cover_every_byte_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "v.mp4"
            v.write_bytes(bytes(range(256)) * 4 + b"z" * 7)    # 1031 bayt
            with mock.patch.object(TT, "MAX_CHUNK", 400), mock.patch.object(TT, "CHUNK", 300):
                http = Http(self.init_ok(), (206, {}), (206, {}), (201, {}),
                            (200, {"data": {"status": "SEND_TO_USER_INBOX"}}))
                TT.upload_draft(v, "AT", http=http, sleep=lambda s: None,
                                log=lambda m: None)
            ranges = [c[2]["headers"]["Content-Range"] for c in http.calls if c[0] == "PUT"]
            sizes = [len(c[2]["data"]) for c in http.calls if c[0] == "PUT"]
        self.assertEqual(ranges, ["bytes 0-299/1031", "bytes 300-599/1031",
                                  "bytes 600-1030/1031"])      # son parca kalani alir
        self.assertEqual(sum(sizes), 1031)
        self.assertEqual(http.calls[0][2]["json_body"]["source_info"]["total_chunk_count"], 3)

    def test_init_rejection_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "v.mp4"
            v.write_bytes(b"x")
            http = Http((200, {"data": {}, "error": {"code": "scope_not_authorized",
                                                     "message": "no video.upload"}}))
            with self.assertRaises(TT.TikTokError) as cm:
                TT.upload_draft(v, "AT", http=http, log=lambda m: None)
        self.assertIn("scope_not_authorized", str(cm.exception))
        self.assertEqual(len(http.calls), 1)

    def test_failed_chunk_and_failed_processing_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "v.mp4"
            v.write_bytes(b"x" * 10)
            with self.assertRaises(TT.TikTokError):
                TT.upload_draft(v, "AT", http=Http(self.init_ok(), (403, {})),
                                log=lambda m: None)
            with self.assertRaises(TT.TikTokError) as cm:
                TT.upload_draft(v, "AT", http=Http(
                    self.init_ok(), (201, {}),
                    (200, {"data": {"status": "FAILED", "fail_reason": "file_format_check_failed"}})),
                    sleep=lambda s: None, log=lambda m: None)
            self.assertIn("file_format_check_failed", str(cm.exception))

    def test_never_ending_processing_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "v.mp4"
            v.write_bytes(b"x" * 10)
            http = Http(self.init_ok(), (201, {}),
                        *[(200, {"data": {"status": "PROCESSING_UPLOAD"}})] * 100)
            with self.assertRaises(TT.TikTokError):
                TT.upload_draft(v, "AT", http=http, sleep=lambda s: None,
                                poll_every=5, max_wait=20, log=lambda m: None)

    def test_refresh(self):
        http = Http((200, {"access_token": "A", "refresh_token": "R2",
                           "expires_in": 86400, "refresh_expires_in": 31536000}))
        out = TT.refresh("k", "s", "R1", http)
        self.assertEqual(out["access_token"], "A")
        form = http.calls[0][2]["form"]
        self.assertEqual((form["grant_type"], form["refresh_token"]), ("refresh_token", "R1"))
        with self.assertRaises(TT.TikTokError):
            TT.refresh("k", "s", "R1", Http((400, {"error": "invalid_grant",
                                                    "error_description": "expired"})))

    def env(self):
        return {"TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s",
                "TIKTOK_REFRESH_TOKEN": "R1"}

    def test_main_check_and_rotated_refresh_token_is_saved_not_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "new"
            tok = {"access_token": "A", "refresh_token": "R2-SECRET",
                   "refresh_expires_in": 31536000, "scope": "user.info.basic,video.upload"}
            with mock.patch.object(TT, "refresh", return_value=tok):
                rc, out, err = run_main(TT, ["--check"], {**self.env(),
                                                          "TIKTOK_NEW_REFRESH_FILE": str(f)})
            self.assertEqual(rc, 0)
            self.assertEqual(f.read_text(), "R2-SECRET")
            self.assertNotIn("R2-SECRET", out + err)
            self.assertIn("365", out)

    def test_main_requires_the_upload_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            man = Path(tmp) / "manifest.json"
            man.write_text(json.dumps({"id": "v", "video": "v.mp4"}))
            tok = {"access_token": "A", "refresh_token": "R1", "scope": "user.info.basic"}
            with mock.patch.object(TT, "refresh", return_value=tok), \
                    mock.patch.object(ledger, "ROOT", Path(tmp)):
                rc, _, err = run_main(TT, [str(man)], self.env())
        self.assertEqual(rc, 1)
        self.assertIn("video.upload", err)

    def test_main_uploads_records_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            man = Path(tmp) / "manifest.json"
            (Path(tmp) / "v.mp4").write_bytes(b"x" * 20)
            man.write_text(json.dumps({"id": "v", "video": "v.mp4"}))
            tok = {"access_token": "A", "refresh_token": "R1",
                   "scope": "user.info.basic,video.upload"}
            with mock.patch.object(TT, "refresh", return_value=tok), \
                    mock.patch.object(TT, "upload_draft", return_value="P9") as up, \
                    mock.patch.object(ledger, "ROOT", Path(tmp)):
                rc, out, _ = run_main(TT, [str(man)], self.env())
                self.assertEqual(rc, 0)
                self.assertIn("taslak hazir", out)
                self.assertTrue(ledger.done("v", "tiktok"))
                rc, out, _ = run_main(TT, [str(man)], self.env())
                self.assertIn("atlandi", out)
                self.assertEqual(up.call_count, 1)

    def test_login_helper_pkce_is_hex_sha256_and_url_has_the_scopes(self):
        import hashlib

        from tools import tiktok_login as L
        v, c = L.pkce()
        self.assertTrue(43 <= len(v) <= 128)
        self.assertEqual(c, hashlib.sha256(v.encode()).hexdigest())
        url = L.auth_url("KEY", "st", c)
        self.assertIn("video.upload", url)
        self.assertIn("127.0.0.1%3A8765%2Fcallback%2F", url)
        self.assertIn("code_challenge_method=S256", url)


# ═══ video barindirma (tools/host_video.sh) ═════════════════════════════
@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "git/bash yok")
class HostVideo(unittest.TestCase):
    def test_keeps_only_the_newest_videos_in_one_commit(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            bare = tmp / "remote.git"
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
            src = (ROOT / "tools/host_video.sh").read_text()
            src = src.replace(
                'git remote add origin "https://x-access-token:${GH_TOKEN}@github.com/${repo}.git"',
                f'git remote add origin "{bare}"')
            src = src.split('url="${base}/${id}.mp4"')[0] + 'echo "$base/${id}.mp4"\n'
            script = tmp / "h.sh"
            script.write_text(src)
            env = dict(os.environ, GITHUB_REPOSITORY="Owner/the-repo", GH_TOKEN="x",
                       MEDIA_KEEP="3")
            for n in range(1, 7):
                d = tmp / "out" / f"2026-11-0{n}-v"
                d.mkdir(parents=True, exist_ok=True)
                (d / f"2026-11-0{n}-v.mp4").write_bytes(os.urandom(500))
                r = subprocess.run(["bash", str(script), f"out/2026-11-0{n}-v"], env=env,
                                   cwd=tmp, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(),
                             "https://owner.github.io/the-repo/2026-11-06-v.mp4")
            chk = tmp / "chk"
            subprocess.run(["git", "clone", "-q", "-b", "media", str(bare), str(chk)],
                           check=True)
            mp4 = sorted(p.name for p in chk.glob("*.mp4"))
            self.assertEqual(mp4, ["2026-11-04-v.mp4", "2026-11-05-v.mp4", "2026-11-06-v.mp4"])
            self.assertTrue((chk / ".nojekyll").exists())
            n = subprocess.run(["git", "-C", str(chk), "rev-list", "--count", "HEAD"],
                               capture_output=True, text=True).stdout.strip()
            self.assertEqual(n, "1")                          # gecmis biriktirilmiyor
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
