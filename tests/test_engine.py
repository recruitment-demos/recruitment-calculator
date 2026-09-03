"""בדיקות למנוע החישוב ולמאגר הנתונים."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recruit_calc.engine import Engine, load_engine, round_half_up  # noqa: E402

BLANK = "no_source"


def blank_engine():
    """מנוע עם שלב מלאכותי שאין לו מקור נתונים.

    עד שהתקבל קובץ ההגשות, «הגשות» היה השלב חסר הנתונים והבדיקות
    נשענו עליו. עכשיו יש לו מקור, ולכן הכלל «לא לנחש נתונים שאינם
    במקור» נבדק על שלב מלאכותי - כך הוא נאכף גם כשכל השלבים
    האמיתיים מקבלים נתונים.
    """
    import copy
    data = copy.deepcopy(load_engine().data)
    data["stages"].insert(0, {
        "key": BLANK, "label": "שלב ללא מקור", "activity_type": None,
        "has_data": False, "note": "אין מקור נתונים לשלב זה.",
        "hire_rate": None, "days_to_hire": None, "buckets": None,
        "hire_curve": None, "hire_window": None, "basis": None,
        "forward": None,
    })
    return Engine(data)


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

    def test_submissions_stage_is_measured_from_the_source(self):
        """שלב ההגשות קיבל מקור נתונים, ולכן הוא נמדד ככל שלב אחר.

        עד קובץ «הגשות חציון א 2026» לא היה לו מקור והוא סומן
        has_data=false. הכלל שלא לנחש נתונים שאינם במקור נאכף עכשיו
        על שלב מלאכותי, ב-test_a_stage_without_a_source_invents_nothing.
        """
        st = self.eng.stage("submissions")
        self.assertTrue(st["has_data"])
        self.assertTrue(self.eng.has_rate("submissions"))
        self.assertGreater(self.eng.rate("submissions"), 0)
        self.assertTrue(self.eng.forward("submissions"))
        with (ROOT / "config" / "params.json").open(encoding="utf-8") as fh:
            cfg = json.load(fh)
        types = next(x for x in cfg["stages"]
                     if x["key"] == "submissions")["activity_type"]
        self.assertIsInstance(types, list)
        self.assertGreater(len(types), 1)

    def test_a_stage_without_a_source_invents_nothing(self):
        eng = blank_engine()
        self.assertFalse(eng.stage(BLANK)["has_data"])
        self.assertFalse(eng.has_rate(BLANK))
        self.assertIsNone(eng.rate(BLANK))
        self.assertIsNone(eng.forward(BLANK))
        self.assertIsNone(eng.observed_candidates(BLANK))
        self.assertIsNone(eng.project_cohort(BLANK, 500))
        self.assertIsNone(eng.timeline(BLANK, 500))
        self.assertIsNone(eng.required_for_target(BLANK, 50))
        self.assertIsNone(eng.curve_share(BLANK, 30))
        self.assertIsNone(eng.hires_by_day(BLANK, 1000, 30))
        self.assertIsNone(eng.plan_from_target(BLANK, 500))
        self.assertIsNone(eng.required_funnel(400)[BLANK])
        for plan in (eng.required_plan(500), eng.gap_plan({}, 400)):
            row = next(r for r in plan["rows"] if r["key"] == BLANK)
            self.assertFalse(row["has_data"])
            self.assertIsNone(row["required"])
            self.assertIsNone(row["lead_days_median"])
            self.assertTrue(row["note"])
        row = next(r for r in eng.manager_plan({}, 400, 90)["rows"]
                   if r["key"] == BLANK)
        self.assertIsNone(row["required_now"])
        self.assertIsNone(row["required_by"])
        self.assertIsNone(row["deadline_days"])

    def test_a_stage_without_a_source_is_left_out_of_the_projection(self):
        eng = blank_engine()
        counts = {s["key"]: None for s in eng.stages}
        counts[BLANK] = 9999
        counts["yachbam"] = 100
        result = eng.combine(counts)
        self.assertEqual(len(result["cohorts"]), 1)
        for entry in result["per_stage"]:
            self.assertNotEqual(entry["key"], BLANK)

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


class TestDurationFilter(unittest.TestCase):
    """פסילת תצפיות שאינן התקדמות אמיתית במשפך."""

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.data = cls.eng.data
        cls.filt = cls.data["duration_filter"]

    def measured(self):
        return [s for s in self.data["stages"] if s["has_data"]]

    def test_filter_settings_are_in_the_dataset(self):
        """ההגדרות נשמרות בנתונים, כדי שהעמוד יוכל להסביר מה נעשה."""
        for field in ("enabled", "method", "spike_ratio", "bin_days"):
            self.assertIn(field, self.filt)

    def test_every_measured_transition_records_its_window(self):
        for st in self.data["stages"]:
            if not st["has_data"]:
                self.assertIsNone(st["hire_window"], st["key"])
                continue
            self.assertIsNotNone(st["hire_window"], st["key"])
            self.assertTrue(st["hire_window"]["reason"], st["key"])
            for f in st["forward"]:
                self.assertIn("window", f, f"{st['key']} -> {f['key']}")
                self.assertTrue(f["window"]["reason"], f["key"])

    def test_window_records_what_it_dropped(self):
        for st in self.measured():
            w = st["hire_window"]
            self.assertEqual(
                w["observations_after"],
                w["observations_before"] - w["dropped_fast"] - w["dropped_slow"],
                st["key"])
            self.assertEqual(w["observations_after"], st["days_to_hire"]["n"],
                             st["key"])

    def test_a_stage_without_a_floor_drops_nothing(self):
        for st in self.measured():
            w = st["hire_window"]
            if w["from_days"] is None:
                self.assertEqual(w["dropped_fast"], 0, st["key"])
                self.assertEqual(w["observations_after"],
                                 w["observations_before"], st["key"])

    def test_only_the_fast_end_is_cut(self):
        """גיוסים איטיים אמיתיים לעולם אינם נמחקים - זה היה מטה את הזמנים."""
        for st in self.measured():
            self.assertEqual(st["hire_window"]["dropped_slow"], 0, st["key"])
            self.assertIsNone(st["hire_window"]["to_days"], st["key"])

    def test_no_observation_survives_below_its_floor(self):
        for st in self.measured():
            floor = st["hire_window"]["from_days"]
            if floor is None:
                continue
            self.assertGreaterEqual(st["hire_curve"][0][0], floor, st["key"])

    def test_smooth_distributions_are_left_alone(self):
        """יחב\"מ אל גיוס מהיר מטבעו וההתפלגות שם חלקה. אין לחתוך אותה."""
        w = self.eng.stage("yachbam")["hire_window"]
        self.assertIsNone(w["from_days"])
        self.assertEqual(w["dropped_fast"], 0)

    # --- הקריטריון שהמשתמש קבע ---

    def test_no_hire_within_a_week_of_a_file_check(self):
        """דרישה מקצועית: אי אפשר להתגייס תוך שבוע מבדיקת קבצים.

        המשתמש קבע את זה מתוך היכרות עם התהליך, ולא מתוך הנתונים.
        אם קובץ מקור עתידי יחזיר גיוסים כאלה, הבדיקה הזו תיפול ותאלץ
        התייחסות במקום שהמספר ייכנס בשקט.
        """
        self.assertEqual(self.eng.hires_by_day("file_check", 100000, 7), 0)

    def test_the_file_check_floor_is_at_least_a_week(self):
        self.assertGreaterEqual(
            self.eng.stage("file_check")["hire_window"]["from_days"], 7)

    def test_the_sigma_method_is_kept_only_as_a_reference(self):
        """מתועד למה סטיית תקן נפסלה: הרצפה שלה נמוכה משבוע."""
        w = self.eng.stage("file_check")["hire_window"]
        self.assertIsNotNone(w["sigma_floor_days"])
        self.assertLess(w["sigma_floor_days"], 7)
        self.assertGreater(w["from_days"], w["sigma_floor_days"])

    def test_filtering_pushes_timing_out_not_in(self):
        """הסינון מרחיק את הזמנים. זה הכיוון השמרני והבטוח."""
        self.assertGreaterEqual(
            self.eng.stage("file_check")["days_to_hire"]["median"], 71)


class TestHiresByDay(unittest.TestCase):
    """כמה יתגייסו עד יום מסוים - תת-קבוצה של הגיוסים, לא מספר אחר."""

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.keys = cls.eng.stage_keys()

    def counts(self, **kw):
        c = {k: None for k in self.keys}
        c.update(kw)
        return c

    def test_every_stage_with_data_has_a_measured_curve(self):
        for s in self.eng.stages:
            if s["has_data"]:
                self.assertTrue(s["hire_curve"], s["key"])
            else:
                self.assertIsNone(s["hire_curve"], s["key"])

    def test_curve_is_sorted_and_cumulative(self):
        for key in self.eng.stage_keys(with_data_only=True):
            curve = self.eng.stage(key)["hire_curve"]
            days = [d for d, _ in curve]
            shares = [x for _, x in curve]
            self.assertEqual(days, sorted(days), key)
            self.assertEqual(shares, sorted(shares), key)
            self.assertGreater(shares[0], 0, key)
            self.assertAlmostEqual(shares[-1], 1.0, places=4, msg=key)

    def test_curve_agrees_with_the_buckets(self):
        """אימות צולב: העקומה והחלונות נמדדו בנפרד וחייבים להסכים."""
        for key in self.eng.stage_keys(with_data_only=True):
            cum = 0.0
            for b in self.eng.stage(key)["buckets"]:
                cum += b["share"]
                if b["max_days"] is None:
                    continue
                self.assertAlmostEqual(
                    self.eng.curve_share(key, b["max_days"]), cum, places=4,
                    msg=f"{key} ביום {b['max_days']}")

    def test_share_before_the_first_hire_is_zero(self):
        for key in self.eng.stage_keys(with_data_only=True):
            first = self.eng.stage(key)["hire_curve"][0][0]
            self.assertEqual(self.eng.curve_share(key, first - 1), 0.0, key)
            self.assertEqual(self.eng.curve_share(key, -5), 0.0, key)

    def test_share_never_decreases(self):
        for key in self.eng.stage_keys(with_data_only=True):
            prev = -1.0
            for day in range(0, 400, 3):
                got = self.eng.curve_share(key, day)
                self.assertGreaterEqual(got, prev, f"{key} ביום {day}")
                prev = got

    def test_by_day_never_exceeds_the_eventual_hires(self):
        for key in self.eng.stage_keys(with_data_only=True):
            eventual = self.eng.project_cohort(key, 1000)["hires"]
            for day in (0, 7, 30, 90, 365, 5000):
                got = self.eng.hires_by_day(key, 1000, day)
                self.assertLessEqual(got, eventual, f"{key} ביום {day}")

    def test_by_day_reaches_the_eventual_hires_in_the_end(self):
        for key in self.eng.stage_keys(with_data_only=True):
            eventual = self.eng.project_cohort(key, 1000)["hires"]
            self.assertEqual(self.eng.hires_by_day(key, 1000, 100000), eventual, key)

    def test_a_month_is_far_less_than_the_eventual_total(self):
        """המקרה שהמשתמש דיווח עליו: 1,000 בבדיקת קבצים, חודש קדימה."""
        eventual = self.eng.project_cohort("file_check", 1000)["hires"]
        month = self.eng.hires_by_day("file_check", 1000, 30)
        self.assertLess(month, eventual / 2)

    def test_combined_by_day_sums_the_cohorts(self):
        counts = self.counts(file_check=1000, yachbam=300)
        merged = self.eng.combined_by_day(counts, 30)
        apart = (self.eng.hires_by_day("file_check", 1000, 30) +
                 self.eng.hires_by_day("yachbam", 300, 30))
        self.assertEqual(merged["hires"], apart)
        self.assertEqual(merged["eventual"], self.eng.combine(counts)["hires"])

    def test_combined_by_day_records_its_sources(self):
        merged = self.eng.combined_by_day(self.counts(file_check=1000, yachbam=300), 30)
        self.assertEqual(len(merged["sources"]), 2)
        for src in merged["sources"]:
            self.assertIn("from_label", src)
            self.assertIn("eventual", src)
            self.assertLessEqual(src["hires"], src["eventual"])

    def test_no_day_means_no_answer(self):
        self.assertIsNone(self.eng.combined_by_day(self.counts(file_check=1000), None))
        self.assertIsNone(self.eng.hires_by_day("file_check", 1000, None))


class TestGapPlan(unittest.TestCase):
    """כמה עוד צריך, אחרי שסופרים את מי שכבר בתהליך."""

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.keys = cls.eng.stage_keys()

    def counts(self, **kw):
        c = {k: None for k in self.keys}
        c.update(kw)
        return c

    def test_existing_candidates_reduce_the_requirement(self):
        """הטענה המרכזית: לא צריך להתחיל מאפס כשיש כבר מועמדים בדרך."""
        target = 400
        empty = self.eng.gap_plan(self.counts(), target)
        stocked = self.eng.gap_plan(self.counts(yachbam=200), target)
        for a, b in zip(empty["rows"], stocked["rows"]):
            if a["has_data"]:
                self.assertLess(b["required"], a["required"], a["key"])

    def test_with_no_stock_the_gap_plan_equals_the_plain_plan(self):
        plain = self.eng.required_plan(400)
        gap = self.eng.gap_plan(self.counts(), 400)
        for a, b in zip(plain["rows"], gap["rows"]):
            self.assertEqual(a["required"], b["required"], a["key"])

    def test_the_gap_is_the_target_minus_what_is_already_coming(self):
        counts = self.counts(screening_day=300, assessment=150, yachbam=200)
        plan = self.eng.gap_plan(counts, 400)
        self.assertEqual(plan["have"], self.eng.combine(counts)["hires"])
        self.assertEqual(plan["gap"], 400 - plan["have"])

    def test_a_met_target_asks_for_nothing(self):
        plan = self.eng.gap_plan(self.counts(yachbam=1000), 400)
        self.assertLessEqual(plan["gap"], 0)
        for row in plan["rows"]:
            if row["has_data"]:
                self.assertEqual(row["required"], 0, row["key"])

    def test_each_required_amount_closes_exactly_the_gap(self):
        counts = self.counts(yachbam=200)
        plan = self.eng.gap_plan(counts, 400)
        for row in plan["rows"]:
            if not row["has_data"]:
                continue
            added = self.eng.project_cohort(row["key"], row["required"])["hires"]
            self.assertAlmostEqual(plan["have"] + added, 400, delta=2,
                                   msg=row["key"])

    def test_a_deadline_raises_the_requirement(self):
        """מועמד שנכנס עכשיו לא בהכרח יגויס עד התאריך, ולכן צריך יותר."""
        counts = self.counts(yachbam=100)
        far = self.eng.gap_plan(counts, 400, 3650)
        near = self.eng.gap_plan(counts, 400, 60)
        for a, b in zip(far["rows"], near["rows"]):
            if a["has_data"] and a["required"] and b["required"]:
                self.assertGreaterEqual(b["required"], a["required"], a["key"])

    def test_a_stage_that_cannot_deliver_in_time_says_so(self):
        """בדיקת קבצים לא מגייסת תוך 10 ימים, ולכן אינה יכולה לתרום."""
        plan = self.eng.gap_plan(self.counts(), 400, 10)
        row = next(r for r in plan["rows"] if r["key"] == "file_check")
        self.assertFalse(row["in_time"])
        self.assertIsNone(row["required"])

    def test_the_effective_rate_is_the_rate_times_what_arrives_in_time(self):
        plan = self.eng.gap_plan(self.counts(), 400, 90)
        for row in plan["rows"]:
            if not row["has_data"]:
                continue
            self.assertAlmostEqual(
                row["effective_rate"],
                row["rate"] * self.eng.curve_share(row["key"], 90), places=9,
                msg=row["key"])

    def test_the_pipeline_is_the_forward_projection_of_the_requirement(self):
        counts = self.counts(yachbam=100)
        pipe = self.eng.gap_pipeline(counts, 400, "file_check")
        self.assertEqual(pipe["projection"],
                         self.eng.project_cohort("file_check", pipe["required"]))

    def test_the_pipeline_has_no_projection_when_nothing_is_needed(self):
        pipe = self.eng.gap_pipeline(self.counts(yachbam=1000), 400, "file_check")
        self.assertIsNone(pipe["projection"])

    def test_sources_say_where_the_existing_hires_come_from(self):
        counts = self.counts(screening_day=300, yachbam=200)
        plan = self.eng.gap_plan(counts, 400)
        self.assertEqual(len(plan["sources"]), 2)
        for src in plan["sources"]:
            self.assertIn("from_label", src)
            self.assertIn("from_count", src)

    def test_no_target_means_no_plan(self):
        self.assertIsNone(self.eng.gap_plan(self.counts(yachbam=100), None))


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

    def test_lead_time_anomalies_are_detected_not_assumed(self):
        """הזמן עד הגיוס אינו יורד לאורך התהליך, והמערכת מזהה את זה מהנתונים."""
        found = self.eng.lead_time_anomalies()
        ordered = [k for k in self.eng.stage_keys() if self.eng.has_rate(k)]
        expected = 0
        for i in range(1, len(ordered)):
            lead = self.eng.stage(ordered[i])["days_to_hire"]["median"]
            for j in range(i):
                if lead > self.eng.stage(ordered[j])["days_to_hire"]["median"]:
                    expected += 1
        self.assertEqual(len(found), expected)
        for a in found:
            self.assertGreater(a["lead_days_median"], a["earlier_lead_days_median"])

    def test_no_target_means_no_plan(self):
        self.assertIsNone(self.eng.required_plan(None))
        self.assertIsNone(self.eng.plan_from_target("file_check", None))

    # --- התקלה שדווחה: היעד בלבד התעלם מהתאריך ---

    def test_a_deadline_raises_the_requirement_in_target_only_mode(self):
        """«400 גיוסים תוך חודש» החזיר 5,205 בדיקות קבצים - כמות שמניבה
        כ-13 גיוסים בחודש. הדרישה חייבת לגדול כשהזמן קצר."""
        open_ended = self.eng.required_plan(400)
        month = self.eng.required_plan(400, 30)
        for a, b in zip(open_ended["rows"], month["rows"]):
            if not a["has_data"]:
                continue
            if b["required"] is None:
                continue
            self.assertGreater(b["required"], a["required"], a["key"])

    def test_the_old_number_would_not_have_met_the_target(self):
        """אימות ישיר: 5,205 בדיקות קבצים אינן 400 גיוסים תוך חודש."""
        old_answer = self.eng.required_plan(400)["rows"][1]["required"]
        actual = self.eng.hires_by_day("file_check", old_answer, 30)
        self.assertLess(actual, 50)

    def test_the_new_number_does_meet_the_target(self):
        row = next(r for r in self.eng.required_plan(400, 30)["rows"]
                   if r["key"] == "file_check")
        got = self.eng.hires_by_day("file_check", row["required"], 30)
        self.assertAlmostEqual(got, 400, delta=5)

    def test_both_plan_paths_agree(self):
        """required_plan ו-gap_plan בלי מלאי חייבים להיות זהים בכל זמן.

        שני מימושים נפרדים היו הסיבה לתקלה. עכשיו יש עוזר אחד, והבדיקה
        הזו אוכפת שהם לא יתפצלו שוב.
        """
        empty = {k: None for k in self.eng.stage_keys()}
        for days in (None, 10, 30, 122, 400):
            a = self.eng.required_plan(400, days)["rows"]
            b = self.eng.gap_plan(empty, 400, days)["rows"]
            self.assertEqual(a, b, f"days={days}")

    def test_plan_from_target_respects_the_deadline(self):
        open_ended = self.eng.plan_from_target("file_check", 400)
        month = self.eng.plan_from_target("file_check", 400, 30)
        self.assertGreater(month["required"], open_ended["required"])

    def test_a_stage_that_cannot_deliver_returns_no_pipeline(self):
        plan = self.eng.plan_from_target("file_check", 400, 10)
        self.assertIsNone(plan["required"])
        self.assertIsNone(plan["projection"])

    def test_every_stage_reports_the_largest_cohort_ever_measured(self):
        """אמת המידה שמאפשרת לומר שדרישה אינה מעשית."""
        for key in self.eng.stage_keys(with_data_only=True):
            self.assertGreater(self.eng.observed_candidates(key), 0, key)

    def test_the_pipeline_hire_row_answers_the_target_not_the_total(self):
        """התקלה השנייה שדווחה: המשפך הראה 11,716 גיוסים ליעד של 400."""
        plan = self.eng.plan_from_target("file_check", 400, 30)
        self.assertEqual(plan["hires_in_time"], 400)
        self.assertGreater(plan["hires"], plan["hires_in_time"])

    def test_without_a_deadline_both_hire_numbers_agree(self):
        for key in self.eng.stage_keys(with_data_only=True):
            plan = self.eng.plan_from_target(key, 400)
            self.assertEqual(plan["hires"], plan["hires_in_time"], key)

    def test_an_unreachable_target_is_marked_not_feasible(self):
        """400 תוך 30 יום דורש 152,470 בדיקות קבצים - כמות שמעולם לא היתה."""
        row = next(r for r in self.eng.required_plan(400, 30)["rows"]
                   if r["key"] == "file_check")
        self.assertFalse(row["feasible"])
        self.assertGreater(row["required"], row["observed"])

    def test_a_month_is_not_enough_for_a_target_of_400(self):
        """הארגון מגייס כ-300 בחודש, ודרך יחב"מ עוברים כ-12 מועמדים ליום.

        400 גיוסים תוך חודש אינם אפשריים משום שלב, וזו התשובה הנכונה.
        """
        self.assertEqual(self.eng.feasible_stages(400, 30), [])

    def test_a_quarter_is_enough_only_from_the_later_stages(self):
        feasible = self.eng.feasible_stages(400, 90)
        self.assertTrue(feasible)
        self.assertNotIn("submissions", feasible)
        self.assertIn("yachbam", feasible)

    def test_a_far_deadline_is_feasible_from_the_start_of_the_funnel(self):
        self.assertIn("file_check", self.eng.feasible_stages(400, 122))

    def test_an_open_target_is_feasible_everywhere(self):
        self.assertEqual(self.eng.feasible_stages(400),
                         self.eng.stage_keys(with_data_only=True))

    def test_an_open_target_has_no_ceiling_at_all(self):
        """התקלה: יעד שנתי סביר הוחזר כ«לא בר-השגה» בכל שלב.

        הארגון מגייס כ-3,700 בשנה, ו-4,000 בלי מועד הוא יעד לגיטימי.
        הגרסה הקודמת השוותה כל דרישה לכמות שנמדדה ב-229 ימים ופסלה
        אותה. בלי חלון זמן אין תקרה, והמחיר הוא זמן בלבד.
        """
        self.assertEqual(self.eng.feasible_stages(4000),
                         self.eng.stage_keys(with_data_only=True))
        for row in self.eng.required_plan(4000)["rows"]:
            if not row["has_data"]:
                continue
            self.assertIsNotNone(row["required"], row["key"])
            self.assertIsNone(row["capacity"], row["key"])
            self.assertGreater(row["pace_days"], 0, row["key"])

    def test_the_pace_is_the_requirement_at_the_measured_rate(self):
        for t in (400, 4000):
            for row in self.eng.required_plan(t)["rows"]:
                if not row["has_data"]:
                    continue
                self.assertAlmostEqual(
                    row["pace_days"],
                    round(row["required"] / row["observed_per_day"], 1),
                    places=1, msg=row["key"])

    def test_the_capacity_guard_still_catches_the_reported_failure(self):
        """«400 תוך חודש» דרש 152,470 בדיקות קבצים. זה חייב להיפסל.

        זו ההגנה שבגללה כלל הפסילה נולד, והיא נשמרת במלואה: שם יש
        תאריך יעד, ולכן יש תקרה.
        """
        row = next(r for r in self.eng.required_plan(400, 30)["rows"]
                   if r["key"] == "file_check")
        self.assertGreater(row["required"], 100000)
        self.assertFalse(row["feasible"])
        self.assertLess(row["capacity"], 5000)

    def test_a_huge_target_is_feasible_nowhere(self):
        self.assertEqual(self.eng.feasible_stages(100000, 30), [])

    def test_a_feasible_requirement_never_exceeds_what_was_measured(self):
        for days in (None, 30, 122, 400):
            for row in self.eng.required_plan(400, days)["rows"]:
                if row["has_data"] and row["feasible"] and row["required"]:
                    self.assertLessEqual(row["required"], row["observed"],
                                         f"{row['key']} days={days}")

    def test_effective_rate_is_the_rate_when_time_is_open(self):
        for key in self.eng.stage_keys(with_data_only=True):
            self.assertEqual(self.eng.effective_rate(key), self.eng.rate(key), key)


class TestFunnelData(unittest.TestCase):
    """משפך המיון המלא ופילוח הערוצים - נתונים קבועים מהקבצים."""

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.data = cls.eng.data

    def test_funnel_covers_every_stage_and_ends_in_hire(self):
        f = self.data["funnel"]
        keys = [r["key"] for r in f["rows"]]
        self.assertEqual(keys[:-1], self.eng.stage_keys(with_data_only=True))
        self.assertEqual(keys[-1], self.eng.hire_key)
        self.assertTrue(f["rows"][-1]["is_hire"])
        self.assertEqual(f["first_key"], keys[0])

    def test_first_row_has_nothing_before_it(self):
        first = self.data["funnel"]["rows"][0]
        self.assertIsNone(first["from_prev"])
        self.assertIsNone(first["from_first"])

    def test_every_later_row_is_measured_from_both_directions(self):
        for r in self.data["funnel"]["rows"][1:]:
            self.assertIsNotNone(r["from_prev"], r["key"])
            self.assertIsNotNone(r["from_first"], r["key"])
            for m in (r["from_prev"], r["from_first"]):
                self.assertGreater(m["reach"]["mid"], 0, r["key"])
                self.assertGreaterEqual(m["days"]["median"], 0, r["key"])

    def test_from_first_is_not_a_product_of_the_step_rates(self):
        """המשפך אינו סדרתי, ולכן שרשור אחוזים היה מייצר מספר שאינו בנתונים."""
        rows = self.data["funnel"]["rows"]
        chained = 1.0
        for r in rows[1:]:
            chained *= r["from_prev"]["reach"]["mid"]
        measured = rows[-1]["from_first"]["reach"]["mid"]
        self.assertNotAlmostEqual(chained, measured, places=4)

    def test_each_stage_matches_the_engine_it_feeds(self):
        """שיעור המעבר במשפך זהה לזה שהמנוע משתמש בו - מקור אחד לשניהם."""
        rows = {r["key"]: r for r in self.data["funnel"]["rows"]}
        first = self.data["funnel"]["first_key"]
        for f in self.eng.forward(first):
            self.assertEqual(rows[f["key"]]["from_first"]["reach"],
                             f["reach"], f["key"])

    def test_segments_do_not_overlap_and_fit_inside_the_whole(self):
        segs = {g["key"]: g for g in self.data["segments"]}
        whole = segs["all"]["funnel"]["rows"]
        parts = [g for k, g in segs.items() if k != "all" and g["funnel"]]
        self.assertTrue(parts)
        for i, row in enumerate(whole):
            total = sum(g["funnel"]["rows"][i]["candidates"] for g in parts)
            self.assertLessEqual(total, row["candidates"], row["key"])

    def test_every_segment_measures_submission_to_hire_directly(self):
        for g in self.data["segments"]:
            if not g["funnel"]:
                continue
            hire = g["funnel"]["rows"][-1]
            self.assertTrue(hire["is_hire"], g["key"])
            self.assertIsNotNone(hire["from_first"], g["key"])
            self.assertGreater(hire["from_first"]["days"]["n"], 0, g["key"])


class TestCombinedMatrix(unittest.TestCase):
    """טבלה אחת: כמה בכל שלב ומתי."""

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def counts(self, **kw):
        c = {k: None for k in self.eng.stage_keys()}
        c.update(kw)
        return c

    def test_the_windows_always_add_up_to_the_row_total(self):
        """טבלה שלא מסתכמת נראית כמו טעות, ולכן העיגול על הסכום הרץ."""
        for counts in (self.counts(file_check=5000),
                       self.counts(submissions=12345, yachbam=77),
                       self.counts(online_day=1), self.counts(screening_day=3)):
            m = self.eng.combined_matrix(counts)
            for r in m["rows"]:
                self.assertEqual(sum(c["count"] for c in r["cells"]),
                                 r["count"], r["key"])

    def test_the_row_total_matches_the_forward_projection(self):
        m = self.eng.combined_matrix(self.counts(file_check=5000))
        proj = {s["key"]: s["count"]
                for s in self.eng.project_cohort("file_check", 5000)["steps"]}
        for r in m["rows"]:
            self.assertEqual(r["count"], proj[r["key"]], r["key"])

    def test_the_entered_stage_gets_no_row_of_its_own(self):
        """מי שכבר שם אינו «מגיע» לשם ואין לו זמן הגעה."""
        m = self.eng.combined_matrix(self.counts(screening_day=800))
        self.assertNotIn("screening_day", [r["key"] for r in m["rows"]])

    def test_every_row_says_where_it_came_from(self):
        m = self.eng.combined_matrix(self.counts(file_check=900, yachbam=40))
        for r in m["rows"]:
            self.assertTrue(r["sources"], r["key"])
            for src in r["sources"]:
                self.assertIn("from_label", src)
                self.assertIn("from_count", src)

    def test_the_matrix_and_the_single_row_graph_agree(self):
        """אותה טבלה בשתי צורות תצוגה - אסור שיציגו מספרים שונים."""
        counts = self.counts(file_check=5000, yachbam=200)
        by_key = {r["key"]: r for r in self.eng.combined_when(counts)}
        for r in self.eng.combined_matrix(counts)["rows"]:
            self.assertEqual(r["count"], by_key[r["key"]]["count"], r["key"])
            self.assertEqual(r["days_median"], by_key[r["key"]]["days_median"],
                             r["key"])

    def test_spread_never_loses_or_invents_a_candidate(self):
        st = self.eng.stage("file_check")
        for total in (0, 1, 2, 3, 17, 999, 10000):
            for buckets in [st["buckets"]] + [f["buckets"] for f in st["forward"]]:
                cells = self.eng.spread(total, buckets)
                self.assertEqual(sum(c["count"] for c in cells), total)
                self.assertTrue(all(c["count"] >= 0 for c in cells))


class TestManagerPlan(unittest.TestCase):
    """הלוח של מנהלת הגיוס: כמה בכל שלב, ועד מתי."""

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def counts(self, **kw):
        c = {k: None for k in self.eng.stage_keys()}
        c.update(kw)
        return c

    def test_without_a_deadline_both_quantities_are_the_same(self):
        plan = self.eng.manager_plan({}, 400)
        for r in plan["rows"]:
            if not r["has_data"]:
                continue
            self.assertEqual(r["required_by"], r["required_now"], r["key"])
            self.assertIsNone(r["deadline_days"], r["key"])
            self.assertFalse(r["late"], r["key"])

    def test_a_deadline_never_makes_the_standing_quantity_larger(self):
        """«כמה צריך שיעמדו שם» אינו תלוי בזמן - התאריך הוא המחיר."""
        open_ended = self.eng.manager_plan({}, 400)
        timed = self.eng.manager_plan({}, 400, 60)
        for a, b in zip(open_ended["rows"], timed["rows"]):
            if not a["has_data"]:
                continue
            self.assertEqual(a["required_by"], b["required_by"], a["key"])
            self.assertGreaterEqual(b["required_now"] or 0,
                                    a["required_now"], a["key"])

    def test_the_standing_quantity_actually_produces_the_target(self):
        for r in self.eng.manager_plan({}, 400, 200)["rows"]:
            if not r["has_data"] or not r["required_by"]:
                continue
            got = self.eng.project_cohort(r["key"], r["required_by"])["hires"]
            self.assertAlmostEqual(got, 400, delta=1, msg=r["key"])

    def test_the_deadline_is_the_target_minus_the_lead_time(self):
        for r in self.eng.manager_plan({}, 400, 90)["rows"]:
            if not r["has_data"]:
                continue
            self.assertAlmostEqual(r["deadline_days"],
                                   90 - r["lead_days_median"], places=6,
                                   msg=r["key"])
            self.assertEqual(r["late"], r["deadline_days"] < 0, r["key"])

    def test_a_stage_whose_window_has_closed_is_marked_late(self):
        plan = self.eng.manager_plan({}, 400, 5)
        late = [r for r in plan["rows"] if r["has_data"] and r["late"]]
        self.assertTrue(late, "בחמישה ימים אף שלב לא נסגר - בדיקה חסרת ערך")

    def test_existing_candidates_are_deducted(self):
        """יעד יחד עם מלאי קיים = כמה *עוד* צריך."""
        alone = self.eng.manager_plan({}, 400)
        with_stock = self.eng.manager_plan(self.counts(yachbam=300), 400)
        self.assertGreater(with_stock["have"], 0)
        self.assertEqual(with_stock["gap"], 400 - with_stock["have"])
        for a, b in zip(alone["rows"], with_stock["rows"]):
            if not a["has_data"]:
                continue
            self.assertLess(b["required_by"], a["required_by"], a["key"])

    def test_a_target_already_met_asks_for_nothing(self):
        plan = self.eng.manager_plan(self.counts(yachbam=5000), 10)
        self.assertLessEqual(plan["gap"], 0)
        for r in plan["rows"]:
            if not r["has_data"]:
                continue
            self.assertEqual(r["required_by"], 0, r["key"])
            self.assertEqual(r["required_now"], 0, r["key"])

    def test_the_standing_quantity_never_gets_a_ceiling(self):
        """«כמה צריך שיעמדו שם» אינו מוגבל בזמן, ולכן אין לו תקרה.

        המחיר שלו הוא הזמן: pace_days אומר כמה זמן לוקח לצבור אותו
        בקצב הנמדד. פסילה כאן היתה חוזרת על התקלה שבה יעד שנתי סביר
        הוצג כ«לא בר-השגה».
        """
        for target in (400, 4000, 100000):
            for r in self.eng.manager_plan({}, target)["rows"]:
                if not r["has_data"]:
                    continue
                self.assertTrue(r["required_by_feasible"], r["key"])
                self.assertIsNotNone(r["required_by"], r["key"])
                self.assertGreater(r["required_by_pace_days"], 0, r["key"])

    def test_the_time_price_grows_with_the_target(self):
        small = self.eng.manager_plan({}, 400)["rows"]
        big = self.eng.manager_plan({}, 4000)["rows"]
        for a, b in zip(small, big):
            if not a["has_data"]:
                continue
            self.assertGreater(b["required_by_pace_days"],
                               a["required_by_pace_days"], a["key"])

    def test_a_deadline_still_flags_what_cannot_be_done_in_time(self):
        plan = self.eng.manager_plan({}, 400, 30)
        blocked = [r for r in plan["rows"] if r["has_data"] and not r["feasible"]]
        self.assertTrue(blocked)
        for r in blocked:
            self.assertGreater(r["required_now"], r["capacity"], r["key"])

    def test_it_agrees_with_the_gap_plan_it_is_built_on(self):
        """אין חישוב דרישה משוכפל - מקור אמת אחד."""
        counts = self.counts(file_check=2000)
        for days in (None, 30, 122):
            gap = self.eng.gap_plan(counts, 400, days)
            mgr = self.eng.manager_plan(counts, 400, days)
            self.assertEqual(mgr["gap"], gap["gap"])
            for a, b in zip(gap["rows"], mgr["rows"]):
                self.assertEqual(a["required"], b["required_now"], a["key"])




class TestCoverage(unittest.TestCase):
    """כיסוי: איזה חלק מהמגויסים בכלל עבר דרך כל שלב.

    זה מספר נפרד לגמרי משיעור המעבר, והבלבול ביניהם הוא הטעות
    שהמשתמש תפס: 35,711 הגשות מניבות כ-1,145 גיוסים לפי השיעור,
    בעוד שהארגון גייס באותה תקופה 2,328. ההסבר אינו בשיעור אלא
    בכיסוי - רק כמחצית מהמגויסים בכלל נרשמו כהגשה.
    """

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def test_every_measured_stage_reports_its_coverage(self):
        for k in self.eng.stage_keys(with_data_only=True):
            c = self.eng.coverage(k)
            self.assertIsNotNone(c, k)
            self.assertEqual(c["hires"], self.eng.data["meta"]["hire_candidates"])
            self.assertLessEqual(c["overall_n"], c["hires"], k)
            self.assertGreaterEqual(c["overall"], 0, k)
            self.assertLessEqual(c["overall"], 1, k)

    def test_the_covered_window_is_never_worse_than_the_whole(self):
        """נטרול הקטיעה משמאל יכול רק לשפר את הכיסוי, לא להרע אותו."""
        for k in self.eng.stage_keys(with_data_only=True):
            c = self.eng.coverage(k)
            if c["covered"] is None:
                continue
            self.assertGreaterEqual(c["covered"], c["overall"], k)

    def test_a_stage_without_data_has_no_coverage(self):
        eng = blank_engine()
        self.assertIsNone(eng.coverage(BLANK))
        self.assertIsNone(eng.covered_share(BLANK))

    def test_submissions_do_not_cover_the_whole_hire_flow(self):
        """הממצא עצמו, נעול בבדיקה.

        אם קובץ עתידי יכסה את כל הגיוסים, הבדיקה תיפול ותאלץ
        להסיר את האזהרה במקום להשאיר אותה כשהיא כבר לא נכונה.
        """
        share = self.eng.covered_share("submissions")
        self.assertLess(share, 0.75,
                        "ההגשות מכסות עכשיו את רוב הגיוסים - יש לעדכן "
                        "את האזהרה ואת התיעוד")
        self.assertIn("submissions",
                      [c["key"] for c in self.eng.low_coverage()])

    def test_the_warning_fires_only_below_the_configured_floor(self):
        floor = self.eng.coverage_floor
        self.assertIsNotNone(floor)
        flagged = {c["key"] for c in self.eng.low_coverage()}
        for k in self.eng.stage_keys(with_data_only=True):
            share = self.eng.covered_share(k)
            self.assertEqual(k in flagged, share < floor, k)

    def test_a_high_coverage_stage_is_not_flagged(self):
        """יחב"מ מכסה את רוב הגיוסים, ואסור שיקבל אזהרה מיותרת."""
        self.assertGreater(self.eng.covered_share("yachbam"), 0.75)
        self.assertNotIn("yachbam", [c["key"] for c in self.eng.low_coverage()])

    def test_the_funnel_carries_the_same_coverage_as_the_stage(self):
        rows = {r["key"]: r for r in self.eng.data["funnel"]["rows"]}
        for k in self.eng.stage_keys(with_data_only=True):
            self.assertEqual(rows[k]["coverage"]["overall"],
                             self.eng.coverage(k)["overall"], k)




class TestThroughputPlan(unittest.TestCase):
    """כמה צריך שיעברו בכל שלב, לפי היחס בין נפחי המשפך שנמדדו.

    התקלה שהוביל לזה: ל-4,000 גיוסים יצאו 124,778 הגשות, לפי שיעור
    קוהורט של 3.2%. אבל בפועל 35,711 הגשות דרו בכפיפה אחת עם 2,328
    גיוסים, כלומר פי 1.72 מזה הם כ-61 אלף - לא 124 אלף. השיעור
    מכסה רק את מי שיש לו רשומת הגשה, וזה כמחצית מהגיוסים.
    """

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()

    def test_the_measured_funnel_reproduces_itself(self):
        """יעד השווה למה שנמדד חייב להחזיר בדיוק את הנפחים שנמדדו."""
        base = self.eng.data["hire_observed"]["candidates"]
        plan = self.eng.throughput_plan(base)
        self.assertEqual(plan["factor"], 1.0)
        for r in plan["rows"]:
            if r["has_data"]:
                self.assertEqual(r["required"], r["observed"], r["key"])

    def test_it_scales_linearly_with_the_target(self):
        a = self.eng.throughput_plan(2000)
        b = self.eng.throughput_plan(4000)
        for x, y in zip(a["rows"], b["rows"]):
            if x["has_data"]:
                self.assertAlmostEqual(y["required"] / x["required"], 2,
                                       delta=0.01, msg=x["key"])

    def test_it_stands_up_to_what_actually_happened(self):
        """הבדיקה שתופסת את התקלה: הכמות חייבת לעמוד מול המציאות."""
        plan = self.eng.throughput_plan(4000)
        rows = {r["key"]: r for r in plan["rows"]}
        # 35,711 הגשות הניבו 2,328 גיוסים, ולכן 4,000 דורשים כ-61 אלף
        self.assertLess(rows["submissions"]["required"], 70000)
        self.assertGreater(rows["submissions"]["required"], 55000)
        # ולא ייתכן שיידרשו יותר מ-5,000 ביחב"מ כדי לגייס 4,000
        self.assertLess(rows["yachbam"]["required"], 5000)
        self.assertGreater(rows["yachbam"]["required"], 4000)

    def test_the_quantity_does_not_depend_on_the_deadline(self):
        """רק הקצב תלוי בזמן, לא הכמות."""
        base = self.eng.throughput_plan(4000)
        for days in (30, 122, 365, 900):
            timed = self.eng.throughput_plan(4000, days)
            for a, b in zip(base["rows"], timed["rows"]):
                self.assertEqual(a["required"], b["required"], a["key"])

    def test_the_pace_is_the_same_multiple_for_every_stage(self):
        """כל המשפך צריך לרוץ באותו כפל - זו המשמעות של «פי 1.72»."""
        plan = self.eng.throughput_plan(4000, 365)
        paces = {r["pace"] for r in plan["rows"] if r["has_data"]}
        self.assertEqual(len(paces), 1, paces)

    def test_a_longer_window_needs_a_slower_pace(self):
        fast = self.eng.throughput_plan(4000, 180)
        slow = self.eng.throughput_plan(4000, 720)
        for a, b in zip(fast["rows"], slow["rows"]):
            if a["has_data"]:
                self.assertGreater(a["pace"], b["pace"], a["key"])

    def test_the_assessment_centre_is_marked_selective(self):
        """מרכז הערכה - לא כולם עוברים בו, ואסור לקרוא אותו כתחנת חובה."""
        rows = {r["key"]: r for r in self.eng.throughput_plan(4000)["rows"]}
        self.assertTrue(rows["assessment"]["selective"])
        self.assertLess(rows["assessment"]["coverage"], 0.5)
        # ושלב שרוב המגויסים כן עוברים בו אינו מסומן
        self.assertFalse(rows["yachbam"]["selective"])
        self.assertFalse(rows["file_check"]["selective"])

    def test_a_selective_stage_carries_fewer_than_the_stage_before_it(self):
        rows = {r["key"]: r for r in self.eng.throughput_plan(4000)["rows"]}
        self.assertLess(rows["assessment"]["required"],
                        rows["screening_day"]["required"])

    def test_it_disagrees_with_the_cohort_rate_and_that_is_the_point(self):
        """שתי השאלות שונות, ואסור ששתי התשובות יתלכדו בשקט."""
        volume = {r["key"]: r for r in self.eng.throughput_plan(4000)["rows"]}
        cohort = {r["key"]: r for r in self.eng.required_plan(4000)["rows"]}
        self.assertLess(volume["submissions"]["required"],
                        cohort["submissions"]["required"] / 1.5)



class TestConstrainedPlan(unittest.TestCase):
    """המחשבון עם האילוצים: התשובה הראשית לשאלת התכנון.

    המשתמש שלח את «תזרים הליך הגיוס 2025» וקבע שלושה אילוצים:
      1. חלק גדול מהגיוסים אינו עובר בהליך המיון כלל, ולכן אינו נגזר
         מכמות ההגשות.
      2. האוכלוסייה המוכרת אינה ניתנת להגדלה. היא תורמת אותה כמות בכל
         שנה, מתפרסת אחיד על פני השנה.
      3. היחסים בין השלבים - ובראשם הגשה->קבצים - נלקחים מהתרשים, גם
         היכן שרישום הפעילויות סותר אותם.
    """

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.af = cls.eng.annual_flow()

    def test_the_chart_that_was_sent_is_in_the_dataset(self):
        self.assertIsNotNone(self.af)
        self.assertIn("תזרים הליך הגיוס 2025.pptx", self.af["source"])
        self.assertEqual(self.af["chain"][0]["volume"], 59978)
        self.assertEqual(self.af["hires"], 3294)
        self.assertEqual(self.af["known"]["hires_per_year"], 1418)
        self.assertEqual(self.af["new"]["hires_per_year"], 1876)

    def test_the_submission_to_file_ratio_stays_what_the_chart_says(self):
        """האילוץ המפורש: היחס ההגיוני בין הגשה לקבצים נשמר.

        רישום הפעילויות נותן 61.2%, והתרשים נותן 51%. התרשים גובר,
        מפני שהרישום חסר: רק כמחצית מהמגויסים בכלל נרשמו כהגשה.
        """
        top = self.af["chain"][0]
        self.assertAlmostEqual(top["chart_rate_to_next"], 0.51, places=2)
        # ועל האוכלוסייה החדשה בלבד, אחרי הוצאת המוכרת משני הצדדים
        self.assertAlmostEqual(top["rate_to_next"], 0.50, places=2)
        # וזה רחוק ממה שרישום הפעילויות מראה
        measured = self.eng.stage("submissions")["forward"]
        to_files = next(f for f in measured if f["key"] == "file_check")
        self.assertGreater(to_files["reach"]["mid"] - top["rate_to_next"], 0.08)

    def test_the_known_population_is_fixed_and_spread_over_the_year(self):
        """הנתיב המוכר אינו גדל עם היעד, ומתחלק אחיד על פני השנה."""
        year = self.eng.constrained_plan(4000)
        self.assertEqual(year["known"]["hires"], 1418)
        # פי שניים מהיעד לא משנה את הנתיב המוכר
        self.assertEqual(self.eng.constrained_plan(8000)["known"]["hires"], 1418)
        # חצי שנה - חצי מהכמות
        half = self.eng.constrained_plan(4000, 182)
        self.assertEqual(half["known"]["hires"], round_half_up(1418 * 182 / 365))

    def test_only_the_new_population_grows_with_the_target(self):
        a = self.eng.constrained_plan(3294)
        b = self.eng.constrained_plan(4000)
        self.assertEqual(a["known"]["hires"], b["known"]["hires"])
        self.assertGreater(b["new"]["hires"], a["new"]["hires"])
        self.assertEqual(b["new"]["hires"] - a["new"]["hires"], 4000 - 3294)

    def test_the_baseline_year_reproduces_itself(self):
        """יעד השווה לגיוסי 2025 מחזיר בדיוק את נפחי 2025."""
        plan = self.eng.constrained_plan(3294)
        for row in plan["rows"]:
            self.assertAlmostEqual(row["total"] / row["baseline"], 1.0, places=2,
                                   msg=row["key"])
        self.assertAlmostEqual(plan["growth"], 1.0, places=2)

    def test_it_is_not_an_insane_number_of_submissions(self):
        """הבקשה המפורשת: מחשבון כמו שצריך, לא כמות מטורפת של הגשות.

        הגבולות נעולים כאן בכוונה. אם קובץ תזרים עתידי יוציא את
        התוצאה מהם, הבדיקה תיפול ותאלץ התייחסות במקום שהמספר ישתנה
        בשקט.
        """
        plan = self.eng.constrained_plan(4000)
        self.assertGreater(plan["submissions"], 70000)
        self.assertLess(plan["submissions"], 95000)
        # ורחוק מאוד משתי התשובות הקודמות
        self.assertLess(plan["submissions"],
                        self.eng.required_plan(4000)["rows"][0]["required"] / 1.3)
        self.assertGreater(plan["submissions"],
                           self.eng.throughput_plan(4000)["rows"][0]["required"])

    def test_the_submissions_grow_faster_than_the_target(self):
        """זהו כל העניין: הנתיב המוכר אינו גדל, ולכן כל התוספת נופלת
        על הנתיב היחיד שכן גדל. יעד פי 1.21 דורש הגשות פי 1.37."""
        plan = self.eng.constrained_plan(4000)
        self.assertAlmostEqual(plan["target_growth"], 4000 / self.af["hires"],
                               places=2)
        self.assertGreater(plan["growth"], plan["target_growth"])

    def test_both_growths_are_measured_against_the_same_window(self):
        """השוואת חלון קצר לשנה מלאה היתה משווה תפוחים לתפוזים.

        110,892 הגשות ב-119 יום נראו כמו «פי 1.85» מ-59,978 בשנה,
        בעוד שבפועל זהו קצב של פי 5.67. שתי הצמיחות נמדדות מול
        אותו חלון, ולכן היחס ביניהן נשמר בכל אורך זמן.
        """
        year = self.eng.constrained_plan(4000)
        short = self.eng.constrained_plan(4000, 119)
        self.assertEqual(year["growth"], year["rows"][0]["pace"])
        self.assertEqual(short["growth"], short["rows"][0]["pace"])
        self.assertEqual(short["target_growth"], short["rows"][-1]["pace"])
        # החלון הקצר יקר הרבה יותר, ובשני המספרים גם יחד
        self.assertGreater(short["growth"], year["growth"] * 3)
        self.assertGreater(short["target_growth"], year["target_growth"] * 3)
        # ובכל אורך זמן ההגשות גדלות מהר יותר מהגיוסים
        for p in (year, short):
            self.assertGreater(p["growth"], p["target_growth"])

    def test_a_small_target_gets_a_proportional_known_lane(self):
        """התקלה שדווחה: יעד 400 החזיר 1,418 גיוסים.

        הנתיב המוכר היה רצפה קשיחה, ולכן כל יעד שקטן ממנו קיבל אותו
        במלואו. עכשיו הוא חלק יחסי מהיעד - 43%, בדיוק כחלקו בתרשים -
        ולעולם אינו גדול מהיעד עצמו.
        """
        share = self.af["known"]["share_of_hires"]
        for target in (100, 400, 700, 1418, 2000):
            plan = self.eng.constrained_plan(target)
            self.assertLessEqual(plan["known"]["hires"], target, str(target))
            self.assertLessEqual(
                abs(plan["known"]["hires"] - target * share), 0.5, str(target))
            self.assertEqual(plan["known"]["hires"] + plan["new"]["hires"],
                             target, str(target))
            self.assertGreater(plan["rows"][0]["new"], 0, str(target))
        self.assertEqual(self.eng.constrained_plan(400)["submissions"], 7283)

    def test_every_row_splits_into_the_two_lanes_and_they_add_up(self):
        plan = self.eng.constrained_plan(4000)
        for r in plan["rows"]:
            self.assertEqual(r["total"], r["new"] + r["known"], r["key"])
            if r["known_passes"]:
                self.assertEqual(r["known"], plan["known"]["hires"], r["key"])
            else:
                self.assertEqual(r["known"], 0, r["key"])

    def test_the_screening_stations_carry_only_the_new_population(self):
        """האוכלוסייה המוכרת מגיעה ביחס 1:1 - היא אינה עוברת סינון.

        זה מה שהכיסוי שנמדד בקבצים מראה: בדיקת קבצים ויחב"מ מכסים
        כ-90% מהמגויסים, ואילו יום מיון מקוון ומרכז הערכה כמחצית
        ופחות.
        """
        plan = self.eng.constrained_plan(4000)
        by = {r["key"]: r for r in plan["rows"]}
        for k in ("online_day", "screening_day"):
            self.assertEqual(by[k]["known"], 0, k)
        for k in ("submissions", "file_check", "yachbam", "hire"):
            self.assertGreater(by[k]["known"], 0, k)

    def test_the_hire_row_is_exactly_the_target(self):
        for t in (1500, 3294, 4000, 6000):
            plan = self.eng.constrained_plan(t)
            self.assertEqual(plan["rows"][-1]["total"], t, t)

    def test_the_funnel_narrows_all_the_way_down(self):
        """תרשים משפך: כל שלב קטן מזה שלפניו. ללא מרכז הערכה."""
        plan = self.eng.constrained_plan(4000)
        totals = [r["total"] for r in plan["rows"]]
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(len(set(totals)), len(totals))

    def test_the_assessment_centre_is_off_the_chain(self):
        """בקשה מפורשת: מרכז הערכה אינו בתרשים המשפך.

        הוא נשאר במערכת כתחנת צד, אך אינו משתתף בשרשרת החישוב -
        אף שיעור מעבר אינו נגזר דרכו.
        """
        plan = self.eng.constrained_plan(4000)
        self.assertNotIn("assessment", [r["key"] for r in plan["rows"]])
        self.assertEqual([a["key"] for a in plan["aside"]], ["assessment"])
        aside = plan["aside"][0]
        self.assertEqual(aside["after"], "screening_day")
        # והוא באמת גדול מהשלב שאחריו בשרשרת - ולכן היה שובר את המשפך
        by = {r["key"]: r for r in plan["rows"]}
        self.assertGreater(aside["total"], by["yachbam"]["total"])

    def test_the_chain_rates_are_measured_on_the_new_population_only(self):
        """שיעור על הנפח המעורב היה מנפח את המעבר האחרון.

        בתרשים יחב"מ->גיוס הוא 80%, אבל 1,418 מהגיוסים שם לא נמדדו
        ביחב"מ בכלל כחלק מהמשפך. על האוכלוסייה החדשה זה 70%.
        """
        last = self.af["chain"][-1]
        self.assertAlmostEqual(last["chart_rate_to_next"], 0.80, places=2)
        self.assertAlmostEqual(last["rate_to_next"], 0.70, places=2)

    def test_the_quantities_do_not_depend_on_the_window_except_the_known_lane(self):
        """הזמן משנה רק את מה שהנתיב המוכר מספק, ואת הקצב."""
        year = self.eng.constrained_plan(4000)
        half = self.eng.constrained_plan(4000, 182)
        # בחצי שנה הנתיב המוכר נותן פחות, ולכן צריך יותר הגשות
        self.assertGreater(half["submissions"], year["submissions"])
        self.assertLess(half["known"]["hires"], year["known"]["hires"])
        # והקצב הנדרש גבוה בהרבה
        self.assertGreater(half["rows"][0]["pace"], year["rows"][0]["pace"] * 1.8)

    def test_a_window_that_is_not_a_window_returns_nothing(self):
        self.assertIsNone(self.eng.constrained_plan(4000, 0))
        self.assertIsNone(self.eng.constrained_plan(4000, -5))
        self.assertIsNone(self.eng.constrained_plan(None))

    def test_it_replaces_the_two_answers_that_came_before_it(self):
        """שלוש תשובות שונות לאותה שאלה, ואסור שיתלכדו בשקט.

        required_plan מנפח (רק חצי מהגיוסים נרשמו כהגשה),
        throughput_plan מכווץ (הוא מניח שכל הגיוסים גדלים יחד),
        ורק constrained_plan מפריד בין הנתיב שגדל לזה שאינו גדל.
        """
        sub = lambda p: p["rows"][0]["required"]
        cohort = sub(self.eng.required_plan(4000))
        volume = sub(self.eng.throughput_plan(4000))
        constrained = self.eng.constrained_plan(4000)["submissions"]
        self.assertLess(volume, constrained)
        self.assertLess(constrained, cohort)



class TestConstrainedForward(unittest.TestCase):
    """הכיוון ההפוך של המחשבון עם האילוצים.

    התקלה שדווחה: 60,000 הגשות החזירו 1,923 גיוסים - רק המסלול החדש.
    האוכלוסייה המוכרת, 1,418 גיוסים בשנה שאינם עוברים בהליך המיון,
    לא נספרה כלל. המשתמש דרש ששני הכיוונים יעמדו על אותה אריתמטיקה.
    """

    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.keys = [s["key"] for s in cls.eng.stages]

    def counts(self, key, value):
        c = {k: None for k in self.keys}
        c[key] = value
        return c

    def test_the_known_lane_is_counted_and_the_bug_is_gone(self):
        """1,418 המגויסים שאינם עוברים מיון נספרים גם בכיוון הזה."""
        flow = self.eng.constrained_combine(self.counts("submissions", 60000))
        self.assertEqual(flow["known"]["hires"], 1418)
        self.assertEqual(flow["hires"],
                         flow["known"]["hires"] + flow["new"]["hires"])
        # המספר הישן, בלי הנתיב המוכר, היה 1,923
        self.assertGreater(flow["hires"], 3000)
        self.assertLess(flow["hires"], 3600)

    def test_the_two_directions_are_an_exact_inverse(self):
        """הזנת מה שהתכנון החזיר חייבת להחזיר את היעד עצמו.

        מאז שהאוכלוסייה המוכרת יחסית בשני הכיוונים - ולא רצפה קשיחה
        בכיוון אחד ותמהיל יחסי בשני - ההיפוך מדויק בכל יעד ובכל
        חלון זמן, ולא רק היכן שהתקרה נוגעת.
        """
        for target in (100, 400, 1419, 2000, 3294, 4000, 9999):
            for days in (None, 27, 30, 182, 365, 730):
                plan = self.eng.constrained_plan(target, days)
                back = self.eng.constrained_combine(
                    self.counts("submissions", plan["submissions"]), days)
                self.assertLessEqual(
                    abs(back["hires"] - target), 1,
                    f"יעד {target} בחלון {days}: חזר {back['hires']}")

    def test_a_short_window_gets_less_of_the_fixed_lane(self):
        """הנתיב הקבוע מתחלק אחיד, ולכן חלון קצר מקבל ממנו פחות."""
        year = self.eng.constrained_combine(self.counts("submissions", 60000))
        half = self.eng.constrained_combine(
            self.counts("submissions", 60000), 182)
        self.assertLess(half["known"]["hires"], year["known"]["hires"])
        self.assertEqual(half["known"]["hires"], round_half_up(1418 * 182 / 365))

    def test_it_never_derives_backwards(self):
        """מכמות בשלב מסוים לא נגזר דבר על השלבים שלפניו."""
        flow = self.eng.constrained_combine(self.counts("yachbam", 5000))
        self.assertEqual([r["key"] for r in flow["rows"]], ["yachbam", "hire"])
        self.assertEqual(flow["start_key"], "yachbam")

    def test_a_side_station_hangs_on_its_host_without_showing_it(self):
        """מרכז הערכה נתלה על «יום מיון», אך המארח אינו מוצג - הוא מוקדם יותר."""
        flow = self.eng.constrained_combine(self.counts("assessment", 1000))
        self.assertEqual([r["key"] for r in flow["rows"]], ["yachbam", "hire"])
        entry = flow["entries"][0]
        self.assertEqual(entry["via"], "aside")
        self.assertEqual(entry["chain_key"], "screening_day")
        src = [a for a in flow["aside"] if a["is_source"]]
        self.assertEqual(len(src), 1)
        self.assertTrue(src[0]["before_start"])

    def test_a_stage_outside_the_chart_says_so(self):
        """«זימון למבחן מקוון» אינו בתרשים, והגשר אליו נמדד מהקבצים."""
        flow = self.eng.constrained_combine(self.counts("online_invite", 10000))
        entry = flow["entries"][0]
        self.assertEqual(entry["via"], "measured")
        self.assertEqual(entry["chain_key"], "online_day")
        self.assertIsNotNone(entry["via_rate"])
        self.assertEqual([x["key"] for x in flow["extra"]], ["online_invite"])

    def test_a_small_batch_gets_a_proportional_answer(self):
        """התקלה שדווחה: 300 בדיקות קבצים החזירו 1,418 גיוסים.

        הניכוי הקבוע הדביק את כל האוכלוסייה השנתית על 300 מועמדים.
        הפיצול הוא יחסי: 4.64% מהנפח בבדיקת קבצים הם מוכרת, ולכן
        300 כפול שיעור ההמרה המשוקלל 10.77% הם 32 גיוסים.
        """
        self.assertAlmostEqual(self.eng.blended_rate("file_check"), 0.107739,
                               places=5)
        flow = self.eng.constrained_combine(self.counts("file_check", 300))
        self.assertEqual(flow["hires"], 32)
        self.assertLess(flow["known"]["hires"], 20)
        # וגם ביחב"מ, שבו חלק האוכלוסייה המוכרת גדול במיוחד
        self.assertEqual(
            self.eng.constrained_combine(self.counts("yachbam", 500))["hires"],
            402)

    def test_the_blended_rate_is_what_the_chart_shows(self):
        """הזנת הנפח שבתרשים מחזירה את מה שהתרשים אומר על אותו שלב.

        בשלב שהאוכלוסייה המוכרת עוברת בו זהו כל 3,294 הגיוסים; בשלב
        שהיא אינה עוברת בו זהו רק חלקה של האוכלוסייה החדשה. בשני
        המקרים המספר הוא הנפח כפול שיעור ההמרה המשוקלל.
        """
        af = self.eng.annual_flow()
        for row in af["chain"]:
            rate = self.eng.blended_rate(row["key"])
            flow = self.eng.constrained_combine(
                self.counts(row["key"], row["volume"]))
            self.assertLessEqual(
                abs(flow["hires"] - round_half_up(row["volume"] * rate)), 1,
                row["key"])
            expected = af["hires"] if row["known_passes"] else af["new"]["hires_per_year"]
            self.assertLessEqual(abs(flow["hires"] - expected), 1, row["key"])

    def test_the_fixed_lane_has_a_ceiling(self):
        """הנתיב המוכר יחסי, אבל אינו חורג מהיקפו בחלון.

        זו התקרה ששומרת על ההיפוך המדויק: כמות גדולה מהנפח הטבעי
        מקבלת 1,418 בלבד, וכל מה שמעליה נופל על האוכלוסייה החדשה.
        """
        small = self.eng.constrained_combine(self.counts("submissions", 6000))
        self.assertLess(small["known"]["hires"], 200)
        big = self.eng.constrained_combine(self.counts("submissions", 200000))
        self.assertEqual(big["known"]["hires"], 1418)

    def test_the_ceiling_is_enforced_once_for_all_entries(self):
        """האוכלוסייה המוכרת היא אוכלוסייה אחת, ואינה נספרת בכל שלב מחדש."""
        counts = {k: None for k in self.keys}
        counts["submissions"] = 60000
        counts["yachbam"] = 4000
        flow = self.eng.constrained_combine(counts)
        self.assertEqual(flow["known"]["hires"], 1418)

    def test_the_times_come_from_the_files_not_from_the_chart(self):
        """התרשים נושא יחסים בלבד. הזמנים ממשיכים להימדד בקבצים."""
        flow = self.eng.constrained_combine(self.counts("submissions", 60000))
        self.assertEqual(flow["rows"][0]["days_median"], 0.0)
        later = [r for r in flow["rows"] if r["key"] != "submissions"]
        self.assertTrue(all(r["days_median"] > 0 for r in later))
        # הזמן עולה ככל שמתקדמים בשרשרת
        days = [r["days_median"] for r in flow["rows"]]
        self.assertEqual(days, sorted(days))

    def test_what_is_there_plus_the_gap_is_the_whole_plan(self):
        """מה שכבר עובר בשלב ועוד ההשלמה = הדרישה המלאה. בכל שלב."""
        counts = self.counts("submissions", 30000)
        flow = self.eng.constrained_combine(counts)
        gap = self.eng.constrained_gap(counts, 4000)
        self.assertEqual(gap["have"], flow["hires"])
        self.assertEqual(gap["gap"], 4000 - flow["hires"])
        for row in gap["rows"]:
            self.assertEqual(row["have"] + row["required"],
                             row["needed_total"], row["key"])
        # והזנת הסכום חזרה מחזירה בדיוק את היעד
        back = self.eng.constrained_combine(
            self.counts("submissions", 30000 + gap["rows"][0]["required"]))
        self.assertEqual(back["hires"], 4000)

    def test_an_empty_pipeline_asks_for_the_whole_plan(self):
        """בלי שום מלאי, ההשלמה היא בדיוק הדרישה המלאה."""
        gap = self.eng.constrained_gap({k: None for k in self.keys}, 4000)
        plan = self.eng.constrained_plan(4000)
        self.assertEqual(gap["have"], 0)
        self.assertEqual([r["required"] for r in gap["rows"]],
                         [r["total"] for r in plan["rows"][:-1]])

    def test_the_timeline_adds_up_to_the_hires(self):
        """פיזור הגיוסים על הזמן מסתכם בדיוק במספר הגיוסים."""
        for key, n in (("submissions", 60000), ("file_check", 20000),
                       ("yachbam", 6000)):
            for days in (None, 122, 365):
                counts = self.counts(key, n)
                flow = self.eng.constrained_combine(counts, days)
                tl = self.eng.constrained_timeline(counts, days)
                self.assertEqual(sum(r["hires"] for r in tl["rows"]),
                                 tl["total"])
                self.assertEqual(tl["total"], flow["hires"])

    def test_the_fixed_lane_is_spread_evenly_over_the_window(self):
        """הנתיב הקבוע אינו נגזר משלב, ולכן הוא מתחלק לפי אורך החלון."""
        shares = self.eng._uniform_shares(365)
        self.assertAlmostEqual(sum(shares), 1.0, places=9)
        # החלון הארוך ביותר מקבל את הרוב, והקצר ביותר את המעט
        self.assertEqual(max(range(len(shares)), key=lambda i: shares[i]),
                         len(shares) - 1)
        # ובחלון קצר, חלונות שכולם אחריו אינם מקבלים דבר
        short = self.eng._uniform_shares(10)
        self.assertAlmostEqual(sum(short), 1.0, places=9)
        self.assertEqual(short[-1], 0.0)

        # והנתיב הקבוע אכן מופיע בפיזור, כשהוא נוגע בתקרה
        tl = self.eng.constrained_timeline(self.counts("submissions", 59978))
        known_rows = [r for r in tl["rows"]
                      for s in r["sources"] if s["from"] is None]
        self.assertTrue(known_rows)
        self.assertEqual(tl["known"], 1418)

    def test_every_stage_that_can_be_entered_gets_an_answer(self):
        """הדרישה: המחשבון עובד לכל שלב ולכל כיוון."""
        for key in self.eng.stage_keys(True):
            flow = self.eng.constrained_combine(self.counts(key, 20000))
            self.assertIsNotNone(flow, key)
            self.assertGreater(flow["hires"], 0, key)
            self.assertEqual(flow["rows"][-1]["key"], self.eng.hire_key, key)

    def test_a_deadline_shows_what_fits_inside_it(self):
        """עם מועד, מוצג מה שמספיק להתגייס עד אליו - ולא סך הכול."""
        counts = self.counts("submissions", 60000)
        timed = self.eng.constrained_combine(counts, 60)
        self.assertIsNotNone(timed["hires_in_time"])
        self.assertLess(timed["hires_in_time"], timed["hires"])
        # הנתיב הקבוע כולו בתוך החלון, ולכן לעולם לא פחות ממנו
        self.assertGreaterEqual(timed["hires_in_time"], timed["known"]["hires"])
        self.assertIsNone(
            self.eng.constrained_combine(counts, None)["hires_in_time"])

    def test_the_matrix_always_adds_up_to_the_row_total(self):
        """סכום החלונות בשורה שווה בדיוק לסך הכול. אחרת נראה כמו טעות."""
        for key, n in (("submissions", 60000), ("file_check", 20000),
                       ("online_invite", 8000), ("yachbam", 6000)):
            for days in (None, 60, 122, 365):
                m = self.eng.constrained_matrix(self.counts(key, n), days)
                if m is None:
                    continue
                for row in m["rows"]:
                    self.assertEqual(sum(c["count"] for c in row["cells"]),
                                     row["count"], f"{key}/{days}/{row['key']}")

    def test_the_matrix_and_the_funnel_agree(self):
        """הטבלה והמשפך הם אותם מספרים. הם לא יתפצלו בשקט."""
        counts = self.counts("file_check", 20000)
        flow = self.eng.constrained_combine(counts)
        m = self.eng.constrained_matrix(counts)
        by_key = {r["key"]: r["count"] for r in m["rows"]}
        for row in flow["rows"]:
            if row["is_source"] or row["key"] not in by_key:
                continue
            self.assertEqual(by_key[row["key"]], row["total"], row["key"])

    def test_the_entered_stage_has_no_arrival_row(self):
        """מי שכבר נמצא בשלב אינו «מגיע» לשם, ואין לו זמן הגעה."""
        m = self.eng.constrained_matrix(self.counts("submissions", 60000))
        self.assertNotIn("submissions", [r["key"] for r in m["rows"]])
        self.assertIn("hire", [r["key"] for r in m["rows"]])

    def test_the_matrix_is_ordered_by_time(self):
        """השורות מסודרות לפי מתי מגיעים, ולא לפי סדר השלבים בקוד."""
        m = self.eng.constrained_matrix(self.counts("submissions", 60000))
        days = [r["days_median"] for r in m["rows"]]
        self.assertEqual(days, sorted(days))

    def test_the_required_pace_is_the_quantity_over_the_window(self):
        """הקצב הנדרש: כמה מועמדים ביום בכל שלב."""
        plan = self.eng.constrained_plan(4000, 200)
        for row in plan["rows"]:
            self.assertAlmostEqual(row["per_day"], row["total"] / 200, places=2)
        gap = self.eng.constrained_gap({k: None for k in self.keys}, 4000, 200)
        for row in gap["rows"]:
            self.assertAlmostEqual(row["per_day"], row["required"] / 200,
                                   places=2)


if __name__ == "__main__":
    unittest.main()
