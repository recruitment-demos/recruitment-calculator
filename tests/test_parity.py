"""ודא ששני מנועי החישוב מחזירים בדיוק אותן תוצאות.

יש לוגיקת חישוב פעמיים: ב-recruit_calc/engine.py וב-JS שבתוך
web/template.html. הבדיקה הזו מריצה את שניהם על אותם תרחישים ומשווה.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recruit_calc.engine import load_engine  # noqa: E402

COUNTS = [1, 3, 7, 25, 100, 407, 999, 1000, 12345, 50000]
TARGETS = [1, 12, 250, 900, 4321]
# ימים: לפני העקומה, על נקודות מדויקות, באמצע חלונות, ומעבר לסופה
DAYS = [-5, 0, 1, 7, 14, 15, 30, 31, 45, 60, 71, 90, 120, 200, 365, 5000]


def node_available():
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def build_scenarios(eng):
    keys = eng.stage_keys()
    with_data = [k for k in keys if eng.has_rate(k)]
    hire = eng.hire_key
    scenarios = []

    for k in keys + [hire]:
        scenarios.append({"op": "label", "stage": k})
    scenarios.append({"op": "low_coverage"})
    for k in keys:
        scenarios.append({"op": "rate", "stage": k})
        scenarios.append({"op": "coverage", "stage": k})
        scenarios.append({"op": "covered_share", "stage": k})
        scenarios.append({"op": "observed_candidates", "stage": k})
        scenarios.append({"op": "observed_per_day", "stage": k})
        for d in DAYS + [None]:
            scenarios.append({"op": "capacity", "stage": k, "days": d})
        for c in COUNTS:
            scenarios.append({"op": "pace_days", "stage": k, "required": c})
        scenarios.append({"op": "low_coverage", "keys": [k]})
        scenarios.append({"op": "forward", "stage": k})
        for d in DAYS:
            scenarios.append({"op": "curve_share", "stage": k, "days": d})
        for c in COUNTS:
            scenarios.append({"op": "project_cohort", "stage": k, "count": c})
            scenarios.append({"op": "timeline", "stage": k, "count": c})
            for d in DAYS:
                scenarios.append({"op": "hires_by_day", "stage": k,
                                  "count": c, "days": d})
        for t in TARGETS:
            scenarios.append({"op": "required_for_target", "stage": k, "target": t})
            for d in (None, 10, 30, 122, 400):
                scenarios.append({"op": "plan_from_target", "stage": k,
                                  "target": t, "days": d})

    scenarios.append({"op": "lead_time_anomalies"})

    for t in TARGETS:
        scenarios.append({"op": "required_funnel", "target": t})
        for d in (None, 10, 30, 122, 365, 400):
            scenarios.append({"op": "throughput_plan", "target": t, "days": d})
            scenarios.append({"op": "constrained_plan", "target": t, "days": d})
        for d in (None, 10, 30, 122, 400):
            scenarios.append({"op": "required_plan", "target": t, "days": d})
            scenarios.append({"op": "feasible_stages", "target": t, "days": d})
        for projected in (0, t - 1, t, t + 1, t * 3):
            scenarios.append({"op": "target_verdict", "projected": projected, "target": t})

    # קבוצה אחת בכל שלב
    for k in with_data:
        for c in COUNTS:
            counts = {x: None for x in keys}
            counts[k] = c
            scenarios.append({"op": "combine", "counts": dict(counts)})
            scenarios.append({"op": "cross_check", "counts": dict(counts)})
            scenarios.append({"op": "combined_when", "counts": dict(counts)})
            scenarios.append({"op": "combined_timeline", "counts": dict(counts)})
            scenarios.append({"op": "combined_matrix", "counts": dict(counts)})
            for d in (None, 10, 30, 122, 365, 400):
                scenarios.append({"op": "constrained_combine",
                                  "counts": dict(counts), "days": d})
                scenarios.append({"op": "constrained_timeline",
                                  "counts": dict(counts), "days": d})
                scenarios.append({"op": "constrained_matrix",
                                  "counts": dict(counts), "days": d})
            for t in TARGETS:
                for d in (None, 10, 30, 122, 400):
                    scenarios.append({"op": "manager_plan", "counts": dict(counts),
                                      "target": t, "days": d})
                    scenarios.append({"op": "constrained_gap", "counts": dict(counts),
                                      "target": t, "days": d})
            for d in DAYS:
                scenarios.append({"op": "combined_by_day",
                                  "counts": dict(counts), "days": d})
            for t in TARGETS:
                for d in (None, 30, 122, 400):
                    scenarios.append({"op": "gap_plan", "counts": dict(counts),
                                      "target": t, "days": d})
                    scenarios.append({"op": "gap_pipeline", "counts": dict(counts),
                                      "target": t, "stage": k, "days": d})

    # כמה קבוצות יחד
    for i in range(len(with_data)):
        for j in range(i + 1, len(with_data)):
            for a, b in ((900, 300), (50, 700), (5000, 12)):
                counts = {x: None for x in keys}
                counts[with_data[i]] = a
                counts[with_data[j]] = b
                scenarios.append({"op": "combine", "counts": dict(counts)})
                scenarios.append({"op": "cross_check", "counts": dict(counts)})
                scenarios.append({"op": "combined_when", "counts": dict(counts)})
                scenarios.append({"op": "combined_timeline", "counts": dict(counts)})
                scenarios.append({"op": "combined_matrix", "counts": dict(counts)})
                scenarios.append({"op": "manager_plan", "counts": dict(counts),
                                  "target": 400, "days": 122})
                for d in (None, 122, 365):
                    scenarios.append({"op": "constrained_combine",
                                      "counts": dict(counts), "days": d})
                    scenarios.append({"op": "constrained_timeline",
                                      "counts": dict(counts), "days": d})
                    scenarios.append({"op": "constrained_matrix",
                                      "counts": dict(counts), "days": d})
                    scenarios.append({"op": "constrained_gap", "counts": dict(counts),
                                      "target": 4000, "days": d})
                for d in DAYS:
                    scenarios.append({"op": "combined_by_day",
                                      "counts": dict(counts), "days": d})

    # מקרי גבול של סף העקביות: בדיוק הכמות הצפויה ומעט סביבה
    for a in with_data:
        proj = eng.project_cohort(a, 1000)
        for step in proj["steps"]:
            if step["is_source"] or step["is_hire"]:
                continue
            for delta in (-0.06, -0.01, 0, 0.01, 0.06):
                counts = {x: None for x in keys}
                counts[a] = 1000
                counts[step["key"]] = max(0, round(step["count"] * (1 + delta)))
                scenarios.append({"op": "cross_check", "counts": dict(counts)})
                scenarios.append({"op": "combine", "counts": dict(counts)})

    # כל השלבים יחד, וגם שלב ללא נתונים
    counts_all = {k: (500 if eng.has_rate(k) else 999) for k in keys}
    for d in (None, -1, 0, 30, 365):
        scenarios.append({"op": "constrained_combine",
                          "counts": dict(counts_all), "days": d})
        scenarios.append({"op": "constrained_timeline",
                          "counts": dict(counts_all), "days": d})
        scenarios.append({"op": "constrained_matrix",
                          "counts": dict(counts_all), "days": d})
        scenarios.append({"op": "constrained_gap", "counts": dict(counts_all),
                          "target": 4000, "days": d})
    scenarios.append({"op": "combine", "counts": dict(counts_all)})
    scenarios.append({"op": "cross_check", "counts": dict(counts_all)})
    scenarios.append({"op": "combined_when", "counts": dict(counts_all)})
    scenarios.append({"op": "combined_timeline", "counts": dict(counts_all)})
    scenarios.append({"op": "combined_matrix", "counts": dict(counts_all)})

    # פיזור על חלונות הזמן: עיגול על הסכום הרץ חייב להיות זהה בשני המנועים
    for k in with_data:
        st = eng.stage(k)
        for total in (0, 1, 3, 7, 99, 1000, 12345):
            scenarios.append({"op": "spread", "total": total,
                              "buckets": st["buckets"]})
            for f in st["forward"]:
                scenarios.append({"op": "spread", "total": total,
                                  "buckets": f.get("buckets")})
    # יעד שכבר הושג, יעד שווה בדיוק, ויעד רחוק - שלושת המסלולים בפער
    for t in (1, 100, 5000):
        for d in (None, 10, 122):
            scenarios.append({"op": "gap_plan", "counts": dict(counts_all),
                              "target": t, "days": d})
            scenarios.append({"op": "manager_plan", "counts": dict(counts_all),
                              "target": t, "days": d})
            for k in with_data:
                scenarios.append({"op": "gap_pipeline", "counts": dict(counts_all),
                                  "target": t, "stage": k, "days": d})

    # אפסים: המשקל בממוצע המשוקלל מתאפס, ויש לוודא שהמסלול הזה זהה בשניהם
    for k in with_data:
        counts = {x: None for x in keys}
        counts[k] = 0
        scenarios.append({"op": "combined_when", "counts": dict(counts)})
        scenarios.append({"op": "combined_timeline", "counts": dict(counts)})
    counts_zero = {k: (0 if eng.has_rate(k) else None) for k in keys}
    scenarios.append({"op": "combined_when", "counts": dict(counts_zero)})
    scenarios.append({"op": "combined_timeline", "counts": dict(counts_zero)})

    # המחשבון עם האילוצים: יעד מתחת לנתיב המוכר, בדיוק עליו, ומעליו,
    # ובחלונות זמן שונים - כולל חלון לא חוקי.
    for t in (0, 1, 700, 1418, 1419, 3294, 4000, 9999):
        for d in (None, -1, 0, 1, 30, 122, 182, 365, 730):
            scenarios.append({"op": "constrained_plan", "target": t, "days": d})
            scenarios.append({"op": "constrained_gap", "counts": {}, "target": t,
                              "days": d})

    # הכיוון ההפוך: כמות בכל שלב, כולל כמות שקטנה מהנתיב המוכר וכמות
    # שאינה על השרשרת כלל
    for k in keys:
        for c in (0, 1, 700, 1418, 5000, 60000, 82016):
            for d in (None, -1, 0, 30, 122, 365, 730):
                counts = {x: None for x in keys}
                counts[k] = c
                scenarios.append({"op": "constrained_entry", "stage": k,
                                  "count": c, "days": d})
                scenarios.append({"op": "constrained_combine",
                                  "counts": dict(counts), "days": d})
                scenarios.append({"op": "constrained_timeline",
                                  "counts": dict(counts), "days": d})
                scenarios.append({"op": "constrained_matrix",
                                  "counts": dict(counts), "days": d})
                scenarios.append({"op": "constrained_gap", "counts": dict(counts),
                                  "target": 4000, "days": d})

    return scenarios


def python_result(eng, sc):
    op = sc["op"]
    if op == "label":
        return eng.label(sc["stage"])
    if op == "rate":
        return eng.rate(sc["stage"])
    if op == "forward":
        return eng.forward(sc["stage"])
    if op == "project_cohort":
        return eng.project_cohort(sc["stage"], sc["count"])
    if op == "timeline":
        return eng.timeline(sc["stage"], sc["count"])
    if op == "combine":
        return eng.combine(sc["counts"])
    if op == "cross_check":
        return eng.cross_check(sc["counts"])
    if op == "curve_share":
        return eng.curve_share(sc["stage"], sc["days"])
    if op == "hires_by_day":
        return eng.hires_by_day(sc["stage"], sc["count"], sc["days"])
    if op == "combined_by_day":
        return eng.combined_by_day(sc["counts"], sc["days"])
    if op == "combined_when":
        return eng.combined_when(sc["counts"])
    if op == "combined_timeline":
        return eng.combined_timeline(sc["counts"])
    if op == "observed_per_day":
        return eng.observed_per_day(sc["stage"])
    if op == "capacity":
        return eng.capacity(sc["stage"], sc["days"])
    if op == "pace_days":
        return eng.pace_days(sc["stage"], sc["required"])
    if op == "observed_candidates":
        return eng.observed_candidates(sc["stage"])
    if op == "coverage":
        return eng.coverage(sc["stage"])
    if op == "covered_share":
        return eng.covered_share(sc["stage"])
    if op == "low_coverage":
        return eng.low_coverage(sc.get("keys"))
    if op == "combined_matrix":
        return eng.combined_matrix(sc["counts"])
    if op == "spread":
        return eng.spread(sc["total"], sc["buckets"])
    if op == "constrained_plan":
        return eng.constrained_plan(sc["target"], sc.get("days"))
    if op == "constrained_entry":
        return eng.constrained_entry(sc["stage"], sc["count"], sc.get("days"))
    if op == "constrained_combine":
        return eng.constrained_combine(sc["counts"], sc.get("days"))
    if op == "constrained_gap":
        return eng.constrained_gap(sc["counts"], sc["target"], sc.get("days"))
    if op == "constrained_timeline":
        return eng.constrained_timeline(sc["counts"], sc.get("days"))
    if op == "constrained_matrix":
        return eng.constrained_matrix(sc["counts"], sc.get("days"))
    if op == "throughput_plan":
        return eng.throughput_plan(sc["target"], sc.get("days"))
    if op == "manager_plan":
        return eng.manager_plan(sc["counts"], sc["target"], sc.get("days"))
    if op == "lead_time_anomalies":
        return eng.lead_time_anomalies()
    if op == "feasible_stages":
        return eng.feasible_stages(sc["target"], sc.get("days"))
    if op == "gap_plan":
        return eng.gap_plan(sc["counts"], sc["target"], sc["days"])
    if op == "gap_pipeline":
        return eng.gap_pipeline(sc["counts"], sc["target"], sc["stage"], sc["days"])
    if op == "required_plan":
        return eng.required_plan(sc["target"], sc.get("days"))
    if op == "plan_from_target":
        return eng.plan_from_target(sc["stage"], sc["target"], sc.get("days"))
    if op == "required_for_target":
        return eng.required_for_target(sc["stage"], sc["target"])
    if op == "required_funnel":
        return eng.required_funnel(sc["target"])
    if op == "target_verdict":
        return eng.target_verdict(sc["projected"], sc["target"])
    raise AssertionError("פעולה לא מוכרת: " + op)


@unittest.skipUnless(node_available(), "node אינו מותקן")
class TestParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = load_engine()
        cls.scenarios = build_scenarios(cls.eng)

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump(cls.scenarios, fh, ensure_ascii=False)
            path = fh.name

        proc = subprocess.run(
            ["node", str(ROOT / "tests" / "parity_check.js"), path],
            capture_output=True, text=True,
        )
        Path(path).unlink(missing_ok=True)
        if proc.returncode != 0:
            raise AssertionError("הרצת מנוע ה-JS נכשלה:\n" + proc.stderr)
        cls.js_results = json.loads(proc.stdout)

    def test_same_number_of_results(self):
        self.assertEqual(len(self.js_results), len(self.scenarios))

    def test_all_scenarios_match(self):
        self.assertGreater(len(self.scenarios), 500,
                           "צריך כיסוי משמעותי של תרחישים")
        mismatches = []
        for sc, js in zip(self.scenarios, self.js_results):
            py = python_result(self.eng, sc)
            if json.loads(json.dumps(py, ensure_ascii=False)) != js:
                mismatches.append((sc, py, js))
        if mismatches:
            sc, py, js = mismatches[0]
            self.fail(
                f"{len(mismatches)} אי-התאמות בין המנועים. הראשונה:\n"
                f"  תרחיש: {json.dumps(sc, ensure_ascii=False)}\n"
                f"  פייתון: {json.dumps(py, ensure_ascii=False)}\n"
                f"  JS:     {json.dumps(js, ensure_ascii=False)}"
            )

    def test_built_pages_are_current(self):
        """שני קובצי הפלט זהים זה לזה ומעודכנים מול התבנית והנתונים."""
        sys.path.insert(0, str(ROOT / "tools"))
        import build_web

        expected = build_web.render()
        a = (ROOT / "index.html").read_text(encoding="utf-8")
        b = (ROOT / "מחשבון גיוס.html").read_text(encoding="utf-8")
        self.assertEqual(a, b, "שני קובצי הפלט אינם זהים - יש להריץ make")
        self.assertEqual(a, expected, "קובצי הפלט אינם מעודכנים - יש להריץ make")
        self.assertNotIn("__DATA__", a, "הנתונים לא הוזרקו לעמוד")


if __name__ == "__main__":
    unittest.main()
