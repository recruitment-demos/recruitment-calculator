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

COUNTS = [1, 3, 25, 100, 407, 1000, 12345]
TARGETS = [1, 12, 250, 900]


def node_available():
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def build_scenarios(eng):
    keys = eng.stage_keys()
    with_data = [k for k in keys if eng.has_rate(k)]
    scenarios = []

    for k in keys:
        for c in COUNTS:
            scenarios.append({"op": "project_hires", "stage": k, "count": c})
            scenarios.append({"op": "fill_from", "stage": k, "count": c})
            scenarios.append({"op": "timeline", "stage": k, "count": c})
        for t in TARGETS:
            scenarios.append({"op": "required_for_target", "stage": k, "target": t})

    for a in keys:
        for b in keys:
            for c in COUNTS:
                scenarios.append({"op": "convert", "from": a, "count": c, "to": b})

    # ניתוח פערים: תת-קבוצות של שלבים עם וללא יעד
    for i in range(len(with_data)):
        for j in range(i, len(with_data)):
            counts = {k: None for k in keys}
            counts[with_data[i]] = 900
            counts[with_data[j]] = 300
            for target in (None, 50, 400):
                scenarios.append({"op": "gap_analysis",
                                  "counts": dict(counts), "target": target})

    counts_all = {k: (500 if eng.has_rate(k) else None) for k in keys}
    for target in (None, 1, 120, 5000):
        scenarios.append({"op": "gap_analysis", "counts": dict(counts_all), "target": target})

    return scenarios


def python_result(eng, sc):
    if sc["op"] == "project_hires":
        r = eng.project_hires(sc["stage"], sc["count"])
        return r.as_dict() if r else None
    if sc["op"] == "required_for_target":
        r = eng.required_for_target(sc["stage"], sc["target"])
        return r.as_dict() if r else None
    if sc["op"] == "convert":
        r = eng.convert(sc["from"], sc["count"], sc["to"])
        return r.as_dict() if r else None
    if sc["op"] == "fill_from":
        return eng.fill_from(sc["stage"], sc["count"])
    if sc["op"] == "timeline":
        rows = eng.timeline(sc["stage"], sc["count"])
        if rows is None:
            return None
        return [{"key": r["key"], "label": r["label"], "share": r["share"],
                 "hires": r["hires"].as_dict() if r["hires"] else None} for r in rows]
    if sc["op"] == "gap_analysis":
        return eng.gap_analysis(sc["counts"], sc["target"])
    raise AssertionError("פעולה לא מוכרת: " + sc["op"])


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
