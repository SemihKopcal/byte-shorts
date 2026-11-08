import json
import unittest

import httpx

from bytepanel.github import GitHub, GitHubError
from bytepanel.health import FAIL, OK, WARN, HealthMonitor, overall, run_checks
from bytepanel.storage import S3Storage, StorageError, TooLarge
from tests.helpers import Clock, FakeGitHub, make_service, put_video

TOKEN = "ghp_SUPERSECRET"


def gh_with(handler):
    return GitHub("o/r", TOKEN, "panel-publish.yml", "main", transport=httpx.MockTransport(handler))


class GitHubClient(unittest.TestCase):
    def test_dispatch_sends_the_expected_request(self):
        seen = {}

        def h(req):
            seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
            seen["body"] = json.loads(req.content)
            return httpx.Response(204)
        gh_with(h).dispatch({"script_id": "p001-x", "request_id": "r"})
        self.assertEqual(seen["url"],
                         "https://api.github.com/repos/o/r/actions/workflows/panel-publish.yml/dispatches")
        self.assertEqual(seen["body"], {"ref": "main", "inputs": {"script_id": "p001-x", "request_id": "r"}})
        self.assertEqual(seen["auth"], f"Bearer {TOKEN}")

    def test_errors_never_contain_the_token(self):
        for resp in (httpx.Response(404, text=TOKEN), httpx.Response(500), httpx.Response(401)):
            with self.assertRaises(GitHubError) as cm:
                gh_with(lambda req, r=resp: r).dispatch({})
            self.assertNotIn(TOKEN, str(cm.exception))

        def boom(req):
            raise httpx.ConnectError(f"cannot connect with {TOKEN}")
        with self.assertRaises(GitHubError) as cm:
            gh_with(boom).dispatch({})
        self.assertNotIn(TOKEN, str(cm.exception))

    def test_latest_run_and_ping(self):
        def h(req):
            if req.url.path.endswith("/runs"):
                return httpx.Response(200, json={"workflow_runs": [{
                    "status": "completed", "conclusion": "failure",
                    "created_at": "2026-11-08T14:34:36Z", "html_url": "https://github.com/o/r/actions/runs/1"}]})
            return httpx.Response(200, json={})
        gh = gh_with(h)
        gh.ping()
        r = gh.latest_run("daily.yml")
        self.assertEqual((r["conclusion"], r["url"]), ("failure", "https://github.com/o/r/actions/runs/1"))
        self.assertIsNone(gh_with(lambda q: httpx.Response(200, json={"workflow_runs": []})).latest_run("x.yml"))

    def test_queue_left_counts_authored_scripts_not_yet_built(self):
        def h(req):
            p = req.url.path
            if p.endswith("/contents/content/scripts"):
                return httpx.Response(200, json=[{"name": "p001-a.json"}, {"name": "p002-b.json"},
                                                 {"name": "p003-c.json"}, {"name": "2026-old.json"},
                                                 {"name": "notes.md"}])
            if p.endswith("built.json"):
                return httpx.Response(200, text='["p001-a", "something-else"]')
            if p.endswith("published.json"):
                return httpx.Response(200, text='[{"id": "p002-b", "title": "t"}]')
            return httpx.Response(404)
        self.assertEqual(gh_with(h).queue_left(), {"total": 3, "left": 1})


class FakeS3Client:
    def __init__(self):
        self.pages = []
        self.calls = []
        self.head_error = None
        self.length = 10
        self.body = b"0123456789"

    def list_objects_v2(self, **kw):
        self.calls.append(("list", kw))
        if isinstance(self.pages, Exception):
            raise self.pages
        i = 1 if kw.get("ContinuationToken") == "t1" else 0
        return self.pages[i]

    def get_object(self, **kw):
        import io
        return {"ContentLength": self.length, "Body": io.BytesIO(self.body)}

    def head_object(self, **kw):
        if self.head_error:
            raise self.head_error
        return {}

    def delete_object(self, **kw):
        self.calls.append(("delete", kw))

    def copy_object(self, **kw):
        self.calls.append(("copy", kw))

    def put_object(self, **kw):
        self.calls.append(("put", kw))

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://r2.example/{Params['Key']}?exp={ExpiresIn}"


class ClientError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class S3(unittest.TestCase):
    def setUp(self):
        self.c = FakeS3Client()
        self.s = S3Storage(self.c, "bucket")

    def test_list_follows_pagination(self):
        self.c.pages = [{"Contents": [{"Key": "a"}], "IsTruncated": True, "NextContinuationToken": "t1"},
                        {"Contents": [{"Key": "b"}], "IsTruncated": False}]
        self.assertEqual(self.s.list_keys("p/"), ["a", "b"])

    def test_big_objects_are_refused_without_reading_them(self):
        self.c.length = 10_000_000
        with self.assertRaises(TooLarge):
            self.s.get_bytes("k", 1000)
        self.c.length, self.c.body = 5, b"x" * 5000          # ContentLength yalan soyluyor
        with self.assertRaises(TooLarge):
            self.s.get_bytes("k", 1000)
        self.c.length, self.c.body = 3, b"abc"
        self.assertEqual(self.s.get_bytes("k", 1000), b"abc")

    def test_exists_distinguishes_missing_from_broken(self):
        self.assertTrue(self.s.exists("k"))
        self.c.head_error = ClientError("404")
        self.assertFalse(self.s.exists("k"))
        self.c.head_error = ClientError("403")
        with self.assertRaises(StorageError):
            self.s.exists("k")

    def test_move_copies_then_deletes_and_presign_uses_the_client(self):
        self.s.move("a", "b")
        self.assertEqual([c[0] for c in self.c.calls], ["copy", "delete"])
        self.assertIn("exp=300", self.s.presign_get("videos/x.mp4"))

    def test_ping_reports_the_error_code_only(self):
        self.c.pages = ClientError("AccessDenied")
        with self.assertRaises(StorageError) as cm:
            self.s.ping()
        self.assertEqual(str(cm.exception), "AccessDenied")


class Health(unittest.TestCase):
    def names(self, checks):
        return {c.name: c for c in checks}

    def test_everything_fine(self):
        svc, *_ = make_service()
        checks = run_checks(svc)
        self.assertEqual(overall(checks), OK)
        self.assertIn("Veritabani", self.names(checks))

    def test_queue_thresholds(self):
        svc, _, gh, _ = make_service()
        for left, want in ((0, FAIL), (3, WARN), (8, WARN), (9, OK)):
            gh.queue_left = lambda left=left: {"total": 10, "left": left}
            self.assertEqual(self.names(run_checks(svc))["Senaryo kuyrugu"].status, want, left)

    def test_a_failing_service_does_not_hide_the_rest(self):
        svc, st, gh, _ = make_service()
        gh.ping = lambda: (_ for _ in ()).throw(GitHubError("HTTP 500"))
        st.fail_ping = True
        by = self.names(run_checks(svc))
        self.assertEqual((by["GitHub"].status, by["R2 deposu"].status), (FAIL, FAIL))
        self.assertEqual(by["Veritabani"].status, OK)
        self.assertEqual(overall(list(by.values())), FAIL)

    def test_a_crashing_check_becomes_a_failure_not_an_exception(self):
        svc, _, gh, _ = make_service()
        gh.latest_run = lambda wf: (_ for _ in ()).throw(RuntimeError("boom"))
        by = self.names(run_checks(svc))
        self.assertEqual(by["Kosular"].status, FAIL)

    def test_failed_runs_show_the_link(self):
        svc, _, gh, _ = make_service()
        gh.latest_run = lambda wf: {"status": "completed", "conclusion": "failure",
                                    "created_at": "2026-11-08T14:34:36Z",
                                    "url": "https://github.com/o/r/actions/runs/9"}
        by = self.names(run_checks(svc))
        self.assertEqual(by["Uretim (daily)"].status, FAIL)
        self.assertIn("runs/9", by["Uretim (daily)"].detail)

    def test_platform_and_pause_and_pending_warnings(self):
        svc, st, gh, clock = make_service()
        put_video(st, "p001-tay-chatbot")
        svc.ingest_inbox()
        svc.approve("p001-tay-chatbot", "t")
        with svc.db.tx() as c:
            c.execute("UPDATE publications SET status='failed',finished_at=?,error='quota' ",
                      ("2026-11-08T15:00:00Z",))
        svc.set_setting("paused", "1", "t")
        by = self.names(run_checks(svc))
        self.assertEqual(by["Platform: youtube"].status, FAIL)
        self.assertIn("quota", by["Platform: youtube"].detail)
        self.assertEqual(by["Duraklatma"].status, WARN)

    def test_monitor_caches_for_a_minute(self):
        svc, *_ = make_service()
        t = [0.0]
        mon = HealthMonitor(svc, ttl=60, clock=lambda: t[0])
        calls = []
        svc.gh.ping = lambda: calls.append(1)
        mon.get()
        mon.get()
        self.assertEqual(len(calls), 1)
        t[0] = 61
        mon.get()
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
