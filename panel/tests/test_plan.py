"""Takvim mantigi (bytepanel/plan.py): saf fonksiyonlar; ag, DB ve saat yok."""
import unittest
from datetime import date, datetime, timezone

from bytepanel import plan


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


class TimeZone(unittest.TestCase):
    def test_turkey_is_a_fixed_utc_plus_3(self):
        self.assertEqual(plan.tr_to_utc(date(2026, 11, 9), "10:15"), utc(2026, 11, 9, 7, 15))
        # gece yarisindan sonrasi bir onceki UTC gunune duser
        self.assertEqual(plan.tr_to_utc(date(2026, 11, 9), "00:30"), utc(2026, 11, 8, 21, 30))
        self.assertEqual(plan.to_tr(utc(2026, 11, 8, 21, 30)).date(), date(2026, 11, 9))
        # yazin da fark yok (Turkiye'de yaz saati yok)
        self.assertEqual(plan.tr_to_utc(date(2026, 7, 1), "12:00"), utc(2026, 7, 1, 9, 0))

    def test_bad_times_and_days_are_refused(self):
        for bad in ("", "24:00", "9:15", "10:60", "10:15:00", "ab:cd", "10:15\n", " 10:15"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                plan.tr_to_utc(date(2026, 11, 9), bad)
        for bad in ("", "2026-02-31", "2026-13-01", "26-11-09", "2026-11-9", "2026-11-09x", "x"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                plan.parse_day(bad)
        self.assertEqual(plan.parse_day("2026-11-09"), date(2026, 11, 9))
        self.assertEqual(plan.parse_day(" 2026-11-09\n"), date(2026, 11, 9))     # bastaki/sondaki bosluk kirpilir

    def test_only_ascii_digits_are_accepted(self):
        for bad in ("２０２６-11-09", "2026-１１-09", "2026-11-０９"):
            with self.assertRaises(ValueError, msg=bad):
                plan.parse_day(bad)
        for bad in ("１０:15", "10:１５"):
            with self.assertRaises(ValueError, msg=bad):
                plan.tr_to_utc(date(2026, 11, 9), bad)
        with self.assertRaises(ValueError):
            plan.parse_month("２０２６-11", date(2026, 11, 9))
        self.assertIsNone(plan.DAY_RX.match("２０２６-11-09"))

    def test_a_typed_datetime_is_turkey_time(self):
        self.assertEqual(plan.parse_tr_datetime("2026-11-12 08:15"), utc(2026, 11, 12, 5, 15))
        self.assertEqual(plan.parse_tr_datetime("2026-11-12T08:15"), utc(2026, 11, 12, 5, 15))
        for bad in ("tomorrow", "2026-11-12", "2026-11-12 8:15", "2026-11-12 08:15 extra", ""):
            with self.assertRaises(ValueError, msg=bad):
                plan.parse_tr_datetime(bad)


class Months(unittest.TestCase):
    TODAY = date(2026, 11, 9)

    def test_month_parsing(self):
        self.assertEqual(plan.parse_month(None, self.TODAY), (2026, 11))
        self.assertEqual(plan.parse_month("", self.TODAY), (2026, 11))
        self.assertEqual(plan.parse_month("2027-01", self.TODAY), (2027, 1))
        for bad in ("2026-13", "2026-00", "2026-1", "26-11", "2026-11-09", "abcd-ef",
                    "1990-01", "2099-01"):
            with self.assertRaises(ValueError, msg=bad):
                plan.parse_month(bad, self.TODAY)

    def test_month_shift_wraps_years(self):
        self.assertEqual(plan.shift_month(2026, 12, 1), (2027, 1))
        self.assertEqual(plan.shift_month(2026, 1, -1), (2025, 12))
        self.assertEqual(plan.shift_month(2026, 11, 0), (2026, 11))

    def test_grid_starts_on_monday_and_covers_the_month(self):
        g = plan.month_grid(2026, 11)               # 1 Kasim 2026 = Pazar
        self.assertEqual(g[0][0], date(2026, 10, 26))
        self.assertEqual(g[0][6], date(2026, 11, 1))
        self.assertEqual(len(g), 6)
        self.assertTrue(all(len(w) == 7 and w[0].weekday() == 0 for w in g))
        days = [d for w in g for d in w]
        self.assertTrue({date(2026, 11, n) for n in range(1, 31)} <= set(days))
        self.assertEqual(len(plan.month_grid(2027, 2)), 4)          # 1 Sub 2027 Pazartesi, 28 gun

    def test_grid_bounds_are_turkey_midnights_in_utc(self):
        lo, hi = plan.grid_bounds_utc(2026, 11)
        self.assertEqual(lo, utc(2026, 10, 25, 21, 0))              # 26 Eki 00:00 TR
        self.assertEqual(hi, utc(2026, 12, 6, 21, 0))               # 7 Ara 00:00 TR
        d0, d1 = plan.day_bounds_utc(date(2026, 11, 9))
        self.assertEqual((d0, d1), (utc(2026, 11, 8, 21, 0), utc(2026, 11, 9, 21, 0)))


class Week(unittest.TestCase):
    FULL = "10:15,22:15|10:15,22:15|10:15,22:15|10:15,22:15|10:15,22:15|12:00|"

    def test_parse_and_format_roundtrip_and_normalize(self):
        w = plan.parse_week(self.FULL)
        self.assertEqual(w[0], ["10:15", "22:15"])
        self.assertEqual(w[5], ["12:00"])
        self.assertEqual(w[6], [])
        self.assertEqual(plan.format_week(w), self.FULL)
        w2 = plan.parse_week("22:15, 10:15,10:15||||||")
        self.assertEqual(w2[0], ["10:15", "22:15"])                 # sirali, tekrarsiz

    def test_bad_templates_are_refused(self):
        for bad in ("", "10:15", "|" * 5, "|" * 7, "x||||||", "25:00||||||", "9:00||||||",
                    ",".join(f"{h:02d}:00" for h in range(9)) + "||||||"):
            with self.assertRaises(ValueError, msg=bad):
                plan.parse_week(bad)

    def test_configured_means_at_least_one_time(self):
        self.assertFalse(plan.week_is_configured(None))
        self.assertFalse(plan.week_is_configured(plan.parse_week("||||||")))
        self.assertTrue(plan.week_is_configured(plan.parse_week(self.FULL)))

    def test_slots_follow_the_template_in_turkey_time(self):
        w = plan.parse_week(self.FULL)
        it = plan.iter_slots(utc(2026, 11, 8, 15, 0), w, ["01:15"])     # Pazar 18:00 TR
        got = [next(it) for _ in range(4)]
        self.assertEqual(got, [utc(2026, 11, 9, 7, 15), utc(2026, 11, 9, 19, 15),
                               utc(2026, 11, 10, 7, 15), utc(2026, 11, 10, 19, 15)])
        # Cumartesi: tek saat; Pazar: yok (bos gun atlanir)
        it = plan.iter_slots(utc(2026, 11, 13, 20, 0), w, [])           # Cuma 23:00 TR
        self.assertEqual(next(it), utc(2026, 11, 14, 9, 0))             # Cmt 12:00 TR
        self.assertEqual(next(it), utc(2026, 11, 16, 7, 15))            # Paz yok -> Pzt 10:15 TR

    def test_without_a_template_the_utc_slots_apply_every_day(self):
        it = plan.iter_slots(utc(2026, 11, 8, 2, 0), None, ["13:15", "07:15"])
        self.assertEqual([next(it) for _ in range(3)],
                         [utc(2026, 11, 8, 7, 15), utc(2026, 11, 8, 13, 15), utc(2026, 11, 9, 7, 15)])

    def test_a_slot_exactly_at_the_start_is_not_after_it(self):
        it = plan.iter_slots(utc(2026, 11, 8, 7, 15), None, ["07:15", "13:15"])
        self.assertEqual(next(it), utc(2026, 11, 8, 13, 15))

    def test_day_times_for_the_planning_form(self):
        w = plan.parse_week(self.FULL)
        self.assertEqual(plan.day_times_tr(date(2026, 11, 9), w, []), ["10:15", "22:15"])
        self.assertEqual(plan.day_times_tr(date(2026, 11, 15), w, []), [])
        # sablon yok: UTC saatlerinin Turkiye karsiligi
        self.assertEqual(plan.day_times_tr(date(2026, 11, 9), None, ["01:15", "19:15"]), ["04:15", "22:15"])


class Queue(unittest.TestCase):
    def test_order_json_goes_first_in_list_order_then_file_order(self):
        ids = ["p003-c", "p001-a", "p002-b", "p004-d", "p005-e"]
        self.assertEqual(plan.compute_queue(ids, {"p001-a"}, ["p005-e", "p003-c", "p999-nope", "p005-e"]),
                         ["p005-e", "p003-c", "p002-b", "p004-d"])
        self.assertEqual(plan.compute_queue(ids, set(), []), sorted(ids))
        self.assertEqual(plan.compute_queue(ids, set(ids), ["p001-a"]), [])
        # sirada olup yapilmis olan atlanir
        self.assertEqual(plan.compute_queue(ids, {"p005-e"}, ["p005-e", "p004-d"])[0], "p004-d")

    def test_runs_take_scripts_in_order_and_then_run_dry(self):
        after, until = utc(2026, 11, 8, 15, 0), utc(2026, 11, 10, 23, 0)
        runs = plan.predict_runs(after, ["16:15", "04:15"], until, ["a", "b", "c"])
        self.assertEqual([r["at"] for r in runs], [utc(2026, 11, 8, 16, 15), utc(2026, 11, 9, 4, 15),
                                                   utc(2026, 11, 9, 16, 15), utc(2026, 11, 10, 4, 15),
                                                   utc(2026, 11, 10, 16, 15)])
        self.assertEqual([r["script_id"] for r in runs], ["a", "b", "c", None, None])

    def test_the_window_is_after_exclusive_until_inclusive(self):
        runs = plan.predict_runs(utc(2026, 11, 9, 4, 15), ["04:15"], utc(2026, 11, 10, 4, 15), ["a", "b"])
        self.assertEqual([r["at"] for r in runs], [utc(2026, 11, 10, 4, 15)])
        self.assertEqual(plan.predict_runs(utc(2026, 11, 9), [], utc(2026, 12, 1), ["a"]), [])

    def test_days_left(self):
        self.assertEqual(plan.queue_days(9, 2), 5)
        self.assertEqual(plan.queue_days(8, 2), 4)
        self.assertEqual(plan.queue_days(0, 2), 0)
        self.assertEqual(plan.queue_days(5, 0), 0)


class Model(unittest.TestCase):
    def pub(self, i, when, platform="youtube", status="planned", sid="p001-a", title="Bir"):
        return {"id": i, "scheduled_at": when, "platform": platform, "status": status,
                "script_id": sid, "title": title}

    def test_events_land_on_the_turkey_day_not_the_utc_day(self):
        pubs = [self.pub(1, "2026-11-08T21:30:00Z"),        # TR 9 Kasim 00:30
                self.pub(2, "2026-11-09T20:59:00Z")]        # TR 9 Kasim 23:59
        ev = plan.events_for(pubs, [], [], {})
        self.assertEqual({d.day for d in ev}, {9})
        self.assertEqual([e["hhmm"] for e in ev[date(2026, 11, 9)]], ["00:30", "23:59"])

    def test_only_planned_publications_can_be_dragged(self):
        pubs = [self.pub(1, "2026-11-09T07:15:00Z", status=s) for s in
                ("planned", "dispatched", "published", "failed")]
        ev = plan.events_for(pubs, [], [], {})[date(2026, 11, 9)]
        self.assertEqual([e["draggable"] for e in ev], [True, False, False, False])

    def test_publications_sort_before_production_and_carry_the_ab_arm(self):
        arm = {"p001-a": {"name": "short", "label": "K", "n": 1}}
        ev = plan.events_for([self.pub(1, "2026-11-09T19:00:00Z")],
                             [{"script_id": "p001-a", "title": "T", "rendered_at": "2026-11-09T01:00:00Z",
                               "approval": "pending"}],
                             [{"at": utc(2026, 11, 9, 2, 0), "script_id": "p001-a"}], arm)[date(2026, 11, 9)]
        self.assertEqual([e["kind"] for e in ev], ["pub", "made", "run"])
        self.assertEqual((ev[0]["arm"], ev[0]["arm_n"], ev[0]["arm_name"]), ("K", 1, "short"))

    def test_only_the_first_empty_run_is_shown(self):
        runs = [{"at": utc(2026, 11, 9, 4, 15), "script_id": "a"},
                {"at": utc(2026, 11, 9, 16, 15), "script_id": None},
                {"at": utc(2026, 11, 10, 4, 15), "script_id": None}]
        ev = plan.events_for([], [], runs, {})
        self.assertEqual(sum(len(v) for v in ev.values()), 2)

    def test_month_grid_model(self):
        pubs = [self.pub(i, "2026-11-09T07:15:00Z", sid=f"p00{i}-x", title=f"T{i}") for i in range(1, 6)]
        mm = plan.build_month(2026, 11, date(2026, 11, 9), pubs, [], [], {})
        self.assertEqual((mm["title"], mm["prev"], mm["next"], mm["this"]),
                         ("Kasim 2026", "2026-10", "2026-12", "2026-11"))
        cells = {c["iso"]: c for w in mm["weeks"] for c in w}
        c = cells["2026-11-09"]
        self.assertTrue(c["today"] and not c["past"] and c["in_month"])
        self.assertEqual((len(c["shown"]), c["more"], len(c["events"])), (3, 2, 5))
        self.assertTrue(cells["2026-11-08"]["past"])
        self.assertFalse(cells["2026-10-26"]["in_month"])
        self.assertEqual(cells["2026-11-10"]["events"], [])


if __name__ == "__main__":
    unittest.main()
