"""
tools/ab_report.py: Studio CSV'sini senaryolarla birlestirip kollari karsilastirir.
AG YOK, gercek Studio dosyasi gerekmez.

    python -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ab_report", ROOT / "tools" / "ab_report.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def script(sid, title, theme="ice", scenes=("contrast", "bars", "close"), words=7):
    beats = [{"id": f"b{i}", "say": " ".join(["w"] * words), "scene": s}
             for i, s in enumerate(scenes)]
    return {"id": sid, "series": "G", "format": "measured", "theme": theme,
            "title": title, "beats": beats}


class Parsing(unittest.TestCase):
    def test_headers_in_english_and_turkish(self):
        for h, k in [("Content", "id"), ("Video title", "title"), ("Views", "views"),
                     ("Average percentage viewed (%)", "avg_pct"),
                     ("Average view duration", "avg_dur"),
                     ("Stayed to watch (%)", "stayed"),
                     ("İçerik", "id"), ("Video başlığı", "title"),
                     ("Görüntüleme", "views"),
                     ("Ortalama görüntüleme yüzdesi (%)", "avg_pct"),
                     ("Ortalama görüntüleme süresi", "avg_dur"),
                     ("Watch time (hours)", None), ("", None)]:
            self.assertEqual(A.classify(h), k, h)

    def test_numbers_with_either_decimal_style(self):
        self.assertEqual(A.parse_num("1,234"), 1234)
        self.assertEqual(A.parse_num("12.5"), 12.5)
        self.assertEqual(A.parse_num("12,5"), 12.5)
        self.assertEqual(A.parse_num("1.234"), 1234)
        self.assertEqual(A.parse_num("63.4%"), 63.4)
        self.assertEqual(A.parse_num("1.234,5"), 1234.5)
        self.assertIsNone(A.parse_num("--"))
        self.assertIsNone(A.parse_num(""))

    def test_durations(self):
        self.assertEqual(A.parse_dur("0:21"), 21)
        self.assertEqual(A.parse_dur("1:02:03"), 3723)
        self.assertEqual(A.parse_dur("21"), 21)

    def test_studio_csv_skips_the_total_row_and_reads_semicolons_and_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.csv"
            p.write_text("﻿Content;Video title;Views;Average view duration\n"
                         "Total;;900;0:20\nabc;First #Shorts;100;0:19\n",
                         encoding="utf-8")
            rows = A.read_studio([p])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "abc")
        self.assertEqual(rows[0]["views"], 100)
        self.assertEqual(rows[0]["avg_dur"], 19)

    def test_unknown_layout_stops_with_a_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.csv"
            p.write_text("a,b\n1,2\n")
            with self.assertRaises(SystemExit) as cm:
                A.read_studio([p])
        self.assertIn("--col", str(cm.exception))


class Matching(unittest.TestCase):
    def test_by_youtube_id_then_by_title_ignoring_hashtags(self):
        scripts = {"p1": {"title": "Alpha beta gamma delta"},
                   "p2": {"title": "Totally different headline here"},
                   "p3": {"title": "Never published at all"}}
        studio = [{"id": "YT1", "title": "something else", "views": 1},
                  {"id": "YT2", "title": "Totally different headline here #Shorts", "views": 2}]
        got = A.match(scripts, studio, {"p1": "YT1"})
        self.assertEqual(got["p1"]["views"], 1)
        self.assertEqual(got["p2"]["views"], 2)
        self.assertNotIn("p3", got)

    def test_short_titles_do_not_prefix_match_by_accident(self):
        scripts = {"p1": {"title": "AI"}}
        studio = [{"id": "x", "title": "AI tools you need", "views": 1}]
        self.assertEqual(A.match(scripts, studio, {}), {})

    def test_published_json_and_map_both_give_ids(self):
        ids = A.youtube_ids([{"id": "a", "youtube_id": "Y1"}, {"id": "b"}], {"c": "Y3"})
        self.assertEqual(ids, {"a": "Y1", "c": "Y3"})


class Stats(unittest.TestCase):
    def test_separated_arms_are_significant_and_identical_ones_are_not(self):
        a, b = [1, 2, 3, 4, 5, 6], [11, 12, 13, 14, 15, 16]
        self.assertAlmostEqual(A.perm_p(a, b), 2 / 924, places=6)
        self.assertEqual(A.perm_p(a, a), 1.0)
        self.assertIsNone(A.perm_p([], b))

    def test_the_verdict_refuses_to_decide_on_too_little_data(self):
        self.assertIn("yetersiz", A.verdict(0.001, 3, 3, 6))
        self.assertEqual(A.verdict(0.001, 7, 7, 6), "belirgin fark")
        self.assertEqual(A.verdict(0.5, 7, 7, 6), "fark ayirt edilemiyor")


class Report(unittest.TestCase):
    def run_main(self, argv, scripts, published=(), exps=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "content" / "scripts").mkdir(parents=True)
            for s in scripts:
                (root / "content" / "scripts" / f"{s['id']}.json").write_text(json.dumps(s))
            (root / "content" / "published.json").write_text(json.dumps(list(published)))
            (root / "content" / "built.json").write_text("[]")
            (root / "content" / "experiments.json").write_text(json.dumps(exps or {}))
            old = (A.SCRIPTS, A.PUBLISHED, A.BUILT, A.EXPERIMENTS)
            A.SCRIPTS = root / "content" / "scripts"
            A.PUBLISHED = root / "content" / "published.json"
            A.BUILT = root / "content" / "built.json"
            A.EXPERIMENTS = root / "content" / "experiments.json"
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                    rc = A.main([str(x) if not isinstance(x, str) else x
                                 for x in argv(root)])
            finally:
                A.SCRIPTS, A.PUBLISHED, A.BUILT, A.EXPERIMENTS = old
        return rc, buf.getvalue()

    def test_a_full_run_compares_the_two_arms(self):
        short = [script(f"s{i}", f"Short topic number {i} here") for i in range(6)]
        std = [script(f"t{i}", f"Standard topic number {i} here", words=12) for i in range(6)]
        exps = {"e": {"title": "t", "primary": "views", "min_per_arm": 6,
                      "arms": {"short": [s["id"] for s in short],
                               "standard": [s["id"] for s in std]}}}

        def argv(root):
            p = root / "studio.csv"
            lines = ["Content,Video title,Views,Average percentage viewed (%)"]
            for i in range(6):
                lines.append(f"ys{i},Short topic number {i} here,{1000 + i},80")
                lines.append(f"yt{i},Standard topic number {i} here #Shorts,{100 + i},50")
            p.write_text("\n".join(lines))
            return [p, "--exp", "e", "--md", root / "out.md"]

        rc, out = self.run_main(argv, short + std, exps=exps)
        self.assertEqual(rc, 0)
        self.assertIn("eslesen: 12", out)
        self.assertIn("kol short: 6 video planli, 6 tanesinin verisi var", out)
        self.assertIn("belirgin fark", out)
        self.assertIn("(ana olcut)", out)

    def test_an_unknown_experiment_name_is_an_error(self):
        rc, _ = self.run_main(lambda root: ["--exp", "yok"], [], exps={"e": {}})
        self.assertEqual(rc, 2)

    def test_status_without_a_csv_lists_the_arms(self):
        s = [script("s0", "Short topic number 0 here")]
        exps = {"e": {"arms": {"a": ["s0", "ghost"], "b": []}}}
        rc, out = self.run_main(lambda root: ["--status"], s, exps=exps)
        self.assertEqual(rc, 0)
        self.assertIn("ghost (DOSYA YOK)", out)


class RepoFiles(unittest.TestCase):
    """content/experiments.json ve order.json gercek senaryolarla tutarli olmali."""

    def test_every_arm_member_is_a_real_script_in_exactly_one_arm(self):
        exps = json.loads((ROOT / "content" / "experiments.json").read_text())
        scripts = {f.stem for f in (ROOT / "content" / "scripts").glob("*.json")}
        for name, e in exps.items():
            seen = []
            for arm, ids in e["arms"].items():
                for sid in ids:
                    self.assertIn(sid, scripts, f"{name}/{arm}: {sid} dosyasi yok")
                    seen.append(sid)
            self.assertEqual(len(seen), len(set(seen)), f"{name}: bir id iki kolda")
            sizes = {len(v) for v in e["arms"].values()}
            self.assertEqual(len(sizes), 1, f"{name}: kollar esit buyuklukte degil")

    def test_the_order_file_lists_real_ids_without_duplicates(self):
        order = json.loads((ROOT / "content" / "order.json").read_text())
        scripts = {f.stem for f in (ROOT / "content" / "scripts").glob("*.json")}
        self.assertEqual(len(order), len(set(order)))
        self.assertEqual([x for x in order if x not in scripts], [])

    def test_experiment_scripts_are_queued_in_pairs_alternating_arms_by_day(self):
        exps = json.loads((ROOT / "content" / "experiments.json").read_text())
        order = json.loads((ROOT / "content" / "order.json").read_text())
        e = exps["e1-length"]
        arm_of = {sid: arm for arm, ids in e["arms"].items() for sid in ids}
        seq = [arm_of[x] for x in order if x in arm_of]
        self.assertEqual(len(seq), 14)
        firsts = []
        for day in range(7):
            pair = seq[2 * day:2 * day + 2]
            self.assertEqual(sorted(pair), ["short", "standard"], f"gun {day + 1}")
            firsts.append(pair[0])
        # ayni kol hep ilk slota dusmesin (saat etkisi kola binmesin)
        self.assertGreaterEqual(firsts.count("short"), 3)
        self.assertGreaterEqual(firsts.count("standard"), 3)


if __name__ == "__main__":
    unittest.main()
