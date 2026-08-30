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
                self.assertIsNotNone(s["forward"], s["key"])
            else:
                # שלב ללא מקור נתונים אסור שיקבל שיעור משוער
                self.assertIsNone(s["hire_rate"], s["key"])
                self.assertIsNone(s["days_to_hire"], s["key"])
                self.assertIsNone(s["forward"], s["key"])
                self.assertTrue(s["note"], s["key"])

    def test_submissions_stage_has_no_invented_data(self):
        self.assertFalse(self.eng.stage("submissions")["has_data"])
        self.assertFalse(self.eng.has_rate("submissions"))
        self.assertIsNone(self.eng.rate("submissions"))
        self.assertIsNone(self.eng.forward("submissions"))

    def test_forward_only_contains_later_stages(self):
        """שלב לא יכול להוביל אל עצמו או אל שלב שקדם לו."""
        order = [s["key"] for s in self.data["stages"]]
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            i = order.index(s["key"])
            for f in s["forward"]:
                if f["key"] == self.eng.hire_key:
                    continue
                self.assertGreater(order.index(f["key"]), i,
                                   f"{s['key']} -> {f['key']} אינו קדימה")

    def test_forward_ends_with_hire(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            self.assertEqual(s["forward"][-1]["key"], self.eng.hire_key, s["key"])

    def test_forward_sorted_by_days(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            days = [f["days"]["median"] for f in s["forward"]]
            self.assertEqual(days, sorted(days), s["key"])

    def test_all_reach_rates_are_valid_probabilities(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            for f in s["forward"]:
                r = f["reach"]
                self.assertGreater(r["low"], 0, f"{s['key']}->{f['key']}")
                self.assertLessEqual(r["high"], 1, f"{s['key']}->{f['key']}")
                self.assertLessEqual(r["low"], r["high"], f"{s['key']}->{f['key']}")

    def test_rate_in_use_is_the_average_of_the_two_bases(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            for f in s["forward"]:
                rates = sorted([f["basis"]["conservative"]["rate"],
                                f["basis"]["mature"]["rate"]])
                self.assertAlmostEqual(f["reach"]["low"], rates[0], places=5)
                self.assertAlmostEqual(f["reach"]["high"], rates[1], places=5)
                self.assertAlmostEqual(f["reach"]["mid"], (rates[0] + rates[1]) / 2,
                                       places=5)

    def test_basis_counts_are_consistent(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            for f in s["forward"]:
                for name in ("conservative", "mature"):
                    b = f["basis"][name]
                    self.assertLessEqual(b["reached"], b["candidates"])
                    self.assertAlmostEqual(b["rate"], b["reached"] / b["candidates"],
                                           places=5)

    def test_transitions_have_enough_samples(self):
        with (ROOT / "config" / "params.json").open(encoding="utf-8") as fh:
            min_n = json.load(fh)["min_transition_n"]
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            for f in s["forward"]:
                self.assertGreaterEqual(f["days"]["n"], min_n,
                                        f"{s['key']}->{f['key']}")

    def test_transition_days_are_positive(self):
        """מעבר קדימה חייב לקחת זמן. חציון 0 היה סימן לכיוון הפוך."""
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            for f in s["forward"]:
                self.assertGreater(f["days"]["median"], 0, f"{s['key']}->{f['key']}")

    def test_hire_rate_matches_last_forward_entry(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            self.assertEqual(s["hire_rate"], s["forward"][-1]["reach"], s["key"])

    def test_buckets_sum_to_one(self):
        for s in self.data["stages"]:
            if not s["has_data"]:
                continue
            self.assertAlmostEqual(sum(b["share"] for b in s["buckets"]), 1.0,
                                   places=4, msg=s["key"])

    def test_buckets_cover_all_days_without_gaps(self):
        buckets = self.data["time_buckets"]
        self.assertEqual(buckets[0]["min_days"], 0)
        self.assertIsNone(buckets[-1]["max_days"])
        for prev, nxt in zip(buckets, buckets[1:]):
            self.assertEqual(nxt["min_days"], prev["max_days"] + 1)

    def test_later_stages_convert_better(self):
        ordered = [s["key"] for s in self.data["stages"] if s["has_data"]]
        rates = [self.eng.rate(k) for k in ordered]
        self.assertEqual(min(rates), rates[0])
        self.assertEqual(max(rates), rates[-1])

    def test_time_to_hire_shrinks_towards_the_end(self):
        ordered = [s for s in self.data["stages"] if s["has_data"]]
        self.assertLess(ordered[-1]["days_to_hire"]["median"],
                        ordered[0]["days_to_hire"]["median"])

    def test_meta_windows_are_ordered(self):
        m = self.data["meta"]
        self.assertLess(m["activity_first"], m["activity_last"])
        self.assertLess(m["hire_first"], m["hire_last"])


class TestRounding(unittest.TestCase):
    def test_half_rounds_up_not_to_even(self):
        self.assertEqual(round_half_up(2.5), 3)
        self.assertEqual(round_half_up(3.5), 4)

    def test_ordinary_rounding(self):
        self.assertEqual(round_half_up(2.4), 2)
        self.assertEqual(round_half_up(2.6), 3)
        self.assertEqual(round_half_up(0), 0)


class TestProjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def test_results_are_single_numbers_not_ranges(self):
        proj = self.eng.project_cohort("file_check", 5000)
        for step in proj["steps"]:
            self.assertIsInstance(step["count"], int)
        self.assertIsInstance(proj["hires"], int)
        for row in self.eng.timeline("file_check", 5000):
            self.assertIsInstance(row["hires"], int)

    def test_cohort_starts_with_the_entered_stage_at_day_zero(self):
        proj = self.eng.project_cohort("online_day", 400)
        first = proj["steps"][0]
        self.assertTrue(first["is_source"])
        self.assertEqual(first["key"], "online_day")
        self.assertEqual(first["count"], 400)
        self.assertEqual(first["days_median"], 0)

    def test_cohort_never_derives_earlier_stages(self):
        """הדרישה המרכזית: גזירה קדימה בלבד."""
        order = [s["key"] for s in self.eng.stages]
        for key in self.eng.stage_keys(with_data_only=True):
            proj = self.eng.project_cohort(key, 1000)
            for step in proj["steps"]:
                if step["is_hire"] or step["is_source"]:
                    continue
                self.assertGreater(order.index(step["key"]), order.index(key),
                                   f"{key} גזר לאחור אל {step['key']}")

    def test_cohort_counts_never_exceed_the_entered_amount(self):
        for key in self.eng.stage_keys(with_data_only=True):
            proj = self.eng.project_cohort(key, 1000)
            for step in proj["steps"]:
                self.assertLessEqual(step["count"], 1000, f"{key}/{step['key']}")

    def test_cohort_scales_linearly(self):
        a = self.eng.project_cohort("file_check", 1000)
        b = self.eng.project_cohort("file_check", 2000)
        for sa, sb in zip(a["steps"], b["steps"]):
            self.assertAlmostEqual(sb["count"], sa["count"] * 2, delta=1)

    def test_hires_equal_count_times_hire_rate(self):
        for key in self.eng.stage_keys(with_data_only=True):
            proj = self.eng.project_cohort(key, 3000)
            self.assertEqual(proj["hires"],
                             round_half_up(3000 * self.eng.rate(key)), key)

    def test_no_projection_for_stage_without_data(self):
        self.assertIsNone(self.eng.project_cohort("submissions", 500))
        self.assertIsNone(self.eng.timeline("submissions", 500))
        self.assertIsNone(self.eng.required_for_target("submissions", 50))

    def test_timeline_sums_to_projected_hires(self):
        rows = self.eng.timeline("online_day", 1000)
        hires = self.eng.project_cohort("online_day", 1000)["hires"]
        self.assertAlmostEqual(sum(r["hires"] for r in rows), hires,
                               delta=len(rows) / 2)

    def test_timeline_has_a_row_per_bucket(self):
        rows = self.eng.timeline("file_check", 500)
        self.assertEqual([r["key"] for r in rows],
                         [b["key"] for b in self.eng.buckets])


class TestCombine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def none_counts(self):
        return {k: None for k in self.eng.stage_keys()}

    def test_single_cohort_totals_match_the_projection(self):
        counts = self.none_counts()
        counts["file_check"] = 5000
        result = self.eng.combine(counts)
        proj = self.eng.project_cohort("file_check", 5000)
        self.assertEqual(len(result["cohorts"]), 1)
        self.assertEqual(result["hires"], proj["hires"])
        self.assertFalse(result["overlap_warning"])

    def test_every_total_equals_the_sum_of_its_sources(self):
        """הפירוט חייב להסתכם בדיוק לסך המוצג."""
        counts = self.none_counts()
        counts["file_check"] = 5000
        counts["yachbam"] = 300
        result = self.eng.combine(counts)
        for entry in result["per_stage"]:
            self.assertEqual(entry["total"],
                             sum(s["count"] for s in entry["sources"]), entry["key"])

    def test_every_number_records_where_it_came_from(self):
        counts = self.none_counts()
        counts["online_day"] = 800
        result = self.eng.combine(counts)
        for entry in result["per_stage"]:
            self.assertTrue(entry["sources"], entry["key"])
            for s in entry["sources"]:
                self.assertEqual(s["from"], "online_day")
                self.assertEqual(s["from_count"], 800)

    def test_multiple_cohorts_sum_and_warn(self):
        counts = self.none_counts()
        counts["file_check"] = 5000
        counts["yachbam"] = 300
        result = self.eng.combine(counts)
        self.assertEqual(len(result["cohorts"]), 2)
        self.assertTrue(result["overlap_warning"])
        expected = (self.eng.project_cohort("file_check", 5000)["hires"] +
                    self.eng.project_cohort("yachbam", 300)["hires"])
        self.assertEqual(result["hires"], expected)

    def test_stage_without_data_is_ignored(self):
        counts = self.none_counts()
        counts["submissions"] = 9999
        counts["yachbam"] = 100
        result = self.eng.combine(counts)
        self.assertEqual(len(result["cohorts"]), 1)
        for entry in result["per_stage"]:
            self.assertNotEqual(entry["key"], "submissions")

    def test_empty_input_produces_nothing(self):
        result = self.eng.combine(self.none_counts())
        self.assertEqual(result["cohorts"], [])
        self.assertEqual(result["hires"], 0)
        self.assertFalse(result["overlap_warning"])


class TestCrossCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def none_counts(self):
        return {k: None for k in self.eng.stage_keys()}

    def test_matches_when_the_later_stage_equals_the_projection(self):
        expected = next(s["count"] for s in
                        self.eng.project_cohort("file_check", 5000)["steps"]
                        if s["key"] == "yachbam")
        counts = self.none_counts()
        counts["file_check"] = 5000
        counts["yachbam"] = expected
        checks = self.eng.cross_check(counts)
        self.assertEqual(checks[0]["verdict"], "matches")
        self.assertEqual(checks[0]["gap"], 0)

    def test_reports_fewer_and_more(self):
        expected = next(s["count"] for s in
                        self.eng.project_cohort("file_check", 5000)["steps"]
                        if s["key"] == "yachbam")
        counts = self.none_counts()
        counts["file_check"] = 5000
        counts["yachbam"] = round(expected * 0.5)
        self.assertEqual(self.eng.cross_check(counts)[0]["verdict"], "fewer")
        counts["yachbam"] = round(expected * 2)
        self.assertEqual(self.eng.cross_check(counts)[0]["verdict"], "more")

    def test_single_stage_has_nothing_to_check(self):
        counts = self.none_counts()
        counts["file_check"] = 5000
        self.assertEqual(self.eng.cross_check(counts), [])

    def test_never_checks_backwards(self):
        counts = self.none_counts()
        counts["file_check"] = 5000
        counts["yachbam"] = 300
        for cc in self.eng.cross_check(counts):
            self.assertEqual(cc["early"], "file_check")
            self.assertEqual(cc["late"], "yachbam")


class TestTarget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def test_required_funnel_hits_the_target(self):
        target = 400
        funnel = self.eng.required_funnel(target)
        self.assertEqual(funnel["hires"], target)
        for key in self.eng.stage_keys(with_data_only=True):
            got = self.eng.project_cohort(key, funnel[key]["value"])["hires"]
            self.assertAlmostEqual(got, target, delta=1, msg=key)
        self.assertIsNone(funnel["submissions"])

    def test_verdicts(self):
        self.assertEqual(self.eng.target_verdict(100, 500)["kind"], "target_miss")
        self.assertEqual(self.eng.target_verdict(500, 100)["kind"], "target_over")
        self.assertEqual(self.eng.target_verdict(100, 100)["kind"], "target_ok")

    def test_tolerance_absorbs_a_single_candidate(self):
        self.assertEqual(self.eng.target_verdict(101, 100)["kind"], "target_ok")

    def test_gap_is_reported(self):
        v = self.eng.target_verdict(100, 500)
        self.assertEqual(v["gap"], 400)

    def test_no_target_means_no_verdict(self):
        self.assertIsNone(self.eng.target_verdict(100, None))

    def test_unknown_stage_raises(self):
        with self.assertRaises(KeyError):
            self.eng.stage("no_such_stage")


if __name__ == "__main__":
    unittest.main()
