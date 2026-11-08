import json
import unittest
from datetime import datetime, timedelta, timezone

from bytepanel.db import iso
from bytepanel.github import GitHubError
from bytepanel.service import Invalid, keys_for, parse_slots, safe_remote_url
from tests.helpers import Clock, make_service, pubs, put_result, put_video

A, B, C = "p001-tay-chatbot", "p002-gpt3-gpu", "p003-air-canada"


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


class Ingest(unittest.TestCase):
    def test_a_rendered_video_arrives_pending_and_the_inbox_record_is_consumed(self):
        svc, st, _, _ = make_service()
        put_video(st, A)
        self.assertEqual(svc.ingest_inbox(), 1)
        v = svc.video(A)
        self.assertEqual(v["approval"], "pending")
        self.assertEqual(v["video_key"], f"videos/{A}/{A}.mp4")
        self.assertFalse(st.exists(f"inbox/{A}.json"))
        self.assertEqual(svc.publications(A), [])

    def test_it_waits_when_the_files_are_not_uploaded_yet(self):
        svc, st, _, _ = make_service()
        put_video(st, A)
        st.delete(f"videos/{A}/{A}.mp4")
        self.assertEqual(svc.ingest_inbox(), 0)
        self.assertTrue(st.exists(f"inbox/{A}.json"))       # sonraki turda tekrar denenir
        self.assertEqual(svc.counts()["total"], 0)

    def test_keys_come_from_the_id_never_from_the_record(self):
        svc, st, _, _ = make_service()
        rec = put_video(st, A)
        rec["files"] = {"video": "../../etc/passwd"}
        st.put_bytes(f"inbox/{A}.json", json.dumps(rec).encode())
        svc.ingest_inbox()
        self.assertEqual(svc.video(A)["video_key"], keys_for(A)["video"])

    def test_bad_records_are_quarantined_not_ingested(self):
        svc, st, _, _ = make_service()
        bad = [
            ("../evil", {}),
            ("p9", {}),                                       # cok kisa
            ("UPPER-case", {}),
            (B, {"title": "  "}),
            (B, {"duration": 0}),
            (B, {"duration": 9999}),
            (B, {"sha256": "zz"}),
            (B, {"rendered_at": "yesterday"}),
            (B, {"v": 2}),
        ]
        for i, (sid, over) in enumerate(bad):
            rec = put_video(st, B, **over) if sid == B else put_video(st, B)
            if sid != B:
                rec["script_id"] = sid
            st.objects.pop(f"inbox/{B}.json")
            st.put_bytes(f"inbox/bad{i}.json", json.dumps(rec).encode())
        svc.ingest_inbox()
        self.assertEqual(svc.counts()["total"], 0)
        self.assertEqual(len(st.list_keys("inbox-rejected/")), len(bad))
        self.assertEqual(st.list_keys("inbox/"), [])

    def test_ids_and_hashes_with_a_trailing_newline_are_rejected(self):
        # `$` ile biten bir regex "deger\\n" de kabul ederdi
        svc, st, _, _ = make_service()
        put_video(st, A, script_id=A + "\n")
        put_video(st, B, sha256="b" * 64 + "\n")
        self.assertEqual(svc.ingest_inbox(), 0)
        self.assertEqual(svc.db.one("SELECT COUNT(*) n FROM videos")["n"], 0)
        put_video(st, C)
        svc.ingest_inbox()
        put_result(st, C, "youtube", "a" * 32 + "\n")
        self.assertEqual(svc.ingest_results(), 0)
        self.assertTrue(any(k.startswith("results-rejected/") for k in st.objects))

    def test_ingesting_twice_does_not_duplicate(self):
        svc, st, _, _ = make_service()
        put_video(st, A)
        svc.ingest_inbox()
        put_video(st, A)
        self.assertEqual(svc.ingest_inbox(), 0)
        self.assertEqual(svc.counts()["total"], 1)

    def test_control_characters_in_the_title_are_neutralised(self):
        svc, st, _, _ = make_service()
        put_video(st, A, title="Hi\x00\x1b[31m there\nline2")
        svc.ingest_inbox()
        self.assertNotRegex(svc.video(A)["title"], r"[\x00-\x1f]")

    def test_auto_approve_plans_the_enabled_platforms_at_distinct_slots(self):
        svc, st, _, _ = make_service()
        svc.set_setting("auto_approve", "1", "t")
        svc.set_setting("platform_instagram", "1", "t")
        put_video(st, A)
        put_video(st, B)
        svc.ingest_inbox()
        a, b = pubs(svc, A), pubs(svc, B)
        self.assertEqual(set(a), {"youtube", "instagram"})
        self.assertEqual(svc.video(A)["approval"], "approved")
        self.assertNotEqual(a["youtube"]["scheduled_at"], b["youtube"]["scheduled_at"])
        self.assertEqual(a["youtube"]["status"], "planned")


class Slots(unittest.TestCase):
    def test_next_slot_rules(self):
        svc, *_ = make_service()
        n = svc.next_free_slot
        self.assertEqual(n("youtube", utc(2026, 11, 8, 2, 0)), utc(2026, 11, 8, 7, 15))
        self.assertEqual(n("youtube", utc(2026, 11, 8, 19, 30)), utc(2026, 11, 9, 1, 15))
        # 2 dakikadan yakin slot kacirilir (gonderim yetismez)
        self.assertEqual(n("youtube", utc(2026, 11, 8, 7, 14)), utc(2026, 11, 8, 13, 15))

    def test_taken_slots_are_skipped_per_platform(self):
        svc, st, _, clock = make_service()
        svc.set_setting("auto_approve", "1", "t")
        put_video(st, A)
        svc.ingest_inbox()
        first = pubs(svc, A)["youtube"]["scheduled_at"]
        nxt = svc.next_free_slot("youtube", clock())
        self.assertGreater(iso(nxt), first)
        # baska platformda ayni slot bos
        self.assertEqual(iso(svc.next_free_slot("instagram", clock())), first)

    def test_slot_list_validation(self):
        self.assertEqual(parse_slots("13:15, 01:15,13:15"), ["01:15", "13:15"])
        for bad in ("", "25:00", "1:5", "ab", ",".join(f"{h:02d}:00" for h in range(24)) + ",23:30"):
            with self.assertRaises(Invalid):
                parse_slots(bad)


class Approval(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        put_video(self.st, A)
        self.svc.ingest_inbox()

    def test_approve_plans_once(self):
        self.svc.approve(A, "semih")
        self.svc.approve(A, "semih")
        self.assertEqual(list(pubs(self.svc, A)), ["youtube"])
        self.assertEqual(self.svc.video(A)["approved_by"], "semih")

    def test_reject_cancels_planned_work(self):
        self.svc.approve(A, "semih")
        self.svc.reject(A, "semih")
        self.assertEqual(self.svc.video(A)["approval"], "rejected")
        self.assertEqual(pubs(self.svc, A)["youtube"]["status"], "canceled")

    def test_unapprove_returns_to_pending_and_cancels(self):
        self.svc.approve(A, "semih")
        self.svc.unapprove(A, "semih")
        self.assertEqual(self.svc.video(A)["approval"], "pending")
        self.assertEqual(pubs(self.svc, A)["youtube"]["status"], "canceled")

    def test_unapprove_refuses_while_a_publish_is_in_flight(self):
        self.svc.approve(A, "semih")
        self.clock.set(2026, 11, 9, 8, 0)
        self.svc.dispatch_due()
        with self.assertRaises(Invalid):
            self.svc.unapprove(A, "semih")

    def test_approve_all_pending(self):
        put_video(self.st, B)
        self.svc.ingest_inbox()
        self.assertEqual(self.svc.approve_all_pending("semih"), 2)
        self.assertEqual(self.svc.counts()["pending"], 0)
        self.assertEqual(self.svc.approve_all_pending("semih"), 0)

    def test_unknown_video_is_a_clean_error(self):
        with self.assertRaises(Invalid):
            self.svc.approve("nope-nope", "semih")

    def test_plan_a_platform_later_and_no_duplicates(self):
        self.svc.approve(A, "semih")
        self.svc.plan_platform(A, "instagram", "semih")
        self.assertEqual(set(pubs(self.svc, A)), {"youtube", "instagram"})
        with self.assertRaises(Invalid):
            self.svc.plan_platform(A, "instagram", "semih")
        with self.assertRaises(Invalid):
            self.svc.plan_platform(A, "myspace", "semih")

    def test_enabling_a_platform_does_not_backfill_old_videos(self):
        self.svc.approve(A, "semih")
        self.svc.set_setting("platform_instagram", "1", "semih")
        self.assertEqual(list(pubs(self.svc, A)), ["youtube"])


class Dispatch(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        put_video(self.st, A)
        self.svc.ingest_inbox()
        self.svc.approve(A, "semih")                  # 2026-11-08 15:00 -> slot 19:15
        self.due = utc(2026, 11, 8, 19, 15)

    def test_nothing_is_sent_before_its_time(self):
        self.assertEqual(self.svc.dispatch_due(), 0)
        self.assertEqual(self.gh.calls, [])

    def test_a_due_approved_video_is_dispatched_with_the_record_written_first(self):
        seen = {}

        def probe(inputs):
            seen["status"] = pubs(self.svc, A)["youtube"]["status"]
        self.gh.on_dispatch = probe
        self.clock.t = self.due
        self.assertEqual(self.svc.dispatch_due(), 1)
        self.assertEqual(seen["status"], "dispatched")   # at-most-once: once kayit
        call = self.gh.calls[0]
        self.assertEqual((call["script_id"], call["platform"], call["privacy"]),
                         (A, "youtube", "public"))
        self.assertRegex(call["request_id"], r"^[a-f0-9]{32}$")

    def test_it_is_never_dispatched_twice(self):
        self.clock.t = self.due
        self.svc.dispatch_due()
        self.assertEqual(self.svc.dispatch_due(), 0)
        self.assertEqual(len(self.gh.calls), 1)

    def test_a_github_failure_marks_failed_and_is_not_retried_automatically(self):
        self.gh.fail = GitHubError("HTTP 500")
        self.clock.t = self.due
        self.svc.dispatch_due()
        p = pubs(self.svc, A)["youtube"]
        self.assertEqual(p["status"], "failed")
        self.assertIn("GitHub", p["error"])
        self.gh.fail = None
        self.assertEqual(self.svc.dispatch_due(), 0)

    def test_pause_stops_everything(self):
        self.svc.set_setting("paused", "1", "semih")
        self.clock.t = self.due
        self.assertEqual(self.svc.dispatch_due(), 0)
        self.svc.set_setting("paused", "0", "semih")
        self.assertEqual(self.svc.dispatch_due(), 1)

    def test_disabled_platform_waits_instead_of_being_sent(self):
        self.svc.set_setting("platform_youtube", "0", "semih")
        self.clock.t = self.due
        self.assertEqual(self.svc.dispatch_due(), 0)
        self.assertEqual(pubs(self.svc, A)["youtube"]["status"], "planned")

    def test_unapproved_or_rejected_video_is_never_dispatched(self):
        self.svc.unapprove(A, "semih")
        self.clock.t = self.due + timedelta(days=1)
        self.assertEqual(self.svc.dispatch_due(), 0)

    def test_missing_file_fails_instead_of_dispatching(self):
        self.st.delete(f"videos/{A}/{A}.mp4")
        self.clock.t = self.due
        self.svc.dispatch_due()
        self.assertEqual(pubs(self.svc, A)["youtube"]["status"], "failed")
        self.assertEqual(self.gh.calls, [])

    def test_hourly_cap_protects_against_a_runaway(self):
        svc, st, gh, clock = make_service(PANEL_MAX_DISPATCH_PER_HOUR="2")
        svc.set_setting("auto_approve", "1", "t")
        for i in range(5):
            put_video(st, f"p00{i + 1}-vid-number-{i}", rendered=f"2026-11-08T14:0{i}:00Z")
        svc.ingest_inbox()
        clock.t = utc(2026, 11, 20, 0, 0)               # hepsi gecikmis
        self.assertEqual(svc.dispatch_due(), 2)
        self.assertEqual(svc.dispatch_due(), 0)
        self.assertIn("sinir", svc.last_errors["dispatch"])
        clock.t += timedelta(hours=1, minutes=1)
        self.assertEqual(svc.dispatch_due(), 2)

    def test_timeout_marks_dispatched_as_failed_with_a_hint(self):
        self.clock.t = self.due
        self.svc.dispatch_due()
        self.clock.t += timedelta(minutes=44)
        self.assertEqual(self.svc.expire_dispatched(), 0)
        self.clock.t += timedelta(minutes=2)
        self.assertEqual(self.svc.expire_dispatched(), 1)
        p = pubs(self.svc, A)["youtube"]
        self.assertEqual(p["status"], "failed")
        self.assertIn("kontrol et", p["error"])

    def test_retry_replans_a_failed_publication_only(self):
        self.clock.t = self.due
        self.gh.fail = GitHubError("HTTP 500")
        self.svc.dispatch_due()
        pid = pubs(self.svc, A)["youtube"]["id"]
        self.svc.retry(pid, "semih")
        p = pubs(self.svc, A)["youtube"]
        self.assertEqual((p["status"], p["request_id"], p["error"]), ("planned", None, None))
        self.assertEqual(p["attempts"], 1)
        with self.assertRaises(Invalid):
            self.svc.retry(pid, "semih")                # artik 'planned'

    def test_reschedule_and_cancel_rules(self):
        pid = pubs(self.svc, A)["youtube"]["id"]
        with self.assertRaises(Invalid):
            self.svc.reschedule(pid, self.clock() - timedelta(hours=1), "s")
        with self.assertRaises(Invalid):
            self.svc.reschedule(pid, self.clock() + timedelta(days=500), "s")
        self.svc.reschedule(pid, utc(2026, 11, 9, 8, 0), "s")
        self.assertEqual(pubs(self.svc, A)["youtube"]["scheduled_at"], "2026-11-09T08:00:00Z")
        self.svc.publish_now(pid, "s")
        self.assertEqual(self.svc.dispatch_due(), 1)
        with self.assertRaises(Invalid):
            self.svc.cancel_publication(pid, "s")        # gonderilmis: iptal edilmez


class Results(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        put_video(self.st, A)
        self.svc.ingest_inbox()
        self.svc.approve(A, "semih")
        self.clock.t = utc(2026, 11, 8, 19, 15)
        self.svc.dispatch_due()
        self.rid = self.gh.calls[0]["request_id"]

    def test_a_matching_success_marks_published_with_a_safe_link(self):
        put_result(self.st, A, "youtube", self.rid)
        self.assertEqual(self.svc.ingest_results(), 1)
        p = pubs(self.svc, A)["youtube"]
        self.assertEqual((p["status"], p["remote_id"], p["remote_url"]),
                         ("published", "abc123", "https://youtu.be/abc123"))
        self.assertEqual(self.st.list_keys("results/"), [])

    def test_unsafe_links_are_dropped(self):
        for url in ("javascript:alert(1)", "http://youtu.be/x", "https://evil.example/x",
                    "https://youtube.com.evil.example/x", "data:text/html,hi"):
            self.assertEqual(safe_remote_url("youtube", url), "", url)
        self.assertEqual(safe_remote_url("instagram", "https://www.instagram.com/reel/x"),
                         "https://www.instagram.com/reel/x")
        self.assertEqual(safe_remote_url("instagram", "https://youtu.be/x"), "")

    def test_a_failure_result_keeps_the_error_text(self):
        put_result(self.st, A, "youtube", self.rid, ok=False, error="quota\x00 exceeded")
        self.svc.ingest_results()
        p = pubs(self.svc, A)["youtube"]
        self.assertEqual(p["status"], "failed")
        self.assertEqual(p["error"], "quota  exceeded")

    def test_a_result_with_the_wrong_request_id_is_quarantined(self):
        put_result(self.st, A, "youtube", "b" * 32)
        self.svc.ingest_results()
        self.assertEqual(pubs(self.svc, A)["youtube"]["status"], "dispatched")
        self.assertEqual(len(self.st.list_keys("results-orphan/")), 1)

    def test_a_replayed_result_cannot_change_a_finished_publication(self):
        put_result(self.st, A, "youtube", self.rid)
        self.svc.ingest_results()
        put_result(self.st, A, "youtube", self.rid, ok=False, error="replay")
        self.svc.ingest_results()
        self.assertEqual(pubs(self.svc, A)["youtube"]["status"], "published")
        self.assertEqual(len(self.st.list_keys("results-orphan/")), 1)

    def test_malformed_results_are_quarantined(self):
        self.st.put_bytes("results/x.json", b"{not json")
        self.st.put_bytes("results/y.json", json.dumps({"v": 1, "request_id": "short"}).encode())
        self.st.put_bytes("results/z.json", b"x" * 70000)
        self.svc.ingest_results()
        self.assertEqual(len(self.st.list_keys("results-rejected/")), 3)


class Retention(unittest.TestCase):
    def fill(self, svc, st, clock, n):
        for i in range(n):
            put_video(st, f"p{i + 1:03d}-video-{i}", rendered=f"2026-11-0{1 + i // 10}T0{i % 10}:00:00Z")
        svc.ingest_inbox()

    def test_the_oldest_files_go_when_over_the_limit_but_rows_stay(self):
        svc, st, _, clock = make_service()
        svc.set_setting("retention_count", "10", "t")
        self.fill(svc, st, clock, 12)
        svc.approve_all_pending("t")
        for p in svc.upcoming(50):
            svc.cancel_publication(p["id"], "t")         # bekleyen is yok
        gone = svc.enforce_retention()
        self.assertEqual(gone, ["p001-video-0", "p002-video-1"])
        self.assertFalse(st.exists("videos/p001-video-0/p001-video-0.mp4"))
        self.assertTrue(st.exists("videos/p003-video-2/p003-video-2.mp4"))
        self.assertEqual(svc.counts()["total"], 12)
        self.assertEqual(svc.counts()["stored"], 10)
        with self.assertRaises(Invalid):
            svc.preview_url("p001-video-0")
        with self.assertRaises(Invalid):
            svc.approve("p001-video-0", "t")

    def test_pending_and_scheduled_videos_are_never_deleted(self):
        svc, st, _, clock = make_service()
        svc.set_setting("retention_count", "10", "t")
        self.fill(svc, st, clock, 12)
        # hicbiri onaylanmadi: hepsi bekliyor -> hicbiri silinmez
        self.assertEqual(svc.enforce_retention(), [])
        # en eskisi onayli ve planli: yine silinmez, siradaki uygun olan silinir
        svc.approve("p001-video-0", "t")
        svc.reject("p002-video-1", "t")
        self.assertEqual(svc.enforce_retention(), ["p002-video-1"])
        self.assertTrue(st.exists("videos/p001-video-0/p001-video-0.mp4"))

    def test_under_the_limit_nothing_happens(self):
        svc, st, _, clock = make_service()
        self.fill(svc, st, clock, 3)
        svc.approve_all_pending("t")
        self.assertEqual(svc.enforce_retention(), [])


class Settings(unittest.TestCase):
    def test_defaults_and_validation(self):
        svc, *_ = make_service()
        self.assertEqual(svc.setting("retention_count"), "100")
        self.assertEqual(svc.enabled_platforms(), ["youtube"])
        for k, v in (("auto_approve", "yes"), ("youtube_privacy", "everyone"),
                     ("retention_count", "5"), ("retention_count", "abc"),
                     ("retention_count", "100000"), ("slots_utc", "99:99"), ("nope", "1")):
            with self.assertRaises(Invalid, msg=f"{k}={v}"):
                svc.set_setting(k, v, "t")
        svc.set_setting("slots_utc", "13:15, 01:15", "t")
        self.assertEqual(svc.setting("slots_utc"), "01:15,13:15")

    def test_changes_are_audited(self):
        svc, *_ = make_service()
        svc.set_setting("paused", "1", "semih", "1.2.3.4")
        row = svc.audit_log(1)[0]
        self.assertEqual((row["actor"], row["ip"], row["action"], row["detail"]),
                         ("semih", "1.2.3.4", "ayar", "paused=1"))


class Tick(unittest.TestCase):
    def test_a_failing_step_does_not_stop_the_others(self):
        svc, st, gh, clock = make_service()
        put_video(st, A)
        svc.ingest_inbox()
        svc.approve(A, "t")
        clock.t = utc(2026, 11, 9, 8, 0)

        def boom(*a, **k):
            raise RuntimeError("R2 down")
        st.list_keys = boom
        out = svc.tick()
        self.assertEqual(out["ice_alma"], "hata")
        self.assertIn("R2 down", svc.last_errors["ice_alma"])
        self.assertEqual(out["gonderim"], 1)               # gonderim yine de calisti


if __name__ == "__main__":
    unittest.main()
