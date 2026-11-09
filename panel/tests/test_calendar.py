"""Takvim: servis kurallari, GitHub okuma, web sayfalari ve guvenlik."""
import base64
import json
import re
import unittest
from datetime import date, datetime, timedelta, timezone

import httpx

from bytepanel import plan
from bytepanel.db import iso
from bytepanel.github import GitHubError
from bytepanel.service import AUTOFILL_MAX, Invalid
from tests.helpers import make_service, pubs, put_video
from tests.test_infra import TOKEN, gh_with
from tests.test_web import A, B, ME, Base

C = "p003-air-canada"
WEEK_ALL = "|".join(["10:15,22:15"] * 7)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def approved(svc, st, *sids):
    for sid in sids:
        put_video(st, sid, title=f"Video {sid}")
    svc.ingest_inbox()
    for sid in sids:
        svc.approve(sid, "t")


# ── ayarlar ──────────────────────────────────────────────────────────
class Settings(unittest.TestCase):
    def test_week_template_is_validated_and_normalized(self):
        svc, *_ = make_service()
        self.assertEqual(svc.week(), None)
        svc.set_setting("week_tr", "22:15, 10:15||||||", "t")
        self.assertEqual(svc.setting("week_tr"), "10:15,22:15||||||")
        self.assertEqual(svc.week()[0], ["10:15", "22:15"])
        for bad in ("x", "10:15", "25:00||||||", "|" * 7 + "|"):
            with self.assertRaises(Invalid, msg=bad):
                svc.set_setting("week_tr", bad, "t")
        self.assertEqual(svc.setting("week_tr"), "10:15,22:15||||||")        # bozuk deger kaydedilmedi

    def test_an_empty_template_means_no_template(self):
        svc, *_ = make_service()
        svc.set_setting("week_tr", "10:15||||||", "t")
        svc.set_setting("week_tr", "||||||", "t")
        self.assertEqual((svc.setting("week_tr"), svc.week()), ("", None))
        svc.set_setting("week_tr", "10:15||||||", "t")
        svc.set_setting("week_tr", "", "t")
        self.assertIsNone(svc.week())

    def test_a_corrupt_stored_template_falls_back_instead_of_breaking(self):
        svc, *_ = make_service()
        svc.db.run("INSERT INTO settings(key,value) VALUES('week_tr','garbage')")
        self.assertIsNone(svc.week())
        self.assertTrue(svc.next_free_slot("youtube", svc.now()))

    def test_run_times_are_validated_like_slots(self):
        svc, *_ = make_service()
        svc.set_setting("runs_utc", "16:15, 04:15", "t")
        self.assertEqual(svc.setting("runs_utc"), "04:15,16:15")
        for bad in ("", "25:00", "x"):
            with self.assertRaises(Invalid):
                svc.set_setting("runs_utc", bad, "t")

    def test_the_template_decides_where_new_videos_land(self):
        svc, st, _, clock = make_service()
        svc.set_setting("week_tr", WEEK_ALL, "t")
        approved(svc, st, A, B, C)
        got = [pubs(svc, s)["youtube"]["scheduled_at"] for s in (A, B, C)]
        # simdi Pazar 18:00 TR: sirayla Paz 22:15, Pzt 10:15, Pzt 22:15 (Turkiye)
        self.assertEqual(got, ["2026-11-08T19:15:00Z", "2026-11-09T07:15:00Z", "2026-11-09T19:15:00Z"])

    def test_without_a_template_the_utc_slots_still_apply(self):
        svc, st, *_ = make_service()
        approved(svc, st, A)
        self.assertEqual(pubs(svc, A)["youtube"]["scheduled_at"], "2026-11-08T19:15:00Z")


# ── onay -> takvim ───────────────────────────────────────────────────
class Revive(unittest.TestCase):
    def test_approving_again_puts_a_canceled_publication_back_on_the_calendar(self):
        svc, st, _, clock = make_service()
        approved(svc, st, A)
        svc.unapprove(A, "t")
        self.assertEqual(pubs(svc, A)["youtube"]["status"], "canceled")
        clock.t += timedelta(hours=6)
        svc.approve(A, "t")
        p = pubs(svc, A)["youtube"]
        self.assertEqual(p["status"], "planned")
        self.assertGreater(p["scheduled_at"], iso(clock()))
        self.assertEqual(len(svc.publications(A)), 1)             # ayni satir: UNIQUE bozulmadi

    def test_approving_twice_never_touches_live_rows(self):
        svc, st, *_ = make_service()
        approved(svc, st, A)
        before = pubs(svc, A)["youtube"]
        svc.approve(A, "t")
        self.assertEqual(pubs(svc, A)["youtube"], before)


# ── elle planlama ────────────────────────────────────────────────────
class PlanAt(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        approved(self.svc, self.st, A, B)
        self.mon = utc(2026, 11, 9, 7, 15)                       # Pzt 10:15 TR
        for sid in (A, B):                                       # otomatik yerlesimi kaldir
            self.svc.cancel_publication(pubs(self.svc, sid)["youtube"]["id"], "t")

    def audit_actions(self):
        return [r["action"] for r in self.svc.audit_log(50)]

    def test_plans_a_video_for_the_chosen_time_and_audits_it(self):
        self.svc.plan_at(A, "youtube", self.mon, "semih", "1.2.3.4")
        p = pubs(self.svc, A)["youtube"]
        self.assertEqual((p["status"], p["scheduled_at"]), ("planned", "2026-11-09T07:15:00Z"))
        self.assertIn("yayin planlandi (takvim)", self.audit_actions())

    def test_it_creates_a_row_when_there_was_none(self):
        svc, st, *_ = make_service()
        approved(svc, st, A)
        svc.set_setting("platform_instagram", "1", "t")           # instagram sonradan acildi
        self.assertNotIn("instagram", pubs(svc, A))
        svc.plan_at(A, "instagram", self.mon, "t")
        self.assertEqual(pubs(svc, A)["instagram"]["scheduled_at"], "2026-11-09T07:15:00Z")

    def test_rules(self):
        svc = self.svc
        svc.set_setting("platform_instagram", "0", "t")
        with self.assertRaises(Invalid):
            svc.plan_at(A, "instagram", self.mon, "t")              # platform kapali
        with self.assertRaises(Invalid):
            svc.plan_at(A, "mastodon", self.mon, "t")               # bilinmeyen platform
        with self.assertRaises(Invalid):
            svc.plan_at("p999-nope", "youtube", self.mon, "t")      # video yok
        with self.assertRaises(Invalid):
            svc.plan_at(A, "youtube", self.clock() - timedelta(hours=2), "t")      # gecmis
        with self.assertRaises(Invalid):
            svc.plan_at(A, "youtube", self.clock() + timedelta(days=401), "t")     # cok uzak
        svc.unapprove(B, "t")
        with self.assertRaises(Invalid):
            svc.plan_at(B, "youtube", self.mon, "t")                # onaysiz
        svc.approve(A, "t")                                         # (A iptal satiri yeniden planlandi)
        with self.assertRaises(Invalid):
            svc.plan_at(A, "youtube", self.mon + timedelta(days=1), "t")   # zaten planli

    def test_the_same_platform_cannot_have_two_videos_at_one_minute(self):
        self.svc.plan_at(A, "youtube", self.mon, "t")
        with self.assertRaises(Invalid) as cm:
            self.svc.plan_at(B, "youtube", self.mon, "t")
        self.assertIn("baska bir yayin", str(cm.exception))
        self.svc.plan_at(B, "youtube", self.mon + timedelta(minutes=1), "t")

    def test_deleted_files_block_planning(self):
        self.svc.db.run("UPDATE videos SET files_deleted_at='2026-11-01T00:00:00Z' WHERE script_id=?", (A,))
        with self.assertRaises(Invalid):
            self.svc.plan_at(A, "youtube", self.mon, "t")

    def test_failed_rows_can_be_planned_again_and_published_ones_cannot(self):
        svc = self.svc
        pid = pubs(svc, A)["youtube"]["id"]
        svc.db.run("UPDATE publications SET status='failed',error='x',attempts=1 WHERE id=?", (pid,))
        svc.plan_at(A, "youtube", self.mon, "t")
        p = pubs(svc, A)["youtube"]
        self.assertEqual((p["id"], p["status"], p["error"]), (pid, "planned", None))
        svc.db.run("UPDATE publications SET status='published' WHERE id=?", (pid,))
        with self.assertRaises(Invalid):
            svc.plan_at(A, "youtube", self.mon + timedelta(days=2), "t")


# ── tasima / zaman degistirme ────────────────────────────────────────
class Move(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        approved(self.svc, self.st, A, B)
        self.pa = pubs(self.svc, A)["youtube"]["id"]
        self.pb = pubs(self.svc, B)["youtube"]["id"]
        self.svc.reschedule(self.pa, utc(2026, 11, 9, 7, 15), "t")      # Pzt 10:15 TR
        self.svc.reschedule(self.pb, utc(2026, 11, 9, 19, 15), "t")     # Pzt 22:15 TR

    def at(self, pid):
        return self.svc.db.one("SELECT scheduled_at FROM publications WHERE id=?", (pid,))["scheduled_at"]

    def test_dragging_keeps_the_turkey_time_of_day(self):
        self.svc.move_pub(self.pb, date(2026, 11, 11), "t")
        self.assertEqual(self.at(self.pb), "2026-11-11T19:15:00Z")      # Car 22:15 TR
        self.svc.reschedule(self.pb, utc(2026, 11, 9, 21, 30), "t")     # Pzt 00:30'dan sonra: TR 10 Kasim 00:30
        self.svc.move_pub(self.pb, date(2026, 11, 12), "t")
        self.assertEqual(self.at(self.pb), "2026-11-11T21:30:00Z")      # TR 12 Kasim 00:30

    def test_refusals(self):
        with self.assertRaises(Invalid):
            self.svc.move_pub(self.pa, date(2026, 11, 7), "t")          # gecmis gun
        with self.assertRaises(Invalid):
            self.svc.move_pub(self.pa, date(2026, 11, 8), "t")          # bugun ama 10:15 TR gecmis
        with self.assertRaises(Invalid):
            self.svc.move_pub(self.pa, date(2029, 1, 1), "t")           # cok uzak
        with self.assertRaises(Invalid):
            self.svc.move_pub(9999, date(2026, 11, 12), "t")            # yok
        self.assertEqual(self.at(self.pa), "2026-11-09T07:15:00Z")

    def test_a_dispatched_or_published_publication_cannot_be_moved(self):
        for status in ("dispatched", "published", "failed", "canceled"):
            self.svc.db.run("UPDATE publications SET status=? WHERE id=?", (status, self.pa))
            with self.assertRaises(Invalid, msg=status):
                self.svc.move_pub(self.pa, date(2026, 11, 12), "t")

    def test_two_publications_cannot_collide_on_one_platform(self):
        self.svc.reschedule(self.pb, utc(2026, 11, 10, 7, 15), "t")     # Sal 10:15 TR
        with self.assertRaises(Invalid):
            self.svc.move_pub(self.pb, date(2026, 11, 9), "t")          # Pzt 10:15 TR: A orada
        with self.assertRaises(Invalid):
            self.svc.reschedule(self.pb, utc(2026, 11, 9, 7, 15), "t")
        self.svc.reschedule(self.pa, utc(2026, 11, 9, 7, 15), "t")      # kendi saatine tasimak sorun degil

    def test_publish_now_never_trips_the_collision_check(self):
        self.svc.publish_now(self.pa, "t")
        self.svc.publish_now(self.pb, "t")
        self.assertEqual(self.at(self.pa), self.at(self.pb))


# ── otomatik doldur ──────────────────────────────────────────────────
class Autofill(unittest.TestCase):
    def test_places_approved_videos_that_have_no_calendar_row(self):
        svc, st, _, clock = make_service()
        approved(svc, st, A, B)
        put_video(st, C)
        svc.ingest_inbox()                                           # C onay bekliyor
        svc.set_setting("platform_instagram", "1", "t")
        self.assertEqual(svc.autofill_count(), 2)                    # (A, B) x instagram
        self.assertEqual(svc.autofill("semih", "1.1.1.1"), 2)
        a, b = pubs(svc, A)["instagram"], pubs(svc, B)["instagram"]
        self.assertEqual((a["status"], b["status"]), ("planned", "planned"))
        self.assertLess(a["scheduled_at"], b["scheduled_at"])        # eski video once
        self.assertNotIn("instagram", pubs(svc, C))                  # onaysiz video dizilmez
        self.assertEqual(svc.autofill("semih"), 0)                   # ikinci kez bir sey yapmaz
        self.assertIn("otomatik dolduruldu", [r["action"] for r in svc.audit_log(20)])

    def test_canceled_failed_and_published_rows_are_left_alone(self):
        svc, st, *_ = make_service()
        approved(svc, st, A, B, C)
        ids = {s: pubs(svc, s)["youtube"]["id"] for s in (A, B, C)}
        svc.db.run("UPDATE publications SET status='canceled' WHERE id=?", (ids[A],))
        svc.db.run("UPDATE publications SET status='failed' WHERE id=?", (ids[B],))
        svc.db.run("UPDATE publications SET status='published' WHERE id=?", (ids[C],))
        self.assertEqual(svc.autofill_count(), 0)
        self.assertEqual(svc.autofill("t"), 0)

    def test_one_run_places_at_most_the_cap_and_the_rest_next_time(self):
        svc, st, *_ = make_service()
        svc.set_setting("platform_youtube", "0", "t")
        sids = [f"p{n:03d}-bulk-{n}" for n in range(AUTOFILL_MAX + 5)]
        approved(svc, st, *sids)
        self.assertEqual(svc.counts()["planned"], 0)
        svc.set_setting("platform_youtube", "1", "t")
        self.assertEqual(svc.autofill_count(), AUTOFILL_MAX)
        self.assertEqual(svc.autofill("t"), AUTOFILL_MAX)
        self.assertEqual(svc.autofill("t"), 5)
        self.assertEqual(svc.autofill("t"), 0)
        slots = [r["scheduled_at"] for r in svc.db.all("SELECT scheduled_at FROM publications")]
        self.assertEqual(len(slots), len(set(slots)))                # hicbiri ayni saate dusmedi

    def test_deleted_files_are_not_placed(self):
        svc, st, *_ = make_service()
        svc.set_setting("platform_youtube", "0", "t")
        approved(svc, st, A)
        svc.db.run("UPDATE videos SET files_deleted_at='2026-11-01T00:00:00Z'")
        svc.set_setting("platform_youtube", "1", "t")
        self.assertEqual(svc.autofill("t"), 0)


# ── GitHub'dan gelen bilgi ───────────────────────────────────────────
class Extras(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        self.calls = 0
        real = self.gh.queue_info

        def counted():
            self.calls += 1
            return real()
        self.gh.queue_info = counted

    def test_result_is_cached_for_five_minutes(self):
        e = self.svc.extras()
        self.assertTrue(e["ok"])
        self.assertEqual(len(e["queue"]), 9)
        self.svc.extras()
        self.assertEqual(self.calls, 1)
        self.clock.t += timedelta(seconds=301)
        self.svc.extras()
        self.assertEqual(self.calls, 2)

    def test_a_github_failure_never_breaks_the_calendar_and_retries_soon(self):
        self.gh.fail_queue = GitHubError("HTTP 500 /repos/o/r")
        e = self.svc.extras()
        self.assertEqual((e["ok"], e["queue"]), (False, []))
        self.assertIn("kuyruk", e["error"])
        self.assertTrue(self.svc.month_model(2026, 11, e))           # model yine uretilir
        self.svc.extras()
        self.assertEqual(self.calls, 1)                              # 1 dk icinde tekrar vurmaz
        self.gh.fail_queue = None
        self.clock.t += timedelta(seconds=61)
        self.assertTrue(self.svc.extras()["ok"])

    def test_any_unexpected_error_is_contained_too(self):
        self.gh.fail_queue = KeyError("queue")
        self.assertFalse(self.svc.extras()["ok"])
        self.clock.t += timedelta(seconds=61)
        self.gh.fail_queue = None
        self.gh.experiments = lambda: 1 / 0
        e = self.svc.extras()
        self.assertTrue(e["ok"])
        self.assertIn("deney", e["error"])

    def test_queue_summary(self):
        e = self.svc.extras()
        s = self.svc.queue_summary(e)                                # 9 senaryo, gunde 2 uretim
        self.assertEqual((s["left"], s["per_day"], s["days"], s["warn"]), (9, 2, 5, True))
        self.assertEqual(s["next_id"], "p040-sira-40")
        self.assertEqual(s["next_run"], "08.11 19:15")               # 16:15 UTC = 19:15 TR
        self.assertEqual(s["last_run"], "12.11 19:15")               # 9. uretim
        self.gh.queue = [f"p{n:03d}-q-{n}" for n in range(100, 140)]
        self.clock.t += timedelta(minutes=6)
        s = self.svc.queue_summary(self.svc.extras())
        self.assertEqual((s["left"], s["days"], s["warn"]), (40, 20, False))
        self.svc.set_setting("runs_utc", "04:15", "t")
        self.assertEqual(self.svc.queue_summary(self.svc.extras())["days"], 40)

    def test_an_unreadable_queue_is_unknown_not_empty(self):
        self.gh.fail_queue = GitHubError("HTTP 500")
        s = self.svc.queue_summary(self.svc.extras())
        self.assertEqual((s["known"], s["warn"], s["last_run"]), (False, False, ""))

    def test_an_exhausted_queue_warns(self):
        self.gh.queue = []
        s = self.svc.queue_summary(self.svc.extras())
        self.assertEqual((s["known"], s["left"], s["warn"]), (True, 0, True))


class Models(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        self.gh.arm_info = {A: {"name": "short", "label": "K", "n": 1, "exp": "e1"}}
        approved(self.svc, self.st, A, B)
        self.pa = pubs(self.svc, A)["youtube"]["id"]
        self.pb = pubs(self.svc, B)["youtube"]["id"]

    def cells(self, mm):
        return {c["iso"]: c for w in mm["weeks"] for c in w}

    def test_month_shows_publications_production_and_the_ab_arm(self):
        self.svc.reschedule(self.pa, utc(2026, 11, 9, 7, 15), "t")
        mm = self.svc.month_model(2026, 11, self.svc.extras())
        pubs_on = [e for e in self.cells(mm)["2026-11-09"]["events"]
                   if e["kind"] == "pub" and e["script_id"] == A]
        self.assertEqual([(e["script_id"], e["hhmm"], e["arm"]) for e in pubs_on], [(A, "10:15", "K")])
        made = [e for e in self.cells(mm)["2026-11-08"]["events"] if e["kind"] == "made"]
        self.assertEqual({e["script_id"] for e in made}, {A, B})     # put_video: 2026-11-08 14:37 UTC
        runs = [e for c in self.cells(mm).values() for e in c["events"] if e["kind"] == "run"]
        self.assertEqual(runs[0]["script_id"], "p040-sira-40")
        self.assertTrue(all(e["hhmm"] in ("07:15", "19:15") for e in runs))

    def test_canceled_are_hidden_in_the_month_but_listed_on_the_day(self):
        self.svc.reschedule(self.pb, utc(2026, 11, 10, 7, 15), "t")
        self.svc.cancel_publication(self.pb, "t")
        extras = self.svc.extras()
        month = self.cells(self.svc.month_model(2026, 11, extras))
        self.assertFalse([e for e in month["2026-11-10"]["events"] if e["kind"] == "pub"])
        day = self.svc.day_model(date(2026, 11, 10), extras)
        self.assertEqual([c["script_id"] for c in day["canceled"]], [B])

    def test_past_runs_are_not_predicted(self):
        mm = self.svc.month_model(2026, 11, self.svc.extras())
        early = [e for e in self.cells(mm)["2026-11-03"]["events"] if e["kind"] == "run"]
        self.assertEqual(early, [])

    def test_day_options_list_only_videos_that_can_still_be_planned(self):
        extras = self.svc.extras()
        self.assertEqual(self.svc.day_model(date(2026, 11, 12), extras)["options"], [])   # ikisi de planli
        self.svc.cancel_publication(self.pb, "t")
        opts = self.svc.day_model(date(2026, 11, 12), extras)["options"]
        self.assertEqual([o["value"] for o in opts], [f"{B}:youtube"])
        self.svc.set_setting("platform_youtube", "0", "t")
        self.assertEqual(self.svc.day_model(date(2026, 11, 12), extras)["options"], [])   # kapali platform

    def test_day_model_basics(self):
        self.svc.set_setting("week_tr", WEEK_ALL, "t")
        d = self.svc.day_model(date(2026, 11, 9), self.svc.extras())
        self.assertEqual((d["iso"], d["prev"], d["next"], d["month"]), ("2026-11-09", "2026-11-08", "2026-11-10", "2026-11"))
        self.assertEqual(d["times"], ["10:15", "22:15"])
        self.assertFalse(d["past"])
        self.assertTrue(self.svc.day_model(date(2026, 11, 7), self.svc.extras())["past"])
        self.assertTrue(self.svc.day_model(date(2026, 11, 8), self.svc.extras())["today"])

    def test_week_rows_for_the_template_form(self):
        rows = self.svc.week_rows()
        self.assertEqual([r["name"] for r in rows], list(plan.WEEKDAYS))
        self.assertEqual(rows[0]["value"], "04:15, 10:15, 16:15, 22:15")   # UTC saatlerinin TR karsiligi
        self.svc.set_setting("week_tr", "09:00|||||12:00|", "t")
        rows = self.svc.week_rows()
        self.assertEqual((rows[0]["value"], rows[1]["value"], rows[5]["value"]), ("09:00", "", "12:00"))


# ── GitHub istemcisi ─────────────────────────────────────────────────
class GitHubReads(unittest.TestCase):
    def handler(self, order=None, experiments=None, built='["p001-a"]', published="[]", status=None):
        def h(req):
            p = req.url.path
            if status:
                return httpx.Response(status, text=TOKEN)
            if p.endswith("/contents/content/scripts"):
                return httpx.Response(200, json=[{"name": n} for n in
                                                 ("p001-a.json", "p002-b.json", "p003-c.json", "p004-d.json", "README.md")])
            if p.endswith("built.json"):
                return httpx.Response(200, text=built)
            if p.endswith("published.json"):
                return httpx.Response(200, text=published)
            if p.endswith("order.json") and order is not None:
                return httpx.Response(200, text=order)
            if p.endswith("experiments.json") and experiments is not None:
                return httpx.Response(200, text=experiments)
            return httpx.Response(404)
        return h

    def test_the_queue_follows_order_json_then_file_order(self):
        gh = gh_with(self.handler(order='["p004-d", "p001-a", "p003-c", 7]'))
        self.assertEqual(gh.queue_info(), {"total": 4, "queue": ["p004-d", "p003-c", "p002-b"]})

    def test_a_missing_or_broken_order_file_changes_nothing(self):
        for order in (None, "not json", '{"a": 1}'):
            gh = gh_with(self.handler(order=order))
            self.assertEqual(gh.queue_info()["queue"], ["p002-b", "p003-c", "p004-d"], order)

    def test_published_ids_count_as_done_in_either_shape(self):
        gh = gh_with(self.handler(published='[{"id": "p002-b", "title": "t"}, "p003-c"]'))
        self.assertEqual(gh.queue_info()["queue"], ["p004-d"])

    def test_queue_left_agrees_with_the_queue(self):
        gh = gh_with(self.handler(order='["p004-d"]'))
        self.assertEqual(gh.queue_left()["left"], len(gh.queue_info()["queue"]))

    def test_failures_become_github_errors_without_the_token(self):
        for call in ("queue_info", "queue_left"):
            with self.assertRaises(GitHubError) as cm:
                getattr(gh_with(self.handler(status=500)), call)()
            self.assertNotIn(TOKEN, str(cm.exception))

    def test_experiments_are_parsed_and_sanitized(self):
        data = {"e1-length": {"title": "Kisa <b>mi</b>?", "arms": {
                    "short": ["p001-a", "p002-b", "../etc", 5, "P1", "x"],
                    "standard": ["p003-c", "p001-a"]}},
                "bad": "nope", "e2": {"arms": "nope"}}
        out = gh_with(self.handler(experiments=json.dumps(data))).experiments()
        self.assertEqual(out["arm_info"]["p001-a"], {"name": "short", "label": "K", "n": 1, "exp": "e1-length"})
        self.assertEqual(out["arm_info"]["p003-c"]["label"], "S")
        for junk in ("../etc", "P1", "x", 5):
            self.assertNotIn(junk, out["arm_info"])
        self.assertEqual(len(out["legend"]), 1)
        self.assertEqual([a["label"] for a in out["legend"][0]["arms"]], ["K", "S"])

    def test_arm_names_cannot_smuggle_markup(self):
        data = {"e": {"arms": {'a"><script>': ["p001-a"], "x" * 90: ["p002-b"]}}}
        out = gh_with(self.handler(experiments=json.dumps(data))).experiments()
        for info in out["arm_info"].values():
            self.assertRegex(info["name"], r"^[A-Za-z0-9_-]{1,20}$")

    def test_no_experiments_file_is_just_empty(self):
        self.assertEqual(gh_with(self.handler()).experiments(), {"arm_info": {}, "legend": []})
        self.assertEqual(gh_with(self.handler(experiments="[1,2]")).experiments(), {"arm_info": {}, "legend": []})


# ── web ──────────────────────────────────────────────────────────────
def flash_of(r) -> str:
    raw = r.cookies.get("flash") or ""
    return base64.urlsafe_b64decode(raw.encode()).decode() if raw else ""


class Pages(Base):
    def test_month_page(self):
        self.add(A)
        self.add(B)
        self.svc.approve(A, ME)
        r = self.get("/calendar")
        self.assertEqual(r.status_code, 200)
        for want in ("Kasim 2026", "Kuyruk: 9 senaryo", 'href="/calendar?m=2026-12"', 'href="/calendar?m=2026-10"',
                     'data-day="2026-11-08"', 'action="/calendar/move"', "Planlama araclari",
                     'href="/calendar?view=list"'):
            self.assertIn(want, r.text, want)

    def test_planned_chips_are_draggable_and_other_states_are_not(self):
        self.add(A)
        self.svc.approve(A, ME)
        body = self.get("/calendar").text
        self.assertRegex(body, r'draggable="true" data-pub="\d+"')
        pid = self.svc.publications(A)[0]["id"]
        self.svc.db.run("UPDATE publications SET status='published' WHERE id=?", (pid,))
        self.assertNotIn("draggable", self.get("/calendar").text)

    def test_past_days_are_not_drop_targets(self):
        body = self.get("/calendar").text
        self.assertRegex(body, r'class="cell[^"]*\bpast\b[^"]*" data-day="2026-11-07">')
        self.assertNotRegex(body, r'\bpast\b[^>]*data-day="2026-11-07"[^>]*data-drop')
        self.assertRegex(body, r'data-day="2026-11-09" data-drop="1"')

    def test_other_months_and_the_day_page(self):
        self.assertEqual(self.get("/calendar?m=2027-01").status_code, 200)
        self.assertIn("Ocak 2027", self.get("/calendar?m=2027-01").text)
        r = self.get("/calendar?d=2026-11-10")
        self.assertEqual(r.status_code, 200)
        self.assertIn("10 Kasim 2026", r.text)
        self.assertIn("Plana ekle", r.text)

    def test_bad_month_or_day_redirects_back_with_a_message(self):
        for q in ("m=2026-13", "m=abc", "m=1990-01", "d=2026-02-31", "d=x", "d=2099-01-01", "m=2026-1"):
            r = self.get(f"/calendar?{q}")
            self.assertEqual((r.status_code, r.headers["location"]), (303, "/calendar"), q)

    def test_list_view_shows_turkey_time_in_the_move_box(self):
        self.add(A)
        self.svc.approve(A, ME)
        body = self.get("/calendar?view=list").text
        self.assertIn('value="2026-11-08 22:15"', body)               # 19:15 UTC
        self.assertIn('name="view" value="list"', body)

    def test_queue_failure_still_renders_the_calendar(self):
        self.svc.gh.fail_queue = GitHubError("HTTP 500 /x")
        self.add(A)
        self.svc.approve(A, ME)
        r = self.get("/calendar")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Kuyruk bilgisi alinamadi", r.text)
        self.assertIn("data-pub=", r.text)                            # planlar yine orada
        self.assertEqual(self.get("/calendar?d=2026-11-08").status_code, 200)

    def test_titles_are_escaped_in_every_calendar_view(self):
        evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
        self.add(A, title=evil)
        self.svc.approve(A, ME)
        self.svc.gh.legend = [{"name": "e", "title": evil, "arms": [{"name": "a<b", "label": "<K>", "n": 1}]}]
        self.svc.gh.arm_info = {A: {"name": "a<b", "label": "<K>", "n": 1, "exp": "e"}}
        self.svc.cancel_publication(self.svc.publications(A)[0]["id"], ME)
        self.svc.plan_at(A, "youtube", datetime(2026, 11, 9, 7, 15, tzinfo=timezone.utc), ME)
        for p in ("/calendar", "/calendar?d=2026-11-09", "/calendar?view=list"):
            body = self.get(p).text
            self.assertNotIn("<script>alert(1)", body, p)
            self.assertNotIn("<img src=x", body, p)
            self.assertNotIn("<K>", body, p)
        self.assertIn("&lt;script&gt;alert(1)", self.get("/calendar?d=2026-11-09").text)

    def test_unsafe_remote_links_are_not_rendered_as_links(self):
        self.add(A)
        self.svc.approve(A, ME)
        pid = self.svc.publications(A)[0]["id"]
        self.svc.db.run("UPDATE publications SET status='published',remote_url=? WHERE id=?",
                        ("javascript:alert(1)", pid))
        self.assertNotIn("javascript:", self.get("/calendar?d=2026-11-08").text)

    def test_no_calendar_page_has_inline_script_style_or_handlers(self):
        self.add(A)
        self.svc.approve(A, ME)
        for p in ("/calendar", "/calendar?m=2026-12", "/calendar?d=2026-11-08", "/calendar?view=list", "/settings"):
            body = self.get(p).text
            self.assertNotRegex(body, r"<script(?![^>]*\bsrc=)", p)
            self.assertNotRegex(body, r"\son\w+=", p)
            self.assertNotRegex(body, r"\sstyle=", p)
            self.assertNotIn("<style", body, p)

    def test_settings_page_has_the_new_fields(self):
        body = self.get("/settings").text
        self.assertIn('name="value" value="04:15,16:15"', body)
        self.post("/settings", {"key": "runs_utc", "value": "05:00"})
        self.assertEqual(self.svc.setting("runs_utc"), "05:00")


class Actions(Base):
    def setUp(self):
        super().setUp()
        self.add(A)
        self.add(B)
        self.svc.approve(A, ME)
        self.svc.approve(B, ME)
        self.pa = self.svc.publications(A)[0]["id"]
        self.pb = self.svc.publications(B)[0]["id"]

    def at(self, pid):
        return self.svc.db.one("SELECT scheduled_at FROM publications WHERE id=?", (pid,))["scheduled_at"]

    def test_plan_from_the_day_page(self):
        self.svc.cancel_publication(self.pa, ME)
        r = self.post("/calendar/plan", {"choice": f"{A}:youtube", "d": "2026-11-11", "time": "10:15"})
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/calendar?d=2026-11-11"))
        self.assertEqual(flash_of(r), "Takvime eklendi.")
        self.assertEqual(self.at(self.pa), "2026-11-11T07:15:00Z")         # Turkiye saati girildi

    def test_plan_errors_come_back_as_messages(self):
        cases = [({"choice": "nope", "d": "2026-11-11", "time": "10:15"}, "video"),
                 ({"choice": f"{A}:youtube", "d": "2026-11-11", "time": "25:00"}, "Saat"),
                 ({"choice": f"{A}:youtube", "d": "2026-02-31", "time": "10:15"}, "Gecersiz tarih"),
                 ({"choice": f"{A}:youtube", "d": "2026-11-11", "time": "10:15"}, "zaten var"),
                 ({"choice": f"{A}:youtube", "d": "2026-11-01", "time": "10:15"}, "gecmis"),
                 ({"choice": f"{A}:nope", "d": "2026-11-11", "time": "10:15"}, "platform"),
                 ({"d": "2026-11-11", "time": "10:15"}, "video secilmedi")]
        for data, want in cases:
            r = self.post("/calendar/plan", data)
            self.assertEqual(r.status_code, 303, data)
            self.assertTrue(flash_of(r).startswith("Hata:"), (data, flash_of(r)))
            self.assertIn(want, flash_of(r), data)

    def test_dragging_moves_the_day_and_keeps_the_time(self):
        before = self.at(self.pb)
        r = self.post("/calendar/move", {"pub": str(self.pb), "d": "2026-11-20", "m": "2026-11"})
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/calendar?m=2026-11"))
        was, now = plan.to_tr(utc(*map(int, re.findall(r"\d+", before)))), \
            plan.to_tr(utc(*map(int, re.findall(r"\d+", self.at(self.pb)))))
        self.assertEqual((now.date(), f"{now:%H:%M}"), (date(2026, 11, 20), f"{was:%H:%M}"))

    def test_move_refusals(self):
        before = (self.at(self.pa), self.at(self.pb))
        for data in ({"pub": "x", "d": "2026-11-20"}, {"pub": "", "d": "2026-11-20"}, {"pub": "99999", "d": "2026-11-20"},
                     {"pub": str(self.pa), "d": "2026-11-01"}, {"pub": str(self.pa), "d": "nope"},
                     {"pub": "-1", "d": "2026-11-20"}, {"pub": "1" * 30, "d": "2026-11-20"},
                     {"pub": "\u00b2", "d": "2026-11-20"}, {"pub": "\u0663", "d": "2026-11-20"},
                     {"pub": str(self.pa), "d": "\uff12\uff10\uff12\uff16-11-20"},
                     {"pub": str(self.pa)}):
            r = self.post("/calendar/move", {**data, "m": "2026-11"})
            self.assertEqual(r.status_code, 303, data)
            self.assertTrue(flash_of(r).startswith("Hata:"), (data, flash_of(r)))
        self.assertEqual((self.at(self.pa), self.at(self.pb)), before)

    def test_autofill(self):
        self.svc.set_setting("platform_instagram", "1", ME)
        r = self.post("/calendar/autofill", {"m": "2026-11"})
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/calendar?m=2026-11"))
        self.assertEqual(flash_of(r), "2 yayin bos saatlere dizildi.")
        self.assertEqual(flash_of(self.post("/calendar/autofill", {"m": "2026-11"})), "Dizilecek video yok.")

    def test_autofill_button_shows_the_count_only_when_there_is_work(self):
        self.assertIn("Takvimde yeri olmayan onayli video yok", self.get("/calendar").text)
        self.svc.set_setting("platform_instagram", "1", ME)
        body = self.get("/calendar").text
        self.assertIn("Otomatik doldur (2)", body)
        self.assertIn('data-confirm="Takvimde yeri olmayan 2 yayin', body)

    def test_template_save_and_clear(self):
        data = {f"d{i}": "10:15, 22:15" for i in range(7)}
        r = self.post("/calendar/template", {**data, "m": "2026-11"})
        self.assertEqual(flash_of(r), "Haftalik sablon kaydedildi.")
        self.assertEqual(self.svc.setting("week_tr"), WEEK_ALL)
        body = self.get("/calendar").text
        self.assertIn('name="d0" value="10:15, 22:15"', body)
        self.assertIn("Sablonu kapat", body)
        r = self.post("/calendar/template", {"clear": "1", "m": "2026-11"})
        self.assertIn("kapatildi", flash_of(r))
        self.assertEqual(self.svc.setting("week_tr"), "")

    def test_template_errors_are_reported_and_nothing_is_saved(self):
        for bad in ({"d0": "25:00"}, {"d0": "10:15|", "d1": ""}, {"d0": "a|b|c|d|e|f|g"},
                    {"d0": ",".join(f"{h:02d}:00" for h in range(9))}):
            r = self.post("/calendar/template", bad)
            self.assertTrue(flash_of(r).startswith("Hata:"), (bad, flash_of(r)))
        self.assertEqual(self.svc.setting("week_tr"), "")

    def test_an_all_blank_template_form_turns_the_template_off(self):
        self.svc.set_setting("week_tr", WEEK_ALL, ME)
        self.post("/calendar/template", {})
        self.assertEqual(self.svc.setting("week_tr"), "")

    def test_existing_row_buttons_return_to_the_page_they_came_from(self):
        r = self.post(f"/pubs/{self.pa}/cancel", {"d": "2026-11-08"})
        self.assertEqual(r.headers["location"], "/calendar?d=2026-11-08")
        r = self.post(f"/pubs/{self.pb}/reschedule", {"when": "2026-11-15 10:15", "d": "2026-11-15"})
        self.assertEqual(r.headers["location"], "/calendar?d=2026-11-15")
        self.assertEqual(self.at(self.pb), "2026-11-15T07:15:00Z")
        r = self.post(f"/pubs/{self.pb}/now", {"view": "list"})
        self.assertEqual(r.headers["location"], "/calendar?view=list")
        self.assertEqual(self.post(f"/pubs/{self.pb}/now").headers["location"], "/calendar")


class BackAddress(Base):
    """Donus adresi formdan gelir ama ASLA ham haliyle kullanilmaz."""

    def test_only_well_formed_dates_survive_as_the_redirect_target(self):
        evil = ["https://evil.example/", "//evil.example", "/settings", "2026-11-09\r\nSet-Cookie: x=1",
                "\uff12\uff10\uff12\uff16-11-09", "\uff12\uff10\uff12\uff16-11",
                "2026-11-09\n", "2026-11\n", "2026-11-09/../x", "2026-13-01", "javascript:alert(1)",
                "2026-11-09 ", "%0d%0a", ""]
        for v in evil:
            for key in ("d", "m"):
                r = self.post("/calendar/autofill", {key: v})
                loc = r.headers["location"]
                self.assertRegex(loc, r"^/calendar(\?(view=list|m=\d{4}-\d{2}|d=\d{4}-\d{2}-\d{2}))?\Z", (key, v, loc))
                self.assertNotIn("evil", loc)
                self.assertNotIn("\n", loc)
        self.assertEqual(self.post("/calendar/autofill", {"m": "2026-11\n"}).headers["location"], "/calendar")
        self.assertEqual(self.post("/calendar/autofill", {"d": "2026-11-09"}).headers["location"], "/calendar?d=2026-11-09")
        self.assertEqual(self.post("/calendar/autofill", {"m": "2026-12", "d": "2026-11-09"}).headers["location"],
                         "/calendar?m=2026-12")


class Protection(Base):
    PATHS = ["/calendar/plan", "/calendar/move", "/calendar/autofill", "/calendar/template"]

    def test_every_new_post_needs_csrf_and_a_matching_origin(self):
        self.add(A)
        self.svc.approve(A, ME)
        for p in self.PATHS:
            self.assertEqual(self.post(p, {"d": "2026-11-12"}, csrf=False).status_code, 403, p)
            self.assertEqual(self.post(p, {"d": "2026-11-12"}, csrf="forged").status_code, 403, p)
            self.assertEqual(self.post(p, {"d": "2026-11-12"}, origin="https://evil.example").status_code, 403, p)
            self.assertEqual(self.post(p, {"d": "2026-11-12"}, origin=None).status_code, 403, p)
        self.assertEqual(self.svc.publications(A)[0]["status"], "planned")

    def test_new_posts_are_rate_limited_with_everything_else(self):
        codes = [self.post("/calendar/autofill", {}).status_code for _ in range(45)]
        self.assertIn(429, codes)

    def test_get_requests_to_the_calendar_never_change_state(self):
        self.add(A)
        self.svc.approve(A, ME)
        before = [dict(r) for r in self.svc.publications(A)]
        for q in ("", "?m=2026-12", "?d=2026-11-08", "?view=list", "?autofill=1", "?move=1&pub=1&d=2026-11-20"):
            self.get(f"/calendar{q}")
        self.assertEqual([dict(r) for r in self.svc.publications(A)], before)
        for p in self.PATHS:
            self.assertEqual(self.get(p).status_code, 405, p)


class Files(unittest.TestCase):
    def test_templates_have_no_inline_styles_or_handlers(self):
        import pathlib
        for f in pathlib.Path("bytepanel/templates").glob("*.html"):
            t = f.read_text()
            self.assertNotRegex(t, r"\sstyle=", f.name)
            self.assertNotRegex(t, r"\son(click|submit|load|error|change|drop|drag\w*)=", f.name)

    def test_the_drag_script_only_fills_the_form_and_submits_it(self):
        import pathlib
        js = pathlib.Path("bytepanel/static/app.js").read_text()
        self.assertNotRegex(js, r"\beval\(|new Function|innerHTML|document\.write")
        self.assertIn("move-form", js)


if __name__ == "__main__":
    unittest.main()
