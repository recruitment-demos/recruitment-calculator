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


class TestCombinedCharts(unittest.TestCase):
    """הגרפים המאוחדים: שורה אחת לכל שלב, ולא גרף נפרד לכל קבוצה שהוזנה."""

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.keys = cls.eng.stage_keys()

    def counts(self, **kw):
        c = {k: None for k in self.keys}
        c.update(kw)
        return c

    def test_when_has_one_row_per_stage_even_with_several_cohorts(self):
        rows = self.eng.combined_when(self.counts(file_check=5000, yachbam=300))
        seen = [r["key"] for r in rows]
        self.assertEqual(len(seen), len(set(seen)), "שלב הופיע יותר מפעם אחת")

    def test_when_never_shows_a_stage_that_was_only_entered(self):
        """מי שכבר נמצא בשלב אינו 'מגיע' אליו, ואין לו זמן הגעה."""
        rows = self.eng.combined_when(self.counts(file_check=5000))
        self.assertNotIn("file_check", [r["key"] for r in rows])

    def test_when_counts_match_the_combined_funnel(self):
        counts = self.counts(file_check=5000, screening_day=200)
        combined = self.eng.combine(counts)
        totals = {e["key"]: e["total"] for e in combined["per_stage"]}
        for row in self.eng.combined_when(counts):
            entered = counts.get(row["key"]) or 0
            self.assertEqual(row["count"], totals[row["key"]] - entered, row["key"])

    def test_when_is_ordered_by_time(self):
        rows = self.eng.combined_when(self.counts(file_check=5000, yachbam=300))
        days = [r["days_median"] for r in rows]
        self.assertEqual(days, sorted(days))

    def test_when_days_are_a_weighted_average_of_the_sources(self):
        counts = self.counts(file_check=5000, online_day=800)
        row = next(r for r in self.eng.combined_when(counts) if r["key"] == "hire")
        self.assertTrue(row["weighted"])
        lo = min(x["days_median"] for x in row["sources"])
        hi = max(x["days_median"] for x in row["sources"])
        self.assertGreaterEqual(row["days_median"], lo)
        self.assertLessEqual(row["days_median"], hi)

    def test_when_survives_a_cohort_of_zero(self):
        rows = self.eng.combined_when(self.counts(file_check=0))
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["count"], 0)
            self.assertGreaterEqual(r["days_median"], 0)

    def test_timeline_totals_equal_the_sum_of_the_cohorts(self):
        counts = self.counts(file_check=5000, yachbam=300)
        merged = self.eng.combined_timeline(counts)
        apart = 0
        for c in self.eng.combine(counts)["cohorts"]:
            apart += sum(b["hires"] for b in self.eng.timeline(c["stage"], c["count"]))
        self.assertEqual(merged["total"], apart)

    def test_timeline_has_one_row_per_bucket(self):
        merged = self.eng.combined_timeline(self.counts(file_check=5000, yachbam=300))
        self.assertEqual([r["key"] for r in merged["rows"]],
                         [b["key"] for b in self.eng.buckets])

    def test_timeline_shares_sum_to_one(self):
        merged = self.eng.combined_timeline(self.counts(file_check=5000))
        self.assertAlmostEqual(sum(r["share"] for r in merged["rows"]), 1.0, places=4)

    def test_every_merged_number_records_its_sources(self):
        counts = self.counts(file_check=5000, yachbam=300)
        for row in self.eng.combined_when(counts):
            self.assertTrue(row["sources"], row["key"])
            for src in row["sources"]:
                self.assertIn("from_label", src)
                self.assertIn("from_count", src)
        for row in self.eng.combined_timeline(counts)["rows"]:
            for src in row["sources"]:
                self.assertIn("from_label", src)


class TestPlanning(unittest.TestCase):
    """תכנון מיעד: כמה צריך בכל שלב כדי לגייס X, ומתי."""

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def test_required_plan_covers_every_stage(self):
        plan = self.eng.required_plan(500)
        self.assertEqual([r["key"] for r in plan["rows"]], self.eng.stage_keys())

    def test_required_plan_hits_the_target_from_every_stage(self):
        target = 500
        for row in self.eng.required_plan(target)["rows"]:
            if not row["has_data"]:
                continue
            got = self.eng.project_cohort(row["key"], row["required"])["hires"]
            self.assertAlmostEqual(got, target, delta=1, msg=row["key"])

    def test_required_plan_invents_nothing_for_a_stage_without_data(self):
        row = next(r for r in self.eng.required_plan(500)["rows"]
                   if r["key"] == "submissions")
        self.assertFalse(row["has_data"])
        self.assertIsNone(row["required"])
        self.assertIsNone(row["lead_days_median"])
        self.assertTrue(row["note"])

    def test_required_plan_carries_the_lead_time(self):
        for row in self.eng.required_plan(500)["rows"]:
            if not row["has_data"]:
                continue
            self.assertEqual(row["lead_days_median"],
                             self.eng.stage(row["key"])["days_to_hire"]["median"])

    def test_later_stages_need_fewer_candidates(self):
        rows = [r for r in self.eng.required_plan(500)["rows"] if r["has_data"]]
        needed = [r["required"] for r in rows]
        self.assertEqual(needed, sorted(needed, reverse=True))

    def test_plan_is_exactly_the_forward_projection_of_the_required_amount(self):
        """הבטחה שאפשר לבדוק: הזנת הכמות הנדרשת במחשבון הרגיל נותנת אותו משפך."""
        for key in self.eng.stage_keys(with_data_only=True):
            plan = self.eng.plan_from_target(key, 500)
            self.assertEqual(plan["projection"],
                             self.eng.project_cohort(key, plan["required"]))

    def test_plan_reaches_the_target_within_rounding(self):
        for key in self.eng.stage_keys(with_data_only=True):
            plan = self.eng.plan_from_target(key, 500)
            self.assertAlmostEqual(plan["hires"], 500, delta=1, msg=key)

    def test_plan_reports_the_real_hires_not_the_target(self):
        plan = self.eng.plan_from_target("file_check", 500)
        self.assertEqual(plan["hires"], plan["projection"]["hires"])

    def test_plan_scales_with_the_target(self):
        a = self.eng.plan_from_target("file_check", 100)["required"]
        b = self.eng.plan_from_target("file_check", 1000)["required"]
        self.assertAlmostEqual(b / a, 10, delta=0.05)

    def test_plan_refuses_a_stage_without_data(self):
        self.assertIsNone(self.eng.plan_from_target("submissions", 500))

    def test_planning_returns_single_numbers_not_ranges(self):
        """אין להחזיר טווח משום פונקציה במנוע - בקשה מפורשת של המשתמש."""
        import json
        blobs = [json.dumps(self.eng.required_plan(500), ensure_ascii=False)]
        for key in self.eng.stage_keys(with_data_only=True):
            blobs.append(json.dumps(self.eng.plan_from_target(key, 500),
                                    ensure_ascii=False))
        for blob in blobs:
            self.assertNotIn('"low"', blob)
            self.assertNotIn('"high"', blob)

    def test_no_target_means_no_plan(self):
        self.assertIsNone(self.eng.required_plan(None))
        self.assertIsNone(self.eng.plan_from_target("file_check", None))


if __name__ == "__main__":
    unittest.main()
