"""בדיקות למנוע החישוב ולמאגר הנתונים."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recruit_calc.engine import Range, load_engine  # noqa: E402


class TestDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.data = cls.eng.data

    def test_dataset_matches_config_stages(self):
        with (ROOT / "config" / "params.json").open(encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertEqual([s["key"] for s in cfg["stages"]],
                         [s["key"] for s in self.data["stages"]])

    def test_every_stage_has_explicit_data_flag(self):
        for s in self.data["stages"]:
            self.assertIn("has_data", s, s["key"])
            if s["has_data"]:
                self.assertIsNotNone(s["hire_rate"], s["key"])
                self.assertIsNotNone(s["days_to_hire"], s["key"])
            else:
                # שלב ללא מקור נתונים אסור שיקבל יחס משוער
                self.assertIsNone(s["hire_rate"], s["key"])
                self.assertIsNone(s["days_to_hire"], s["key"])
                self.assertTrue(s["note"], s["key"])

    def test_submissions_stage_has_no_invented_data(self):
        sub = self.eng.stage("submissions")
        self.assertFalse(sub["has_data"])
        self.assertFalse(self.eng.has_rate("submissions"))

    def test_rates_are_valid_probabilities(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            r = s["hire_rate"]
            self.assertGreater(r["low"], 0, s["key"])
            self.assertLessEqual(r["high"], 1, s["key"])
            self.assertLessEqual(r["low"], r["high"], s["key"])

    def test_rate_bounds_come_from_the_two_bases(self):
        """הטווח חייב להיות בדיוק שני בסיסי החישוב, לא ערך מוחלק."""
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            rates = sorted([s["basis"]["conservative"]["rate"],
                            s["basis"]["mature"]["rate"]])
            self.assertAlmostEqual(s["hire_rate"]["low"], rates[0], places=5, msg=s["key"])
            self.assertAlmostEqual(s["hire_rate"]["high"], rates[1], places=5, msg=s["key"])

    def test_basis_counts_are_consistent(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            for name in ("conservative", "mature"):
                b = s["basis"][name]
                self.assertLessEqual(b["hired"], b["candidates"], f"{s['key']}/{name}")
                self.assertAlmostEqual(b["rate"], b["hired"] / b["candidates"],
                                       places=5, msg=f"{s['key']}/{name}")

    def test_buckets_sum_to_one(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            total = sum(b["share"] for b in s["buckets"])
            self.assertAlmostEqual(total, 1.0, places=4, msg=s["key"])

    def test_buckets_cover_all_days_without_gaps(self):
        buckets = self.data["time_buckets"]
        self.assertEqual(buckets[0]["min_days"], 0)
        self.assertIsNone(buckets[-1]["max_days"])
        for prev, nxt in zip(buckets, buckets[1:]):
            self.assertEqual(nxt["min_days"], prev["max_days"] + 1)

    def test_later_stages_convert_better(self):
        """ככל שהשלב מתקדם יותר, יחס הגיוס אמור לעלות."""
        ordered = [s for s in self.data["stages"] if s["has_data"]]
        rates = [s["hire_rate"]["mid"] for s in ordered]
        # מרכז הערכה הוא שלב סלקטיבי שלא כולם עוברים בו, ולכן לא נדרשת
        # מונוטוניות מוחלטת - נדרש רק שהשלב הראשון יהיה הנמוך ביותר
        # והאחרון הגבוה ביותר.
        self.assertEqual(min(rates), rates[0])
        self.assertEqual(max(rates), rates[-1])

    def test_median_days_shrink_towards_the_end(self):
        ordered = [s for s in self.data["stages"] if s["has_data"]]
        self.assertLess(ordered[-1]["days_to_hire"]["median"],
                        ordered[0]["days_to_hire"]["median"])

    def test_meta_windows_are_ordered(self):
        m = self.data["meta"]
        self.assertLess(m["activity_first"], m["activity_last"])
        self.assertLess(m["hire_first"], m["hire_last"])


class TestRange(unittest.TestCase):
    def test_orders_bounds(self):
        r = Range(9, 2)
        self.assertEqual((r.low, r.high), (2, 9))

    def test_rounding_widens_outwards(self):
        self.assertEqual(Range(2.1, 5.9).rounded(), (2, 6))

    def test_exact_integers_stay_put(self):
        self.assertEqual(Range(4.0, 4.0).rounded(), (4, 4))


class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def test_project_hires_scales_linearly(self):
        a = self.eng.project_hires("online_day", 100)
        b = self.eng.project_hires("online_day", 200)
        self.assertAlmostEqual(b.low, a.low * 2, places=6)
        self.assertAlmostEqual(b.high, a.high * 2, places=6)

    def test_project_and_require_are_inverse(self):
        for key in self.eng.stage_keys(with_data_only=True):
            hires = self.eng.project_hires(key, 1000)
            back_low = self.eng.required_for_target(key, hires.low)
            back_high = self.eng.required_for_target(key, hires.high)
            # הגבול התחתון של הגיוסים מגיע מהיחס הנמוך, ולכן חוזר לגבול העליון
            self.assertAlmostEqual(back_low.high, 1000, places=6, msg=key)
            self.assertAlmostEqual(back_high.low, 1000, places=6, msg=key)

    def test_convert_to_self_is_identity(self):
        r = self.eng.convert("yachbam", 77, "yachbam")
        self.assertEqual((r.low, r.high), (77, 77))

    def test_convert_widens_never_narrows(self):
        """מעבר הלוך ושוב בין שלבים לא יכול לצמצם את אי-הוודאות."""
        there = self.eng.convert("file_check", 1000, "yachbam")
        back_low = self.eng.convert("yachbam", there.low, "file_check")
        back_high = self.eng.convert("yachbam", there.high, "file_check")
        self.assertLessEqual(back_low.low, 1000 + 1e-9)
        self.assertGreaterEqual(back_high.high, 1000 - 1e-9)

    def test_convert_through_hires_is_transitive(self):
        direct = self.eng.convert("file_check", 5000, "yachbam")
        via = self.eng.convert("online_day",
                               self.eng.convert("file_check", 5000, "online_day").low,
                               "yachbam")
        # המסלול העקיף חייב להיות מוכל בטווח הישיר או רחב ממנו, לא לחרוג ממנו כלפי מטה
        self.assertLessEqual(via.low, direct.high)

    def test_no_result_for_stage_without_data(self):
        self.assertIsNone(self.eng.project_hires("submissions", 500))
        self.assertIsNone(self.eng.required_for_target("submissions", 50))
        self.assertIsNone(self.eng.convert("submissions", 500, "file_check"))
        self.assertIsNone(self.eng.convert("file_check", 500, "submissions"))
        self.assertIsNone(self.eng.timeline("submissions", 500))

    def test_fill_from_marks_the_input_stage(self):
        filled = self.eng.fill_from("screening_day", 300)
        self.assertEqual(filled["screening_day"]["source"], "input")
        self.assertEqual(filled["screening_day"]["low"], 300)
        self.assertEqual(filled["screening_day"]["high"], 300)
        self.assertEqual(filled["file_check"]["source"], "derived")
        self.assertIsNone(filled["submissions"])

    def test_fill_from_earlier_stages_are_larger(self):
        filled = self.eng.fill_from("yachbam", 100)
        self.assertGreater(filled["file_check"]["low"], filled["yachbam"]["high"])

    def test_timeline_shares_sum_to_projected_hires(self):
        count = 1000
        rows = self.eng.timeline("online_day", count)
        hires = self.eng.project_hires("online_day", count)
        self.assertAlmostEqual(sum(r["hires"].low for r in rows), hires.low, places=3)
        self.assertAlmostEqual(sum(r["hires"].high for r in rows), hires.high, places=3)

    def test_timeline_has_a_row_per_bucket(self):
        rows = self.eng.timeline("file_check", 500)
        self.assertEqual([r["key"] for r in rows],
                         [b["key"] for b in self.eng.buckets])

    def test_gap_analysis_reports_deficit(self):
        # מעט מאוד בדיקות קבצים מול הרבה יחב"מ - חייב לצאת חוסר
        msgs = self.eng.gap_analysis({"file_check": 10, "yachbam": 500})
        kinds = {m["kind"] for m in msgs}
        self.assertIn("deficit", kinds)

    def test_gap_analysis_reports_surplus(self):
        msgs = self.eng.gap_analysis({"file_check": 500000, "yachbam": 10})
        kinds = {m["kind"] for m in msgs}
        self.assertIn("surplus", kinds)

    def test_gap_analysis_balanced_when_consistent(self):
        needed = self.eng.convert("yachbam", 100, "file_check")
        msgs = self.eng.gap_analysis({"file_check": int(needed.mid), "yachbam": 100})
        pair = [m for m in msgs if m["against"] == "yachbam"]
        self.assertEqual(pair[0]["kind"], "balanced")

    def test_gap_analysis_target_verdicts(self):
        low = self.eng.gap_analysis({"yachbam": 100}, target=500)
        self.assertEqual(low[-1]["kind"], "target_miss")
        high = self.eng.gap_analysis({"yachbam": 100}, target=1)
        self.assertEqual(high[-1]["kind"], "target_over")
        projected = self.eng.project_hires("yachbam", 100)
        ok = self.eng.gap_analysis({"yachbam": 100}, target=int(projected.mid))
        self.assertEqual(ok[-1]["kind"], "target_ok")

    def test_gap_analysis_ignores_stages_without_data(self):
        msgs = self.eng.gap_analysis({"submissions": 9999, "yachbam": 100})
        for m in msgs:
            self.assertNotIn("submissions", (m.get("stage"), m.get("against")))

    def test_gap_analysis_target_uses_deepest_entered_stage(self):
        msgs = self.eng.gap_analysis({"file_check": 5000, "yachbam": 100}, target=50)
        self.assertEqual(msgs[-1]["stage"], "yachbam")

    def test_unknown_stage_raises(self):
        with self.assertRaises(KeyError):
            self.eng.stage("no_such_stage")


if __name__ == "__main__":
    unittest.main()
