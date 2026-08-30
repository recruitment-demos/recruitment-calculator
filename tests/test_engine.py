"""בדיקות למנוע החישוב ולמאגר הנתונים."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recruit_calc.engine import load_engine, round_half_up  # noqa: E402


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
        self.assertFalse(self.eng.stage("submissions")["has_data"])
        self.assertFalse(self.eng.has_rate("submissions"))
        self.assertIsNone(self.eng.rate("submissions"))

    def test_rates_are_valid_probabilities(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            r = s["hire_rate"]
            self.assertGreater(r["low"], 0, s["key"])
            self.assertLessEqual(r["high"], 1, s["key"])
            self.assertLessEqual(r["low"], r["high"], s["key"])

    def test_rate_in_use_is_the_average_of_the_two_bases(self):
        """הערך שבשימוש חייב להיות בדיוק הממוצע, לא ערך שנבחר ידנית."""
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            rates = sorted([s["basis"]["conservative"]["rate"],
                            s["basis"]["mature"]["rate"]])
            self.assertAlmostEqual(s["hire_rate"]["low"], rates[0], places=5, msg=s["key"])
            self.assertAlmostEqual(s["hire_rate"]["high"], rates[1], places=5, msg=s["key"])
            self.assertAlmostEqual(self.eng.rate(s["key"]),
                                   (rates[0] + rates[1]) / 2, places=5, msg=s["key"])

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
        ordered = [s["key"] for s in self.data["stages"] if s["has_data"]]
        rates = [self.eng.rate(k) for k in ordered]
        # מרכז הערכה הוא שלב סלקטיבי שלא כולם עוברים בו, ולכן לא נדרשת
        # מונוטוניות מוחלטת - נדרש רק שהראשון יהיה הנמוך והאחרון הגבוה.
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

    def test_gap_tolerance_present(self):
        tol = self.data["gap_tolerance"]
        self.assertGreater(tol["pct"], 0)
        self.assertGreaterEqual(tol["min_candidates"], 1)


class TestRounding(unittest.TestCase):
    def test_half_rounds_up_not_to_even(self):
        # round() המובנה היה מחזיר 2 עבור 2.5, בניגוד ל-Math.round ב-JS
        self.assertEqual(round_half_up(2.5), 3)
        self.assertEqual(round_half_up(3.5), 4)

    def test_ordinary_rounding(self):
        self.assertEqual(round_half_up(2.4), 2)
        self.assertEqual(round_half_up(2.6), 3)
        self.assertEqual(round_half_up(0), 0)


class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def test_results_are_single_numbers_not_ranges(self):
        """אין טווחים בשום מוצא של המנוע."""
        self.assertIsInstance(self.eng.project_hires("online_day", 100), float)
        self.assertIsInstance(self.eng.required_for_target("online_day", 30), float)
        self.assertIsInstance(self.eng.convert("file_check", 100, "yachbam"), float)
        filled = self.eng.fill_from("online_day", 100)
        self.assertIsInstance(filled["hires"], int)
        self.assertIsInstance(filled["file_check"]["value"], int)
        for row in self.eng.timeline("online_day", 100):
            self.assertIsInstance(row["hires"], int)

    def test_project_hires_scales_linearly(self):
        a = self.eng.project_hires("online_day", 100)
        b = self.eng.project_hires("online_day", 200)
        self.assertAlmostEqual(b, a * 2, places=6)

    def test_project_and_require_are_inverse(self):
        for key in self.eng.stage_keys(with_data_only=True):
            hires = self.eng.project_hires(key, 1000)
            self.assertAlmostEqual(self.eng.required_for_target(key, hires),
                                   1000, places=6, msg=key)

    def test_convert_to_self_is_identity(self):
        self.assertEqual(self.eng.convert("yachbam", 77, "yachbam"), 77)

    def test_convert_round_trip_returns_to_start(self):
        there = self.eng.convert("file_check", 1000, "yachbam")
        back = self.eng.convert("yachbam", there, "file_check")
        self.assertAlmostEqual(back, 1000, places=6)

    def test_convert_is_transitive(self):
        direct = self.eng.convert("file_check", 5000, "yachbam")
        via = self.eng.convert("online_day",
                               self.eng.convert("file_check", 5000, "online_day"),
                               "yachbam")
        self.assertAlmostEqual(direct, via, places=6)

    def test_no_result_for_stage_without_data(self):
        self.assertIsNone(self.eng.project_hires("submissions", 500))
        self.assertIsNone(self.eng.required_for_target("submissions", 50))
        self.assertIsNone(self.eng.convert("submissions", 500, "file_check"))
        self.assertIsNone(self.eng.convert("file_check", 500, "submissions"))
        self.assertIsNone(self.eng.timeline("submissions", 500))

    def test_fill_from_marks_the_input_stage(self):
        filled = self.eng.fill_from("screening_day", 300)
        self.assertEqual(filled["screening_day"], {"value": 300, "source": "input"})
        self.assertEqual(filled["file_check"]["source"], "derived")
        self.assertIsNone(filled["submissions"])

    def test_fill_from_earlier_stages_are_larger(self):
        filled = self.eng.fill_from("yachbam", 100)
        self.assertGreater(filled["file_check"]["value"], filled["yachbam"]["value"])

    def test_required_funnel_hits_the_target(self):
        target = 400
        funnel = self.eng.required_funnel(target)
        self.assertEqual(funnel["hires"], target)
        for key in self.eng.stage_keys(with_data_only=True):
            back = self.eng.project_hires(key, funnel[key]["value"])
            self.assertAlmostEqual(back, target, delta=1, msg=key)
        self.assertIsNone(funnel["submissions"])

    def test_timeline_sums_to_projected_hires(self):
        count = 1000
        rows = self.eng.timeline("online_day", count)
        hires = self.eng.project_hires("online_day", count)
        # סכום הדליים המעוגלים חייב להיות צמוד לסך המגויסים
        self.assertAlmostEqual(sum(r["hires"] for r in rows), hires,
                               delta=len(rows) / 2)

    def test_timeline_has_a_row_per_bucket(self):
        rows = self.eng.timeline("file_check", 500)
        self.assertEqual([r["key"] for r in rows],
                         [b["key"] for b in self.eng.buckets])

    def test_gap_analysis_reports_deficit(self):
        msgs = self.eng.gap_analysis({"file_check": 10, "yachbam": 500})
        pair = [m for m in msgs if m["stage"] == "file_check"][0]
        self.assertEqual(pair["kind"], "deficit")
        self.assertGreater(pair["gap"], 0)

    def test_gap_analysis_reports_surplus(self):
        msgs = self.eng.gap_analysis({"file_check": 500000, "yachbam": 10})
        pair = [m for m in msgs if m["stage"] == "file_check"][0]
        self.assertEqual(pair["kind"], "surplus")
        self.assertGreater(pair["gap"], 0)

    def test_gap_analysis_balanced_when_exactly_consistent(self):
        needed = self.eng.convert("yachbam", 100, "file_check")
        msgs = self.eng.gap_analysis({"file_check": round(needed), "yachbam": 100})
        pair = [m for m in msgs if m["against"] == "yachbam"][0]
        self.assertEqual(pair["kind"], "balanced")
        self.assertEqual(pair["gap"], 0)

    def test_gap_tolerance_absorbs_small_differences(self):
        """הפרש של מועמד אחד לא נחשב פער."""
        needed = self.eng.convert("yachbam", 100, "file_check")
        msgs = self.eng.gap_analysis({"file_check": round(needed) + 1, "yachbam": 100})
        pair = [m for m in msgs if m["against"] == "yachbam"][0]
        self.assertEqual(pair["kind"], "balanced")

    def test_gap_tolerance_does_not_absorb_large_differences(self):
        needed = self.eng.convert("yachbam", 100, "file_check")
        msgs = self.eng.gap_analysis({"file_check": round(needed * 1.5), "yachbam": 100})
        pair = [m for m in msgs if m["against"] == "yachbam"][0]
        self.assertEqual(pair["kind"], "surplus")

    def test_gap_analysis_target_verdicts(self):
        low = self.eng.gap_analysis({"yachbam": 100}, target=500)
        self.assertEqual(low[-1]["kind"], "target_miss")
        self.assertGreater(low[-1]["gap"], 0)

        high = self.eng.gap_analysis({"yachbam": 100}, target=1)
        self.assertEqual(high[-1]["kind"], "target_over")

        exact = round_half_up(self.eng.project_hires("yachbam", 100))
        ok = self.eng.gap_analysis({"yachbam": 100}, target=exact)
        self.assertEqual(ok[-1]["kind"], "target_ok")
        self.assertEqual(ok[-1]["gap"], 0)

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
