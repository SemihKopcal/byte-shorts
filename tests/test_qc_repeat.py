"""
QC tekrar kurallari. 8 Kasim, daily #18: kanalin tek serisi G oldugu icin
"son 3 video da ayni seri" kurali ucuncu videodan sonra her senaryoyu
reddediyordu (p004). G muaf, A/B hala donuyor; baslik benzerligi ve ayni id
hepsinde gecerli.

    python -m unittest tests.test_qc_repeat -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from worker import qc


def _ledger(entries):
    d = tempfile.mkdtemp()
    f = Path(d) / "published.json"
    f.write_text(json.dumps(entries))
    return f


def _pub(i, series="G", title=None):
    return {"id": f"p00{i}", "series": series,
            "title": title or f"Distinct title number {i} about unrelated subject {chr(97 + i)}{chr(98 + i)}{chr(99 + i)}"}


class SeriesRepeat(unittest.TestCase):
    def test_g_is_not_blocked_after_three_g_videos(self):
        f = _ledger([_pub(1), _pub(2), _pub(3)])
        spec = {"id": "p004", "series": "G"}
        self.assertEqual(qc.repeat_problems(spec, "A terabyte drive shows fewer gigabytes", f), [])

    def test_g_still_fine_after_ten(self):
        f = _ledger([_pub(i) for i in range(1, 11)])
        spec = {"id": "p011", "series": "G"}
        self.assertEqual(qc.repeat_problems(spec, "Eliza rules fooled readers in sixty six", f), [])

    def test_other_series_still_rotate(self):
        f = _ledger([_pub(1, "A"), _pub(2, "A"), _pub(3, "A")])
        spec = {"id": "a004", "series": "A"}
        out = qc.repeat_problems(spec, "Something quite different here today", f)
        self.assertTrue(any("seriyi degistir" in x for x in out), out)

    def test_other_series_ok_when_mixed(self):
        f = _ledger([_pub(1, "A"), _pub(2, "G"), _pub(3, "A")])
        spec = {"id": "a004", "series": "A"}
        self.assertEqual(qc.repeat_problems(spec, "Something quite different here today", f), [])

    def test_similar_title_is_still_refused_for_g(self):
        f = _ledger([_pub(1, "G", "Why a terabyte drive shows nine hundred thirty gigabytes")])
        spec = {"id": "p004", "series": "G"}
        out = qc.repeat_problems(spec, "Why a terabyte drive shows nine hundred thirty one gigabytes", f)
        self.assertTrue(any("cok benziyor" in x for x in out), out)

    def test_same_id_is_still_refused(self):
        f = _ledger([_pub(4)])
        spec = {"id": "p004", "series": "G"}
        out = qc.repeat_problems(spec, "Entirely different heading words appear", f)
        self.assertTrue(any("zaten yayinlanmis" in x for x in out), out)

    def test_no_ledger_is_fine(self):
        spec = {"id": "p004", "series": "G"}
        self.assertEqual(qc.repeat_problems(spec, "Any title at all", Path("/nonexistent/published.json")), [])


if __name__ == "__main__":
    unittest.main()
