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
    for k in keys:
        scenarios.append({"op": "rate", "stage": k})
        scenarios.append({"op": "forward", "stage": k})
        for c in COUNTS:
            scenarios.append({"op": "project_cohort", "stage": k, "count": c})
            scenarios.append({"op": "timeline", "stage": k, "count": c})
        for t in TARGETS:
            scenarios.append({"op": "required_for_target", "stage": k, "target": t})
            scenarios.append({"op": "plan_from_target", "stage": k, "target": t})

    scenarios.append({"op": "lead_time_anomalies"})

    for t in TARGETS:
        scenarios.append({"op": "required_funnel", "target": t})
        scenarios.append({"op": "required_plan", "target": t})
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
    scenarios.append({"op": "combine", "counts": dict(counts_all)})
    scenarios.append({"op": "cross_check", "counts": dict(counts_all)})
    scenarios.append({"op": "combined_when", "counts": dict(counts_all)})
    scenarios.append({"op": "combined_timeline", "counts": dict(counts_all)})

    # אפסים: המשקל בממוצע המשוקלל מתאפס, ויש לוודא שהמסלול הזה זהה בשניהם
    for k in with_data:
        counts = {x: None for x in keys}
        counts[k] = 0
        scenarios.append({"op": "combined_when", "counts": dict(counts)})
        scenarios.append({"op": "combined_timeline", "counts": dict(counts)})
    counts_zero = {k: (0 if eng.has_rate(k) else None) for k in keys}
    scenarios.append({"op": "combined_when", "counts": dict(counts_zero)})
    scenarios.append({"op": "combined_timeline", "counts": dict(counts_zero)})

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
    if op == "combined_when":
        return eng.combined_when(sc["counts"])
    if op == "combined_timeline":
        return eng.combined_timeline(sc["counts"])
    if op == "lead_time_anomalies":
        return eng.lead_time_anomalies()
    if op == "required_plan":
        return eng.required_plan(sc["target"])
    if op == "plan_from_target":
        return eng.plan_from_target(sc["stage"], sc["target"])
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
