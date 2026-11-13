"""Hikayeler: kolay form on kontrolu, istek/sonuc akisi (R2 + workflow), kuyruk islemleri, web sayfalari."""
import json
import re
import unittest
from datetime import timedelta

from bytepanel import scripts
from bytepanel.github import GitHubError
from bytepanel.service import SCRIPT_PENDING_MAX, SCRIPT_TIMEOUT_MIN, Invalid
from tests.helpers import make_service
from tests.test_web import A, B, ME, Base

BEATS = [
    ("YouTube started as a video dating site.", "YouTube began as a dating site", "", ""),
    ("Its tagline was tune in, hook up.", "Tagline: Tune in, hook up", "Tune in, hook up", ""),
    ("The domain was registered on Valentine's Day, two thousand five.",
     "Domain registered: Feb 14, 2005", "Feb 14, 2005", ""),
    ("The first video went up in April two thousand five.", "First video: Apr 2005", "Apr 2005", ""),
    ("Users quickly began posting videos on any subject.", "Videos on any subject", "any subject", ""),
    ("By December two thousand five, it reported eight million views a day.",
     "Dec 2005: 8M views a day", "8M views", ""),
    ("By October two thousand six, it reported over one hundred million views a day.",
     "Oct 2006: 100M+ views a day", "100M+", ""),
    ("Google agreed to acquire it that month.", "Google agrees to acquire it", "", ""),
    ("The price was one billion, six hundred fifty million dollars.",
     "$1.65 billion deal", "$1.65 billion", "check"),
    ("That was about twenty months after the company was founded.",
     "About 20 months after founding", "20 months", ""),
    ("A dating site idea became a video platform.", "Dating idea. Video platform.", "", ""),
    ("Google bought that platform.", "Bought by Google", "", ""),
]


def good_form():
    """Gecerli bir form (tests/fixtures.py story_form ile ayni icerik; panel testleri depo testlerinden ayri)."""
    return {
        "title": "YouTube started as a video dating site", "format": "story", "theme": "",
        "tags": "youtube, startup story, google",
        "description": ("YouTube began in 2005 as a video dating site with the tagline 'Tune in, hook up'. "
                        "Google agreed to buy it in October 2006 for $1.65 billion."),
        "beats": [{"say": a, "cap": b, "kw": c, "mark": d} for a, b, c, d in BEATS],
        "sources": ["https://www.mediavillage.com/article/historys-moment-in-media-youtubes-origin-story/",
                    "https://www.sec.gov/Archives/edgar/data/1288776/000119312506206884/dex991.htm"],
        "facts": [
            {"text": "YouTube began as a dating site; its tagline was 'Tune in, hook up'",
             "source": "1", "note": "MediaVillage: began as a dating site"},
            {"text": "The domain was registered on February 14, 2005; first video April 2005",
             "source": "1", "note": "MediaVillage: registered on Valentine's Day 2005"},
            {"text": "In December 2005 YouTube reported 8 million views a day",
             "source": "1", "note": "MediaVillage: 8 million views a day"},
            {"text": "On October 9, 2006 Google agreed to buy YouTube for $1.65 billion; more than 100 million "
                     "views a day", "source": "2", "note": "Google press release, October 9, 2006"},
            {"text": "Google bought YouTube about 20 months after it was founded", "source": "2",
             "note": "Google press release: founded February 2005, deal October 2006"},
        ],
        "calcs": [],
    }


def as_post(form):
    """Formu tarayicinin gonderecegi alan adlariyla sozluge cevirir."""
    d = {"title": form["title"], "format": form["format"], "theme": form["theme"], "tags": form["tags"],
         "description": form["description"]}
    for i, b in enumerate(form["beats"], start=1):
        d.update({f"say_{i}": b["say"], f"cap_{i}": b["cap"], f"kw_{i}": b["kw"], f"mark_{i}": b["mark"]})
    for i, u in enumerate(form["sources"], start=1):
        d[f"src_{i}"] = u
    for i, f in enumerate(form["facts"], start=1):
        d.update({f"fact_text_{i}": f["text"], f"fact_src_{i}": f["source"], f"fact_note_{i}": f["note"]})
    for i, c in enumerate(form["calcs"], start=1):
        d.update({f"calc_shown_{i}": c["shown"], f"calc_expr_{i}": c["expr"]})
    return d


class Precheck(unittest.TestCase):
    def test_a_good_form_passes(self):
        self.assertEqual(scripts.precheck(good_form()), [])

    def test_post_round_trip_keeps_the_form(self):
        f = good_form()
        self.assertEqual(scripts.form_from_post(as_post(f)), f)

    def test_empty_rows_are_skipped_and_text_is_cleaned(self):
        post = as_post(good_form())
        post["say_13"], post["say_14"] = "", "   "
        post["title"] = "  YouTube ’s\x00 start  "
        form = scripts.form_from_post(post)
        self.assertEqual(len(form["beats"]), 12)
        self.assertEqual(form["title"], "YouTube 's start")

    def problems(self, mutate):
        f = good_form()
        mutate(f)
        return " ".join(scripts.precheck(f))

    def test_each_rule_is_reported_in_plain_turkish(self):
        cases = {
            "Baslik bos": lambda f: f.update(title=""),
            "en fazla 60": lambda f: f.update(title="x" * 61),
            "Bicim": lambda f: f.update(format="movie"),
            "Bilinmeyen tema": lambda f: f.update(theme="neon"),
            "Aciklama": lambda f: f.update(description="kisa"),
            "etiket": lambda f: f.update(tags="a,b,c,d,e,f"),
            "10 ile 14": lambda f: f.update(beats=f["beats"][:5]),
            "rakam var": lambda f: f["beats"][3].update(say="It went up in April 2005."),
            "yasakli kalip": lambda f: f["beats"][4].update(say="Imagine posting videos on any subject."),
            "AYNEN": lambda f: f["beats"][4].update(kw="nothing here"),
            "isaret icin": lambda f: f["beats"][0].update(mark="check"),
            "soru olmamali": lambda f: f["beats"][0].update(say="Was YouTube a dating site?"),
            "kanca": lambda f: f["beats"][0].update(say="YouTube started out as a video dating site, believe it or "
                                                         "not, back then in the early days."),
            "kaynak no": lambda f: f["facts"][0].update(source="9"),
            "hicbir olayda": lambda f: [x.update(source="1") for x in f["facts"]],
            "https://": lambda f: f["sources"].__setitem__(0, "http://example.com/a"),
            "iki kez": lambda f: f["sources"].__setitem__(1, f["sources"][0]),
            "kaynak yazmissin": lambda f: f.update(sources=f["sources"][:1]),
            "olay yazmissin": lambda f: f.update(facts=f["facts"][:1]),
            "notu bos": lambda f: f["facts"][2].update(note=""),
            "Hesap 1": lambda f: f.update(calcs=[{"shown": "abc", "expr": "1+1"}]),
        }
        for needle, mutate in cases.items():
            self.assertIn(needle, self.problems(mutate), needle)

    def test_too_long_a_video_is_refused(self):
        def long(f):
            for b in f["beats"]:
                b["say"] = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
        self.assertIn("Tahmini sure", self.problems(long))

    def test_estimate_matches_the_repo_formula(self):
        e = scripts.estimate(good_form())
        words = sum(len(b["say"].split()) for b in good_form()["beats"])
        self.assertEqual(e["words"], words)
        self.assertEqual(e["seconds"], round(words / 2.6 + 0.18 * 11))

    def test_a_form_is_never_read_as_code(self):
        self.assertEqual(scripts.precheck("<script>"), ["form okunamadi"])

    def test_request_record_is_bounded(self):
        rec = json.loads(scripts.request_record("a" * 32, good_form(), "2026-11-08T15:00:00Z"))
        self.assertEqual((rec["v"], rec["action"], rec["request_id"]), (1, "new", "a" * 32))
        big = good_form()
        big["description"] = "x" * 70000
        with self.assertRaises(ValueError):
            scripts.request_record("a" * 32, big, "now")

    def test_result_parser_distrusts_everything(self):
        ok = {"v": 1, "request_id": "a" * 32, "status": "ok", "action": "ingest", "script_id": "p050-x",
              "title": "T\x00", "message": "m", "problems": ["p1", "", 3]}
        r = scripts.parse_result(json.dumps(ok).encode())
        self.assertEqual((r["status"], r["title"], r["problems"]), ("ok", "T", ["p1", "3"]))
        for bad in ({**ok, "v": 2}, {**ok, "request_id": "../x"}, {**ok, "status": "maybe"}, [1], "x"):
            with self.assertRaises(ValueError):
                scripts.parse_result(json.dumps(bad).encode())
        with self.assertRaises(ValueError):
            scripts.parse_result(b"not json")


class Flow(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()

    def row(self, rid):
        return dict(self.svc.db.one("SELECT * FROM script_requests WHERE request_id=?", (rid,)))

    def test_submit_stores_the_request_then_dispatches_the_scripts_workflow(self):
        seen = {}

        def check(inputs):                         # dispatch ANINDA kayit ve R2 girdisi zaten hazir olmali
            rid = inputs["request_id"]
            seen["row"], seen["key"] = self.row(rid), self.st.exists(f"scripts-in/{rid}.json")
        self.gh.on_dispatch = check
        rid = self.svc.submit_script(good_form(), ME, "1.2.3.4")
        self.assertRegex(rid, r"^[a-f0-9]{32}$")
        self.assertEqual(seen["row"]["status"], "sent")
        self.assertTrue(seen["key"])
        self.assertEqual(self.gh.calls, [{"action": "ingest", "script_id": "", "request_id": rid}])
        self.assertEqual(self.gh.workflows, ["panel-scripts.yml"])
        rec = json.loads(self.st.get_bytes(f"scripts-in/{rid}.json", 65536))
        self.assertEqual(rec["form"]["title"], good_form()["title"])
        self.assertEqual(self.row(rid)["actor"], ME)
        self.assertIn("senaryo: ingest", [r["action"] for r in self.svc.audit_log(5)])

    def test_a_bad_form_never_reaches_r2_or_github(self):
        f = good_form()
        f["title"] = ""
        with self.assertRaises(Invalid):
            self.svc.submit_script(f, ME)
        self.assertEqual(self.gh.calls, [])
        self.assertEqual(self.st.list_keys("scripts-in/", 10), [])
        self.assertEqual(self.svc.script_requests(), [])

    def test_a_failed_dispatch_marks_the_request_and_removes_the_input(self):
        self.gh.fail = GitHubError("HTTP 401")
        with self.assertRaises(Invalid) as cm:
            self.svc.submit_script(good_form(), ME)
        self.assertIn("GitHub", str(cm.exception))
        (r,) = self.svc.script_requests()
        self.assertEqual(r["status"], "error")
        self.assertTrue(r["can_fix"])
        self.assertEqual(self.st.list_keys("scripts-in/", 10), [])

    def test_at_most_five_requests_wait_at_once(self):
        for _ in range(SCRIPT_PENDING_MAX):
            self.svc.submit_script(good_form(), ME)
        with self.assertRaises(Invalid):
            self.svc.submit_script(good_form(), ME)
        self.assertEqual(len(self.gh.calls), SCRIPT_PENDING_MAX)

    def test_results_update_the_row_and_are_deleted(self):
        rid = self.svc.submit_script(good_form(), ME)
        self.svc.script_list()                      # onbellek dolu
        self.st.put_bytes(f"scripts-out/{rid}.json", json.dumps(
            {"v": 1, "request_id": rid, "status": "ok", "action": "ingest", "script_id": "p050-youtube-dating",
             "title": "YouTube started as a video dating site", "message": "Kuyruga eklendi: 13. sirada",
             "problems": []}).encode())
        self.assertEqual(self.svc.ingest_script_results(), 1)
        r = self.row(rid)
        self.assertEqual((r["status"], r["script_id"]), ("ok", "p050-youtube-dating"))
        self.assertIn("13. sirada", r["message"])
        self.assertEqual(self.st.list_keys("scripts-out/", 10), [])
        self.assertIsNone(self.svc._scripts)        # liste yeniden okunur
        self.assertIsNone(self.svc._extras)

    def test_a_rejected_result_keeps_the_form_for_fixing(self):
        rid = self.svc.submit_script(good_form(), ME)
        self.st.put_bytes(f"scripts-out/{rid}.json", json.dumps(
            {"v": 1, "request_id": rid, "status": "rejected", "action": "ingest", "script_id": "", "title": "",
             "message": "Kapidan gecmedi", "problems": ["Cumle 3: kanit yok"]}).encode())
        self.svc.ingest_script_results()
        (r,) = self.svc.script_requests()
        self.assertEqual((r["status"], r["problems"], r["can_fix"]), ("rejected", ["Cumle 3: kanit yok"], True))
        self.assertEqual(self.svc.script_form(rid)["title"], good_form()["title"])

    def test_unknown_and_broken_results_are_quarantined(self):
        self.st.put_bytes("scripts-out/" + "b" * 32 + ".json", json.dumps(
            {"v": 1, "request_id": "b" * 32, "status": "ok"}).encode())
        self.st.put_bytes("scripts-out/zzz.json", b"{not json")
        self.assertEqual(self.svc.ingest_script_results(), 0)
        self.assertEqual(self.st.list_keys("scripts-out/", 10), [])
        self.assertEqual(len(self.st.list_keys("scripts-orphan/", 10)), 1)
        self.assertEqual(len(self.st.list_keys("scripts-rejected/", 10)), 1)

    def test_a_result_cannot_finish_the_same_request_twice(self):
        rid = self.svc.submit_script(good_form(), ME)
        body = json.dumps({"v": 1, "request_id": rid, "status": "ok", "action": "ingest",
                           "script_id": "p050-x", "title": "", "message": "", "problems": []}).encode()
        self.st.put_bytes(f"scripts-out/{rid}.json", body)
        self.assertEqual(self.svc.ingest_script_results(), 1)
        self.st.put_bytes(f"scripts-out/{rid}.json", body.replace(b'"ok"', b'"error"'))
        self.assertEqual(self.svc.ingest_script_results(), 0)
        self.assertEqual(self.row(rid)["status"], "ok")

    def test_silent_requests_time_out_without_touching_finished_ones(self):
        r1 = self.svc.submit_script(good_form(), ME)
        self.clock.t += timedelta(minutes=SCRIPT_TIMEOUT_MIN - 2)
        r2 = self.svc.submit_script(good_form(), ME)
        self.clock.t += timedelta(minutes=3)
        self.assertEqual(self.svc.expire_script_requests(), 1)
        self.assertEqual((self.row(r1)["status"], self.row(r2)["status"]), ("error", "sent"))
        self.assertIn("Sonuc gelmedi", self.row(r1)["message"])
        self.assertFalse(self.st.exists(f"scripts-in/{r1}.json"))
        self.assertTrue(self.st.exists(f"scripts-in/{r2}.json"))

    def test_tick_runs_both_new_steps(self):
        rid = self.svc.submit_script(good_form(), ME)
        self.st.put_bytes(f"scripts-out/{rid}.json", json.dumps(
            {"v": 1, "request_id": rid, "status": "ok", "action": "ingest", "script_id": "p050-x",
             "title": "", "message": "", "problems": []}).encode())
        self.svc.tick()
        self.assertEqual(self.row(rid)["status"], "ok")
        self.assertNotIn("senaryo_sonuc", self.svc.last_errors)

    def test_script_form_refuses_bad_ids_and_other_actions(self):
        for bad in ("../x", "", "Z" * 32, "a" * 31):
            with self.assertRaises(Invalid):
                self.svc.script_form(bad)
        self.svc.gh.queue = [A, B, "p003-air-canada"]
        self.svc.queue_action("remove", B, ME)
        rid = self.svc.script_requests()[0]["request_id"]
        with self.assertRaises(Invalid):               # kuyruk islemi 'Duzelt' ile acilamaz
            self.svc.script_form(rid)


class QueueActions(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        self.gh.queue = [A, B, "p003-air-canada", "p004-x"]

    def test_move_first_and_remove_dispatch_with_the_script_id(self):
        self.svc.queue_action("move_first", B, ME, "9.9.9.9")
        self.svc.queue_action("remove", "p004-x", ME)
        self.assertEqual(self.gh.calls, [
            {"action": "move_first", "script_id": B, "request_id": self.gh.calls[0]["request_id"]},
            {"action": "remove", "script_id": "p004-x", "request_id": self.gh.calls[1]["request_id"]}])
        self.assertEqual(set(self.gh.workflows), {"panel-scripts.yml"})
        self.assertEqual(self.st.list_keys("scripts-in/", 10), [])      # bu islemler R2 girdisi gerektirmez

    def test_only_scripts_in_the_current_queue_are_accepted(self):
        for sid in ("p099-not-queued", "../etc/passwd", "p1-short", "P001-UP"):
            with self.assertRaises(Invalid, msg=sid):
                self.svc.queue_action("remove", sid, ME)
        with self.assertRaises(Invalid):
            self.svc.queue_action("delete_everything", A, ME)
        self.assertEqual(self.gh.calls, [])

    def test_first_in_line_cannot_be_moved_first(self):
        with self.assertRaises(Invalid):
            self.svc.queue_action("move_first", A, ME)

    def test_two_pending_actions_on_one_script_are_refused(self):
        self.svc.queue_action("move_first", B, ME)
        with self.assertRaises(Invalid):
            self.svc.queue_action("remove", B, ME)
        self.assertEqual(len(self.gh.calls), 1)

    def test_a_failed_dispatch_is_recorded(self):
        self.gh.fail = GitHubError("HTTP 500")
        with self.assertRaises(Invalid):
            self.svc.queue_action("remove", B, ME)
        (r,) = self.svc.script_requests()
        self.assertEqual((r["action"], r["status"], r["can_fix"]), ("remove", "error", False))


class Listing(unittest.TestCase):
    def setUp(self):
        self.svc, self.st, self.gh, self.clock = make_service()
        self.gh.queue = [A, B]
        self.gh.titles = {A: {"title": "Tay chatbot", "format": "story", "words": 104, "beats": 12},
                          B: {"title": "GPT-3 GPU", "format": "measured", "words": 60, "beats": 10}}
        self.gh.arm_info = {B: {"name": "hook-b", "label": "B", "n": 2, "exp": "hook"}}

    def test_titles_seconds_and_arms(self):
        sl = self.svc.script_list()
        a, b = sl["items"]
        self.assertEqual((a["n"], a["title"], a["format"]), (1, "Tay chatbot", "story"))
        self.assertEqual(a["seconds"], round(104 / 2.6 + 0.18 * 11))
        self.assertEqual((b["arm"], b["arm_n"], b["exp"]), ("B", 2, "hook"))
        self.assertTrue(sl["experiment_waiting"])
        self.assertTrue(sl["ok"])

    def test_the_list_is_cached_and_reset_after_a_result(self):
        self.svc.script_list()
        self.gh.titles[A]["title"] = "Changed"
        self.assertEqual(self.svc.script_list()["items"][0]["title"], "Tay chatbot")
        self.svc._forget_scripts()
        self.assertEqual(self.svc.script_list()["items"][0]["title"], "Changed")

    def test_github_trouble_never_breaks_the_page(self):
        self.gh.fail_titles = GitHubError("HTTP 502")
        sl = self.svc.script_list()
        self.assertEqual([x["title"] for x in sl["items"]], [A, B])          # basliklar yerine kimlik
        self.assertIn("basliklar", sl["error"])
        self.gh.fail_titles = None
        self.gh.fail_queue = GitHubError("HTTP 500")
        self.svc._forget_scripts()
        sl = self.svc.script_list()
        self.assertEqual((sl["items"], sl["ok"]), ([], False))
        self.assertIn("kuyruk", sl["error"])


class Pages(Base):
    def setUp(self):
        super().setUp()
        self.svc.gh.queue = [A, B, "p003-air-canada"]
        self.svc.gh.titles = {A: {"title": "Tay chatbot", "format": "story", "words": 100, "beats": 12},
                              B: {"title": "GPT-3 <b>GPU</b>", "format": "measured", "words": 60, "beats": 10}}

    def test_queue_page_lists_titles_and_escapes_them(self):
        r = self.get("/scripts")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Tay chatbot", r.text)
        self.assertIn("GPT-3 &lt;b&gt;GPU&lt;/b&gt;", r.text)
        self.assertNotIn("<b>GPU</b>", r.text)
        self.assertIn(f"/scripts/{B}/move", r.text)
        self.assertNotIn(f"/scripts/{A}/move", r.text)                       # birinci zaten basta
        self.assertIn(f"/scripts/{A}/remove", r.text)
        self.assertIn('href="/scripts/new"', r.text)

    def test_nav_has_the_stories_link(self):
        self.assertIn('href="/scripts"', self.get("/").text)

    def test_form_page_has_the_fixed_rows_and_csrf(self):
        r = self.get("/scripts/new")
        self.assertEqual(r.status_code, 200)
        for name in ("title", "format", "theme", "tags", "description", "say_1", "say_14", "cap_14", "kw_14",
                     "mark_14", "src_1", "src_6", "fact_text_6", "fact_src_6", "fact_note_6",
                     "calc_shown_4", "calc_expr_4", "csrf"):
            self.assertIn(f'name="{name}"', r.text, name)
        self.assertNotIn('name="say_15"', r.text)
        self.assertIn('id="est"', r.text)

    def test_a_good_form_is_sent_and_the_user_returns_to_the_list(self):
        r = self.post("/scripts/new", as_post(good_form()))
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/scripts"))
        self.assertEqual(len(self.svc.gh.calls), 1)
        self.assertEqual(self.svc.gh.calls[0]["action"], "ingest")
        page = self.get("/scripts")
        self.assertIn("kontrol ediliyor", page.text)

    def test_a_bad_form_comes_back_with_problems_and_everything_typed(self):
        post = as_post(good_form())
        post["say_4"] = "It went up in April 2005 <script>alert(1)</script>"
        r = self.post("/scripts/new", post)
        self.assertEqual(r.status_code, 422)
        self.assertIn("rakam var", r.text)
        self.assertIn("YouTube started as a video dating site", r.text)       # baslik korunur
        self.assertIn("&lt;script&gt;", r.text)
        self.assertNotIn("<script>alert", r.text)
        self.assertEqual(self.svc.gh.calls, [])

    def test_github_trouble_keeps_the_form(self):
        self.svc.gh.fail = GitHubError("HTTP 401")
        r = self.post("/scripts/new", as_post(good_form()))
        self.assertEqual(r.status_code, 503)
        self.assertIn("GitHub", r.text)
        self.assertIn("YouTube started as a video dating site", r.text)

    def test_fix_link_reopens_a_rejected_form(self):
        rid = self.svc.submit_script(good_form(), ME)
        self.st.put_bytes(f"scripts-out/{rid}.json", json.dumps(
            {"v": 1, "request_id": rid, "status": "rejected", "action": "ingest", "script_id": "", "title": "",
             "message": "Reddedildi", "problems": ["Cumle 3: kanit yok"]}).encode())
        self.svc.ingest_script_results()
        page = self.get("/scripts")
        self.assertIn("Cumle 3: kanit yok", page.text)
        self.assertIn(f"/scripts/new?fix={rid}", page.text)
        form = self.get(f"/scripts/new?fix={rid}")
        self.assertEqual(form.status_code, 200)
        self.assertIn("Google bought that platform.", form.text)
        bad = self.get("/scripts/new?fix=../../etc")
        self.assertEqual((bad.status_code, bad.headers["location"]), (303, "/scripts"))

    def test_move_and_remove_post_through_to_the_workflow(self):
        r = self.post(f"/scripts/{B}/move")
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/scripts"))
        r = self.post("/scripts/p003-air-canada/remove")
        self.assertEqual(r.status_code, 303)
        self.assertEqual([c["action"] for c in self.svc.gh.calls], ["move_first", "remove"])

    def test_bad_ids_are_404_and_never_reach_github(self):
        for sid in ("..%2Fx", "P001-X", "p1-x", "p001-x%20y"):
            self.assertEqual(self.post(f"/scripts/{sid}/remove").status_code, 404, sid)
        self.assertEqual(self.svc.gh.calls, [])

    def test_posts_need_csrf_and_a_matching_origin(self):
        self.assertEqual(self.post("/scripts/new", as_post(good_form()), csrf=False).status_code, 403)
        self.assertEqual(self.post("/scripts/new", as_post(good_form()), csrf="bad").status_code, 403)
        self.assertEqual(self.post(f"/scripts/{B}/remove", origin="https://evil.test").status_code, 403)
        self.assertEqual(self.post(f"/scripts/{B}/remove", origin=None).status_code, 403)
        self.assertEqual(self.svc.gh.calls, [])

    def test_state_changing_routes_are_rate_limited(self):
        codes = [self.post(f"/scripts/{B}/remove").status_code for _ in range(60)]
        self.assertEqual(set(codes[40:]), {429})

    def test_the_stylesheet_and_script_cover_the_new_pages(self):
        css = self.get("/static/app.css").text
        for cls in (".beatrow", ".factrow", ".badge.sent", ".badge.error", ".est"):
            self.assertIn(cls, css)
        js = self.get("/static/app.js").text
        self.assertIn("getElementById('est')", js)
        self.assertNotRegex(self.get("/scripts/new").text, r"\sstyle=")        # CSP: satir ici stil yok


if __name__ == "__main__":
    unittest.main()
