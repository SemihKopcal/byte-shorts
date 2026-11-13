"""Takvim yenilemesi: Bugun / Yarin / Hafta gorunumleri, sade ozet, TikTok taslak sayaci, gercek uretim saati."""
import unittest
from datetime import date, datetime, timedelta, timezone

from bytepanel import plan
from bytepanel.github import GitHubError
from bytepanel.service import TIKTOK_DRAFT_LIMIT
from tests.helpers import make_service, put_video
from tests.test_web import A, B, ME, Base


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def ev(kind, **kw):
    base = {"kind": kind, "hhmm": "10:00", "title": "T", "script_id": "p001-x", "empty": False}
    if kind == "pub":
        base.update(id=1, platform="youtube", status="planned")
    base.update(kw)
    return base


class Sentence(unittest.TestCase):
    def test_empty_day(self):
        self.assertEqual(plan.day_sentence([]), "Bu gun icin bir sey yok.")

    def test_counts_are_spelled_out_in_plain_turkish(self):
        events = [ev("pub", status="published"), ev("pub", status="planned"), ev("pub", status="planned"),
                  ev("pub", status="failed"), ev("pub", status="dispatched"), ev("made"), ev("run")]
        s = plan.day_sentence(events)
        for part in ("1 yayin yayinlandi", "1 yayin yukleniyor", "2 yayin planli", "1 yayin basarisiz",
                     "1 video uretildi", "1 uretim bekleniyor"):
            self.assertIn(part, s)

    def test_past_days_do_not_promise_planned_posts(self):
        s = plan.day_sentence([ev("pub", status="planned")], past=True)
        self.assertEqual(s, "1 yayin yapilmadi")

    def test_an_empty_queue_is_said_once(self):
        s = plan.day_sentence([ev("run", empty=True), ev("run", empty=True)])
        self.assertEqual(s.count("kuyruk bitti"), 1)


class Delays(unittest.TestCase):
    SLOTS = ["04:15", "16:15"]

    def stamps(self, hhmm_list, days=range(1, 5)):
        return [utc(2026, 11, d, int(h[:2]), int(h[3:])) for d in days for h in hhmm_list]

    def test_the_median_delay_per_cron_slot_is_learned(self):
        r = self.stamps(["12:15", "22:15"])
        self.assertEqual(plan.run_delays(self.SLOTS, r), {"04:15": 480, "16:15": 360})

    def test_jitter_is_smoothed_by_the_median_and_rounded_to_five_minutes(self):
        r = [utc(2026, 11, d, 12, m) for d, m in ((1, 15), (2, 25), (3, 15), (4, 35))] + self.stamps(["22:15"])
        self.assertEqual(plan.run_delays(self.SLOTS, r)["04:15"], 490)

    def test_too_little_data_means_no_correction(self):
        self.assertEqual(plan.run_delays(self.SLOTS, self.stamps(["12:15", "22:15"], days=range(1, 3))), {})
        self.assertEqual(plan.run_delays(self.SLOTS, self.stamps(["12:15"], days=[1] * 8)), {})
        self.assertEqual(plan.run_delays([], self.stamps(["12:15"])), {})

    def test_runs_that_finished_far_too_late_are_ignored(self):
        r = self.stamps(["12:15"], days=range(1, 5)) + [utc(2026, 11, 5, 3, 0)] * 3
        out = plan.run_delays(self.SLOTS, r)
        self.assertEqual(out.get("04:15"), 480)

    def test_a_run_just_after_midnight_belongs_to_the_last_slot_of_the_day_before(self):
        r = [utc(2026, 11, d, 1, 0) for d in range(1, 8)]
        self.assertEqual(plan.run_delays(["23:00"], r), {"23:00": 120})

    def test_effective_runs_shift_by_the_delay_and_never_leave_the_day(self):
        self.assertEqual(plan.effective_runs(self.SLOTS, {"04:15": 490, "16:15": 360}), ["12:25", "22:15"])
        self.assertEqual(plan.effective_runs(self.SLOTS, {}), self.SLOTS)
        self.assertEqual(plan.effective_runs(["20:00"], {"20:00": 600}), ["23:59"])

    def test_monday_of(self):
        self.assertEqual(plan.monday_of(date(2026, 11, 8)), date(2026, 11, 2))      # pazar
        self.assertEqual(plan.monday_of(date(2026, 11, 2)), date(2026, 11, 2))


class ServiceViews(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()

    def video(self, sid, rendered="2026-11-08T14:37:00Z"):
        put_video(self.st, sid, rendered=rendered, title=f"Video {sid}")
        self.svc.ingest_inbox()

    def test_agenda_today_and_tomorrow(self):
        self.video(A)
        self.svc.approve(A, ME)
        extras = self.svc.extras()
        today = self.svc.agenda(date(2026, 11, 8), extras)
        self.assertEqual((today["rel"], today["today"], today["past"]), ("Bugun", True, False))
        self.assertIn("1 yayin planli", today["sentence"])
        self.assertIn("1 video uretildi", today["sentence"])
        tomorrow = self.svc.agenda(date(2026, 11, 9), extras)
        self.assertEqual(tomorrow["rel"], "Yarin")
        self.assertIn("uretim bekleniyor", tomorrow["sentence"])
        self.assertEqual(self.svc.agenda(date(2026, 11, 7), extras)["rel"], "Dun")
        self.assertEqual(self.svc.agenda(date(2026, 11, 20), extras)["rel"], "")

    def test_agenda_does_not_claim_the_queue_ended_when_it_could_not_be_read(self):
        self.gh.fail_queue = GitHubError("HTTP 500")
        a = self.svc.agenda(date(2026, 11, 9), self.svc.extras())
        self.assertNotIn("kuyruk bitti", a["sentence"])
        self.assertFalse(any(e["kind"] == "run" for e in a["events"]))

    def test_week_runs_monday_to_sunday_and_marks_today(self):
        wk = self.svc.week_model(date(2026, 11, 8), self.svc.extras())
        self.assertEqual([d["iso"] for d in wk["days"]][0], "2026-11-02")
        self.assertEqual([d["name"] for d in wk["days"]], list(plan.WEEKDAYS))
        self.assertEqual([d["iso"] for d in wk["days"] if d["today"]], ["2026-11-08"])
        self.assertEqual((wk["prev"], wk["next"]), ("2026-10-26", "2026-11-09"))
        self.assertEqual(wk["title"], "2 - 8 Kasim 2026")
        self.assertTrue(wk["is_this_week"])
        self.assertFalse(self.svc.week_model(date(2026, 11, 16), self.svc.extras())["is_this_week"])

    def test_week_title_across_two_months(self):
        wk = self.svc.week_model(date(2026, 11, 30), self.svc.extras())
        self.assertEqual(wk["title"], "30 Kasim - 6 Aralik 2026")

    def test_tiktok_counter_is_off_until_the_platform_is_on(self):
        self.assertFalse(self.svc.tiktok_drafts()["enabled"])

    def test_tiktok_counter_counts_the_last_24_hours_only(self):
        self.svc.set_setting("platform_tiktok", "1", ME)
        for i in range(7):
            self.video(f"p{100 + i}-t{i}")
            self.svc.approve(f"p{100 + i}-t{i}", ME)
        rows = {r["script_id"]: r["id"] for r in self.svc.db.all("SELECT script_id,id FROM publications WHERE platform='tiktok'")}
        ids = list(rows.values())
        now = self.clock.t
        for i, pid in enumerate(ids[:3]):        # 24 saat icinde: sayilir
            self.svc.db.run("UPDATE publications SET status='published', finished_at=? WHERE id=?",
                            ((now - timedelta(hours=2 + i)).strftime("%Y-%m-%dT%H:%M:%SZ"), pid))
        self.svc.db.run("UPDATE publications SET status='published', finished_at=? WHERE id=?",
                        ((now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"), ids[3]))   # eski: sayilmaz
        self.svc.db.run("UPDATE publications SET status='dispatched', dispatched_at=? WHERE id=?",
                        ((now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"), ids[4]))   # yolda: sayilir
        t = self.svc.tiktok_drafts()
        self.assertEqual((t["enabled"], t["used"], t["limit"], t["free"]), (True, 4, TIKTOK_DRAFT_LIMIT, 1))
        self.assertFalse(t["full"])
        self.svc.db.run("UPDATE publications SET status='published', finished_at=? WHERE id=?",
                        ((now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), ids[5]))
        t = self.svc.tiktok_drafts()
        self.assertEqual((t["used"], t["free"], t["full"]), (5, 0, True))

    def test_tiktok_counter_warns_when_planned_posts_would_overflow(self):
        self.svc.set_setting("platform_tiktok", "1", ME)
        for i in range(2):
            self.video(f"p{100 + i}-t{i}")
            self.svc.approve(f"p{100 + i}-t{i}", ME)
        now = self.clock.t
        self.svc.db.run("UPDATE publications SET scheduled_at=? WHERE platform='tiktok'",
                        ((now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
        t = self.svc.tiktok_drafts()
        self.assertEqual((t["used"], t["planned"], t["over"]), (0, 2, False))

    def test_today_card_numbers(self):
        self.video(A)
        self.video(B)
        self.svc.approve(A, ME)
        pid = self.svc.publications(A)[0]["id"]
        self.svc.db.run("UPDATE publications SET status='failed', finished_at=? WHERE id=?", ("2026-11-07T10:00:00Z", pid))
        tc = self.svc.today_card(self.svc.extras())
        self.assertEqual((tc["pending"], tc["failed"], tc["paused"]), (1, 1, False))
        self.assertEqual(tc["next_run"]["script_id"], self.gh.queue[0])
        self.assertEqual(tc["next_run"]["rel"], "bugun")
        self.assertEqual(tc["runs_tr"], ["07:15", "19:15"])          # 04:15 ve 16:15 UTC
        self.assertTrue(tc["queue"]["known"])

    def test_old_failures_are_not_in_the_attention_box(self):
        self.video(A)
        self.svc.approve(A, ME)
        pid = self.svc.publications(A)[0]["id"]
        self.svc.db.run("UPDATE publications SET status='failed', finished_at=? WHERE id=?", ("2026-10-20T10:00:00Z", pid))
        self.assertEqual(self.svc.today_card(self.svc.extras())["failed"], 0)

    def test_the_calendar_learns_the_real_run_hours(self):
        self.svc.set_setting("runs_utc", "04:15,16:15", ME)
        for d in range(1, 6):
            for n, hhmm in enumerate(("12:15", "22:15")):
                self.video(f"p{200 + d * 2 + n}-r{d}{n}", rendered=f"2026-11-0{d}T{hhmm}:00Z")
        self.assertEqual(self.svc.runs_effective(), ["12:15", "22:15"])
        self.assertEqual(self.svc.run_delays(), {"04:15": 480, "16:15": 360})
        tc = self.svc.today_card(self.svc.extras())
        self.assertEqual(tc["runs_tr"], ["01:15", "15:15"])              # 22:15 UTC = 01:15 TR; 12:15 UTC = 15:15 TR
        self.assertEqual((tc["next_run"]["hhmm"], tc["next_run"]["rel"]), ("01:15", "yarin"))   # simdi 18:00 TR

    def test_a_broken_runs_setting_never_breaks_the_page(self):
        self.svc.db.run("UPDATE settings SET value='garbage' WHERE key='runs_utc'")
        self.assertEqual(self.svc.run_delays(), {})


class Pages(Base):
    def setUp(self):
        super().setUp()
        self.svc.gh.queue = [f"p{n:03d}-sira-{n}" for n in range(40, 49)]

    def test_default_calendar_page_is_today(self):
        self.add(A)
        self.add(B)
        self.svc.approve(A, ME)
        r = self.get("/calendar")
        self.assertEqual(r.status_code, 200)
        for want in ("Bugun ne olacak?", "8 Kasim 2026", "1 video onayini bekliyor", 'href="/videos"',
                     "yayinlanacak", "Siradaki video", "Kuyruk", 'href="/scripts"', 'href="/scripts/new"',
                     'href="/calendar?view=tomorrow"', 'href="/calendar?view=week"',
                     'href="/calendar?view=month"', 'href="/calendar?view=list"', 'aria-current="page"'):
            self.assertIn(want, r.text, want)
        self.assertNotIn("data-day=", r.text)                     # ay izgarasi degil

    def test_tomorrow_is_the_same_page_for_the_next_day_without_the_status_cards(self):
        r = self.get("/calendar?view=tomorrow")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Yarin ne olacak?", r.text)
        self.assertIn("9 Kasim 2026", r.text)
        self.assertNotIn("TikTok taslak kutusu", r.text)
        self.assertNotIn("onayini bekliyor", r.text)

    def test_week_view_and_week_navigation(self):
        r = self.get("/calendar?view=week")
        self.assertEqual(r.status_code, 200)
        self.assertIn("2 - 8 Kasim 2026", r.text)
        self.assertIn('href="/calendar?view=week&amp;w=2026-11-09"', r.text)
        self.assertIn('href="/calendar?view=week&amp;w=2026-10-26"', r.text)
        self.assertNotIn("Bu hafta</a>", r.text)
        for i in range(7):
            self.assertIn(f'href="/calendar?d=2026-11-{2 + i:02d}"', r.text)
        r = self.get("/calendar?view=week&w=2026-11-17")
        self.assertIn("16 - 22 Kasim 2026", r.text)
        self.assertIn("Bu hafta</a>", r.text)

    def test_bad_week_dates_redirect_back_with_a_message(self):
        for q in ("w=2026-02-31", "w=x", "w=2099-01-01", "w=1990-01-01"):
            r = self.get(f"/calendar?view=week&{q}")
            self.assertEqual((r.status_code, r.headers["location"]), (303, "/calendar"), q)

    def test_unknown_views_fall_back_to_today(self):
        r = self.get("/calendar?view=%3Cscript%3E")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Bugun ne olacak?", r.text)
        self.assertNotIn("<script>", r.text.replace('<script src="/static/app.js">', ""))

    def test_month_view_is_still_there(self):
        r = self.get("/calendar?view=month")
        self.assertIn("Kasim 2026", r.text)
        self.assertIn('data-day="2026-11-08"', r.text)
        self.assertIn('href="/scripts"', r.text)

    def test_every_calendar_page_has_the_tab_bar(self):
        for path, on in (("/calendar", "Bugun"), ("/calendar?view=tomorrow", "Yarin"),
                         ("/calendar?view=week", "Hafta"), ("/calendar?view=month", "Ay"),
                         ("/calendar?view=list", "Liste")):
            body = self.get(path).text
            self.assertIn(f'class="on" aria-current="page">{on}</a>', body, path)
        self.assertIn('class="tabs"', self.get("/calendar?d=2026-11-08").text)

    def test_actions_return_to_the_view_they_came_from(self):
        self.add(A)
        self.svc.approve(A, ME)
        pid = self.svc.publications(A)[0]["id"]
        r = self.post(f"/pubs/{pid}/cancel", {"view": "week", "w": "2026-11-02"})
        self.assertEqual(r.headers["location"], "/calendar?view=week&w=2026-11-02")
        for view in ("tomorrow", "month", "list"):
            self.svc.db.run("UPDATE publications SET status='planned' WHERE id=?", (pid,))
            self.assertEqual(self.post(f"/pubs/{pid}/cancel", {"view": view}).headers["location"],
                             f"/calendar?view={view}")
        self.svc.db.run("UPDATE publications SET status='planned' WHERE id=?", (pid,))
        for bad in ("../x", "week\n", "javascript:1", ""):
            self.svc.db.run("UPDATE publications SET status='planned' WHERE id=?", (pid,))
            self.assertEqual(self.post(f"/pubs/{pid}/cancel", {"view": bad}).headers["location"], "/calendar", bad)
        self.svc.db.run("UPDATE publications SET status='planned' WHERE id=?", (pid,))
        r = self.post(f"/pubs/{pid}/cancel", {"view": "week", "w": "../../x"})
        self.assertEqual(r.headers["location"], "/calendar?view=week")

    def test_today_page_buttons_work(self):
        self.add(A)
        self.svc.approve(A, ME)
        pid = self.svc.publications(A)[0]["id"]
        body = self.get("/calendar").text
        self.assertIn(f'action="/pubs/{pid}/now"', body)
        self.assertIn(f'action="/pubs/{pid}/cancel"', body)
        self.assertIn("Simdi yayinla", body)
        self.post(f"/pubs/{pid}/cancel", {})
        self.assertNotIn(f'action="/pubs/{pid}/cancel"', self.get("/calendar").text)

    def test_week_view_is_read_only_rows(self):
        self.add(A)
        self.svc.approve(A, ME)
        body = self.get("/calendar?view=week").text
        self.assertNotIn('action="/pubs/', body)                     # hafta: yalniz bakis, islem gun sayfasinda
        self.assertIn("yayinlanacak", body)

    def test_attention_box_appears_only_when_there_is_something_to_do(self):
        body = self.get("/calendar").text
        self.assertNotIn("card attn", body)
        self.add(A)
        self.assertIn("1 video onayini bekliyor", self.get("/calendar").text)

    def test_paused_publishing_is_loud_on_the_today_page(self):
        self.svc.set_setting("paused", "1", ME)
        self.assertIn("DURAKLATILDI", self.get("/calendar").text)

    def test_tiktok_card_shows_only_when_tiktok_is_on(self):
        self.assertNotIn("TikTok taslak kutusu", self.get("/calendar").text)
        self.svc.set_setting("platform_tiktok", "1", ME)
        body = self.get("/calendar").text
        self.assertIn("TikTok taslak kutusu", body)
        self.assertIn("0</b> / 5", body)

    def test_a_queue_failure_still_renders_today_and_week(self):
        self.svc.gh.fail_queue = GitHubError("HTTP 500 /x")
        self.add(A)
        self.svc.approve(A, ME)
        for path in ("/calendar", "/calendar?view=tomorrow", "/calendar?view=week"):
            r = self.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("Kuyruk bilgisi alinamadi", r.text, path)
            self.assertNotIn("Kuyruk bitti", r.text, path)

    def test_titles_are_escaped_in_the_new_views(self):
        evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
        self.add(A, title=evil)
        self.svc.approve(A, ME)
        self.svc.set_setting("platform_tiktok", "1", ME)
        for path in ("/calendar", "/calendar?view=tomorrow", "/calendar?view=week"):
            body = self.get(path).text
            self.assertNotIn("<script>alert", body, path)
            self.assertNotIn("<img src=x", body, path)
        self.assertIn("&lt;script&gt;alert(1)", self.get("/calendar").text)

    def test_no_inline_script_style_or_handler_in_the_new_pages(self):
        self.add(A)
        self.svc.approve(A, ME)
        self.svc.set_setting("platform_tiktok", "1", ME)
        for path in ("/calendar", "/calendar?view=tomorrow", "/calendar?view=week"):
            body = self.get(path).text
            self.assertNotRegex(body, r"<script(?![^>]*\bsrc=)", path)
            self.assertNotRegex(body, r"\son\w+=", path)
            self.assertNotRegex(body, r"\sstyle=", path)

    def test_new_views_never_change_state(self):
        self.add(A)
        self.svc.approve(A, ME)
        before = [dict(r) for r in self.svc.publications(A)]
        for q in ("", "?view=tomorrow", "?view=week", "?view=week&w=2026-11-16", "?view=month"):
            self.get(f"/calendar{q}")
        self.assertEqual([dict(r) for r in self.svc.publications(A)], before)


if __name__ == "__main__":
    unittest.main()
