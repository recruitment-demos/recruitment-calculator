"""מאות סימולציות על המחשבון, כדי שכל מה שמוזן ייצא הגיוני.

בקשה מפורשת של המשתמש מ-2026-09-03: «תריץ מאות סימולציות תראה שהכל
עובד, כל מה שמזינים שיוצא הגיוני». הבדיקות כאן אינן בודקות ערך אחד
אלא תכונות שחייבות להתקיים בכל התרחישים - מונוטוניות, יחסיות,
היפוך בין שני הכיוונים, וחפיפה לתרשים תזרים הליך הגיוס.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recruit_calc.engine import load_engine  # noqa: E402

TARGETS = [1, 5, 25, 100, 400, 900, 1418, 2000, 3294, 3700, 4000, 6000,
           9999, 25000]
DAYS = [None, 7, 14, 27, 30, 60, 90, 120, 182, 240, 365, 500, 730]
COUNTS = [1, 10, 50, 300, 1000, 5000, 20000, 60000, 82016, 250000]


class TestSimulations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.keys = [s["key"] for s in cls.eng.stages]
        cls.entry_keys = cls.eng.stage_keys(True)
        cls.af = cls.eng.annual_flow()

    def counts(self, key, value):
        c = {k: None for k in self.keys}
        c[key] = value
        return c

    # ------------------------------------------------------------------
    # כיוון א': מיעד לכמות
    # ------------------------------------------------------------------

    def test_every_target_returns_a_plan_that_makes_sense(self):
        """כל שילוב של יעד וחלון זמן מחזיר תשובה סבירה."""
        checked = 0
        for target in TARGETS:
            for days in DAYS:
                plan = self.eng.constrained_plan(target, days)
                self.assertIsNotNone(plan, f"{target}/{days}")
                where = f"יעד {target} בחלון {days}"
                # שני הנתיבים מסתכמים ביעד
                self.assertLessEqual(
                    abs(plan["known"]["hires"] + plan["new"]["hires"] - target),
                    1, where)
                # אף נתיב אינו שלילי ואינו גדול מהיעד
                self.assertGreaterEqual(plan["known"]["hires"], 0, where)
                self.assertGreaterEqual(plan["new"]["hires"], 0, where)
                self.assertLessEqual(plan["known"]["hires"], target + 1, where)
                # המשפך יורד משלב לשלב, וכל שלב גדול מהגיוס
                totals = [r["total"] for r in plan["rows"]]
                self.assertEqual(totals, sorted(totals, reverse=True), where)
                self.assertEqual(totals[-1], target, where)
                self.assertGreater(totals[0], 0, where)
                checked += 1
        self.assertGreater(checked, 150)

    def test_the_known_lane_is_never_a_hard_floor(self):
        """התקלה שדווחה: יעד 400 החזיר 1,418 גיוסים.

        האוכלוסייה המוכרת יחסית ליעד ולעולם אינה גדולה ממנו.
        """
        for target in TARGETS:
            for days in DAYS:
                plan = self.eng.constrained_plan(target, days)
                self.assertLessEqual(
                    plan["known"]["hires"], target,
                    f"יעד {target} בחלון {days} קיבל נתיב מוכר גדול מהיעד")
        small = self.eng.constrained_plan(400)
        self.assertEqual(small["known"]["hires"], 172)
        self.assertEqual(small["new"]["hires"], 228)

    def test_the_known_share_is_the_chart_share_until_the_ceiling(self):
        """עד התקרה החלק היחסי קבוע, ומעליה הוא נשחק."""
        share = self.af["known"]["share_of_hires"]
        ceiling_target = self.af["known"]["hires_per_year"] / share
        for target in TARGETS:
            plan = self.eng.constrained_plan(target)
            got = plan["known"]["hires"] / target
            if target < ceiling_target - 1:
                # סטייה של עד חצי אדם מהעיגול, ולא יותר
                self.assertLessEqual(
                    abs(plan["known"]["hires"] - target * share), 0.5,
                    f"יעד {target}: {plan['known']['hires']} מול "
                    f"{target * share:.1f}")
                self.assertLess(abs(got - share), 0.5 / target + 1e-9,
                                str(target))
            else:
                self.assertLessEqual(plan["known"]["hires"],
                                     self.af["known"]["hires_per_year"])

    def test_more_target_never_needs_fewer_submissions(self):
        """מונוטוניות: יעד גדול יותר לעולם אינו דורש פחות הגשות."""
        for days in DAYS:
            last = -1
            for target in TARGETS:
                subs = self.eng.constrained_plan(target, days)["submissions"]
                self.assertGreaterEqual(subs, last, f"יעד {target}/{days}")
                last = subs

    def test_a_shorter_window_never_needs_fewer_submissions(self):
        """חלון קצר יותר לעולם אינו דורש פחות: הנתיב הקבוע תורם בו פחות."""
        for target in TARGETS:
            last = None
            for days in sorted(d for d in DAYS if d is not None):
                subs = self.eng.constrained_plan(target, days)["submissions"]
                if last is not None:
                    self.assertLessEqual(subs, last + 1,
                                         f"יעד {target} בחלון {days}")
                last = subs

    # ------------------------------------------------------------------
    # כיוון ב': מכמות לגיוסים
    # ------------------------------------------------------------------

    def test_every_stage_and_quantity_returns_something_sane(self):
        """כל שלב, בכל כמות ובכל חלון, מחזיר תשובה סבירה."""
        checked = 0
        for key in self.entry_keys:
            for count in COUNTS:
                for days in (None, 30, 120, 365):
                    flow = self.eng.constrained_combine(
                        self.counts(key, count), days)
                    where = f"{key}={count} בחלון {days}"
                    self.assertIsNotNone(flow, where)
                    # אי אפשר לגייס יותר ממה שנכנס
                    self.assertLessEqual(flow["hires"], count, where)
                    self.assertGreaterEqual(flow["hires"], 0, where)
                    # שני הנתיבים מסתכמים
                    self.assertEqual(
                        flow["known"]["hires"] + flow["new"]["hires"],
                        flow["hires"], where)
                    # המשפך יורד, ושורת הכניסה היא הכמות שהוזנה
                    totals = [r["total"] for r in flow["rows"]]
                    self.assertEqual(totals, sorted(totals, reverse=True), where)
                    self.assertEqual(flow["rows"][-1]["total"],
                                     flow["hires"], where)
                    checked += 1
        self.assertGreater(checked, 200)

    def test_the_answer_is_the_quantity_times_the_blended_rate(self):
        """הדרישה: כמות כפול שיעור ההמרה המשוקלל, בלי מספר קבוע."""
        for key in self.entry_keys:
            rate = self.eng.blended_rate(key)
            if rate is None:
                continue
            share = self.eng.known_share(key) or 0.0
            ceiling = self.af["known"]["hires_per_year"]
            for count in (1, 10, 50, 300, 1000, 5000):
                if count * share > ceiling:
                    # מעל הנפח הטבעי התקרה נוגעת, והשיעור המשוקלל
                    # נשחק בכוונה - שם התשובה קטנה יותר.
                    continue
                flow = self.eng.constrained_combine(self.counts(key, count))
                expected = count * rate
                # סטייה של עד אדם אחד מכל צד של העיגול, ולא יותר
                self.assertLessEqual(
                    abs(flow["hires"] - expected), max(1.5, expected * 0.01),
                    f"{key}={count}: {flow['hires']} מול {expected:.1f}")

    def test_doubling_the_input_never_lowers_the_output(self):
        """מונוטוניות בכיוון ההפוך."""
        for key in self.entry_keys:
            last = -1
            for count in COUNTS:
                hires = self.eng.constrained_combine(
                    self.counts(key, count))["hires"]
                self.assertGreaterEqual(hires, last, f"{key}={count}")
                last = hires

    # ------------------------------------------------------------------
    # שני הכיוונים יחד
    # ------------------------------------------------------------------

    def test_the_round_trip_holds_everywhere(self):
        """הזנת מה שהתכנון החזיר מחזירה את היעד. בכל יעד ובכל חלון.

        זו התוצאה של שני התיקונים יחד: החלק היחסי בשני הכיוונים,
        ותקרה זהה בשניהם.
        """
        checked = 0
        for target in TARGETS:
            for days in DAYS:
                plan = self.eng.constrained_plan(target, days)
                back = self.eng.constrained_combine(
                    self.counts("submissions", plan["submissions"]), days)
                self.assertLessEqual(
                    abs(back["hires"] - target), 2,
                    f"יעד {target} בחלון {days}: חזר {back['hires']}")
                checked += 1
        self.assertGreater(checked, 150)

    def test_the_round_trip_holds_from_every_stage(self):
        """גם מכל שלב אחר: הכמות שהתכנון דורש שם מחזירה את היעד."""
        for target in (400, 1000, 4000, 9999):
            for days in (None, 120, 365):
                plan = self.eng.constrained_plan(target, days)
                for row in plan["rows"][:-1]:
                    back = self.eng.constrained_combine(
                        self.counts(row["key"], row["total"]), days)
                    where = (f"יעד {target}/{days} מ«{row['label']}»: "
                             f"{row['total']} החזירו {back['hires']}")
                    if row["known_passes"]:
                        self.assertLessEqual(abs(back["hires"] - target), 3, where)
                    else:
                        # בשלב שהאוכלוסייה המוכרת אינה עוברת בו אי אפשר
                        # לשחזר ממנו את חלקה - היא מגיעה בדרך אחרת.
                        # מה שכן חייב לחזור הוא כל האוכלוסייה החדשה.
                        self.assertLessEqual(
                            abs(back["hires"] - plan["new"]["hires"]), 3, where)

    def test_the_gap_always_closes(self):
        """מה שכבר יש ועוד ההשלמה מחזיר בדיוק את היעד."""
        for key in ("submissions", "file_check", "yachbam"):
            for have in (0, 100, 1000, 20000):
                for target in (400, 2000, 4000):
                    counts = self.counts(key, have) if have else \
                        {k: None for k in self.keys}
                    gap = self.eng.constrained_gap(counts, target)
                    where = f"{key}={have} ליעד {target}"
                    if gap["gap"] <= 0:
                        # היעד כבר מושג. אין השלמה, והכרטיס אומר זאת
                        # במקום להציג שורות.
                        self.assertTrue(all(r["required"] == 0
                                            for r in gap["rows"]), where)
                        continue
                    for row in gap["rows"]:
                        # כשכבר עוברים שם יותר מהנדרש, ההשלמה היא אפס
                        self.assertEqual(
                            row["have"] + row["required"],
                            max(row["have"], row["needed_total"]), where)
                    if gap["gap"] > 0:
                        total = gap["rows"][0]["have"] + gap["rows"][0]["required"]
                        back = self.eng.constrained_combine(
                            self.counts("submissions", total))
                        self.assertLessEqual(abs(back["hires"] - target), 2,
                                             where)

    # ------------------------------------------------------------------
    # חפיפה לתרשים
    # ------------------------------------------------------------------

    def test_the_chart_reproduces_itself_in_both_directions(self):
        """הנפחים של התרשים חייבים לחזור על עצמם, לשני הכיוונים."""
        plan = self.eng.constrained_plan(self.af["hires"])
        for row, chart in zip(plan["rows"], self.af["chain"]):
            self.assertLessEqual(abs(row["total"] - chart["volume"]), 2,
                                 chart["key"])
        for chart in self.af["chain"]:
            flow = self.eng.constrained_combine(
                self.counts(chart["key"], chart["volume"]))
            expected = (self.af["hires"] if chart["known_passes"]
                        else self.af["new"]["hires_per_year"])
            self.assertLessEqual(abs(flow["hires"] - expected), 2, chart["key"])

    def test_the_two_column_funnel_matches_the_chart(self):
        """המשפך שבתחתית העמוד הוא התרשים עצמו, בשתי קריאות."""
        f = self.eng.flow_funnel()
        chart = list(self.af["chain"]) + [self.af["hire_row"]]
        for row, c in zip(f["rows"], chart):
            self.assertEqual(row["all"]["count"], c["volume"], c["key"])
            self.assertEqual(row["new"]["count"], c["new"], c["key"])
            # העמודה עם המוכרת אינה קטנה מזו שבלעדיה
            self.assertGreaterEqual(row["all"]["count"], row["new"]["count"])
        # בשלבי המיון עצמם שתי העמודות זהות: המוכרת אינה עוברת שם
        for row in f["rows"]:
            if not row["known_passes"]:
                self.assertEqual(row["all"]["count"], row["new"]["count"],
                                 row["key"])

    def test_nothing_returns_a_negative_or_absurd_number(self):
        """סריקה רחבה: אין מספר שלילי ואין שיעור מחוץ לתחום."""
        for key in self.entry_keys:
            for count in COUNTS:
                for days in (None, 30, 365):
                    flow = self.eng.constrained_combine(
                        self.counts(key, count), days)
                    for row in flow["rows"]:
                        self.assertGreaterEqual(row["total"], 0)
                        self.assertGreaterEqual(row["new"], 0)
                        self.assertGreaterEqual(row["known"], 0)
                        if row["rate_to_next"] is not None:
                            self.assertGreater(row["rate_to_next"], 0)
                            self.assertLessEqual(row["rate_to_next"], 1)
                    m = self.eng.constrained_matrix(self.counts(key, count), days)
                    if m:
                        for row in m["rows"]:
                            self.assertEqual(
                                sum(c["count"] for c in row["cells"]),
                                row["count"], f"{key}/{count}/{row['key']}")


if __name__ == "__main__":
    unittest.main()
