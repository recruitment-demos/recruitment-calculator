"""מנוע החישוב של מחשבון הגיוס.

הלוגיקה כאן חייבת להישאר זהה ללוגיקה שב-web/template.html.
tests/test_parity.py מוודא שהשניים מחזירים את אותן תוצאות.

עקרונות
-------
1. גזירה קדימה בלבד. מספר שהוזן בשלב מסוים מייצג קבוצת מועמדים שנמצאת
   *עכשיו* באותו שלב. מהקבוצה הזו נגזר כמה מהם יגיעו לכל שלב מאוחר יותר
   ומתי, וכמה מהם יגויסו ומתי. לא נגזר מהם כמה היו בשלבים מוקדמים יותר -
   זה מידע שאין לנו.

2. כל מעבר נמדד ישירות מהנתונים. שיעור ההגעה משלב S לשלב T הוא החלק
   מהמועמדים שהיו ב-S והגיעו בפועל ל-T אחר כך. לא מכפלה של אחוזי מעבר
   ולא יחס של יחסים - מדידה ישירה של הזוג הזה.

3. כל תוצאה היא מספר יחיד. כל שיעור נמדד בשני בסיסים, והערך שבשימוש הוא
   הממוצע ביניהם. שני הבסיסים נשמרים ב-data/recruitment_data.json.

4. כמה שלבים שהוזנו = כמה קבוצות נפרדות. כל קבוצה נגזרת בנפרד, והתוצאה
   הסופית מציגה במפורש כמה תרמה כל קבוצה. אם הקבוצות חופפות, המשתמש
   מקבל אזהרה מפורשת - המערכת לא מנחשת אם הן חופפות או לא.

5. שלב שאין לו נתונים במקור («הגשות») אינו מקבל שיעור משוער. כל בקשה
   לחשב דרכו מחזירה None עם הסבר, ולא ניחוש.
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "recruitment_data.json"


def round_half_up(x):
    """עיגול שמתנהג זהה בפייתון וב-JS.

    round() המובנה בפייתון מעגל חצי לזוגי, ו-Math.round ב-JS מעגל חצי
    כלפי מעלה. הפונקציה הזו מבטיחה שהשניים לא יתפצלו על ערכי .5.
    כל הערכים במערכת אינם שליליים.
    """
    return int(math.floor(x + 0.5))


class Engine:
    def __init__(self, dataset):
        self.data = dataset
        self.stages = dataset["stages"]
        self.by_key = {s["key"]: s for s in self.stages}
        self.buckets = dataset["time_buckets"]
        self.tolerance = dataset["gap_tolerance"]
        self.hire_key = dataset["hire_key"]
        self.hire_label = dataset["hire_label"]

    # ------------------------------------------------------------------
    # עזר
    # ------------------------------------------------------------------

    def stage(self, key):
        if key not in self.by_key:
            raise KeyError(f"שלב לא מוכר: {key}")
        return self.by_key[key]

    def has_rate(self, key):
        s = self.stage(key)
        return s["has_data"] and s["hire_rate"] is not None

    def rate(self, key):
        """יחס הגיוס שבשימוש: ממוצע שני בסיסי המדידה."""
        if not self.has_rate(key):
            return None
        return self.stage(key)["hire_rate"]["mid"]

    def label(self, key):
        return self.hire_label if key == self.hire_key else self.stage(key)["label"]

    def stage_keys(self, with_data_only=False):
        return [s["key"] for s in self.stages
                if not with_data_only or (s["has_data"] and s["hire_rate"])]

    def forward(self, key):
        """שלבי ההמשך של שלב, לפי סדר הזמן שנמדד. כולל את הגיוס בסוף."""
        if not self.has_rate(key):
            return None
        return self.stage(key)["forward"]

    # ------------------------------------------------------------------
    # גזירה קדימה מקבוצה אחת
    # ------------------------------------------------------------------

    def project_cohort(self, key, count):
        """מקבוצת מועמדים בשלב אחד - כמה יגיעו לכל שלב המשך ומתי.

        השלב עצמו הוא הצעד הראשון, ביום 0, עם כל הכמות שהוזנה.
        """
        if count is None or not self.has_rate(key):
            return None

        steps = [{
            "key": key,
            "label": self.stage(key)["label"],
            "count": count,
            "reach": 1.0,
            "days_median": 0.0,
            "days_mean": 0.0,
            "is_source": True,
            "is_hire": False,
        }]

        for f in self.forward(key):
            steps.append({
                "key": f["key"],
                "label": f["label"],
                "count": round_half_up(count * f["reach"]["mid"]),
                "reach": f["reach"]["mid"],
                "days_median": f["days"]["median"],
                "days_mean": f["days"]["mean"],
                "is_source": False,
                "is_hire": f["key"] == self.hire_key,
            })

        return {
            "stage": key,
            "label": self.stage(key)["label"],
            "count": count,
            "steps": steps,
            "hires": next(s["count"] for s in steps if s["is_hire"]),
        }

    def timeline(self, key, count):
        """התפלגות מועדי הגיוס של הקבוצה, לפי חלונות הזמן."""
        if count is None or not self.has_rate(key):
            return None
        stage = self.stage(key)
        if not stage["buckets"]:
            return None
        hires = count * self.rate(key)
        return [{
            "key": b["key"],
            "label": b["label"],
            "share": b["share"],
            "hires": None if b["share"] is None else round_half_up(hires * b["share"]),
        } for b in stage["buckets"]]

    # ------------------------------------------------------------------
    # שילוב כמה קבוצות
    # ------------------------------------------------------------------

    def combine(self, counts):
        """גזירה של כל הקבוצות שהוזנו, עם פירוט מקור לכל מספר.

        counts - מילון {stage_key: מספר מועמדים}. ערכי None מדולגים.
        """
        cohorts = []
        for key in self.stage_keys():
            n = counts.get(key)
            if n is None or not self.has_rate(key):
                continue
            cohorts.append(self.project_cohort(key, n))

        # צבירה לפי שלב, עם רישום כמה תרמה כל קבוצה
        per_stage = {}
        order = []
        for c in cohorts:
            for step in c["steps"]:
                if step["key"] not in per_stage:
                    per_stage[step["key"]] = {
                        "key": step["key"], "label": step["label"],
                        "total": 0, "sources": [],
                    }
                    order.append(step["key"])
                entry = per_stage[step["key"]]
                entry["total"] += step["count"]
                entry["sources"].append({
                    "from": c["stage"],
                    "from_label": c["label"],
                    "from_count": c["count"],
                    "count": step["count"],
                    "days_median": step["days_median"],
                })

        return {
            "cohorts": cohorts,
            "per_stage": [per_stage[k] for k in order],
            "hires": per_stage.get(self.hire_key, {"total": 0, "sources": []})["total"],
            "overlap_warning": len(cohorts) > 1,
        }

    def cross_check(self, counts):
        """מה קבוצה מוקדמת חוזה לשלב שבו הוזנה קבוצה מאוחרת.

        זו אינה הודעת שגיאה. היא נועדה לענות על שאלה אחת: אם המספרים
        שהוזנו מתארים את אותם אנשים, האם הם מסתדרים זה עם זה.
        """
        entered = [k for k in self.stage_keys()
                   if counts.get(k) is not None and self.has_rate(k)]
        out = []
        for i, early in enumerate(entered):
            projection = self.project_cohort(early, counts[early])
            by_key = {s["key"]: s for s in projection["steps"]}
            for late in entered[i + 1:]:
                if late not in by_key:
                    continue
                expected = by_key[late]["count"]
                actual = counts[late]
                allowed = max(self.tolerance["min_candidates"],
                              expected * self.tolerance["pct"])
                if abs(actual - expected) <= allowed:
                    verdict = "matches"
                elif actual < expected:
                    verdict = "fewer"
                else:
                    verdict = "more"
                out.append({
                    "early": early, "late": late,
                    "early_count": counts[early],
                    "expected": expected, "actual": actual,
                    "gap": abs(actual - expected),
                    "verdict": verdict,
                })
        return out

    # ------------------------------------------------------------------
    # חישוב לאחור מיעד
    # ------------------------------------------------------------------

    def required_for_target(self, key, target_hires):
        """כמה מועמדים דרושים בשלב כדי להגיע ליעד גיוס נתון."""
        if target_hires is None or not self.has_rate(key):
            return None
        return target_hires / self.rate(key)

    def required_funnel(self, target_hires):
        """חישוב לאחור: כמה מועמדים נדרשים בכל שלב כדי להגיע ליעד."""
        out = {}
        for k in self.stage_keys():
            req = self.required_for_target(k, target_hires)
            out[k] = None if req is None else {
                "value": round_half_up(req), "source": "derived"}
        out["hires"] = target_hires
        return out

    def target_verdict(self, projected_hires, target):
        """השוואת המגויסים הצפויים ליעד."""
        if target is None:
            return None
        allowed = max(self.tolerance["min_candidates"],
                      target * self.tolerance["pct"])
        if abs(projected_hires - target) <= allowed:
            kind, gap = "target_ok", 0
        elif projected_hires < target:
            kind, gap = "target_miss", target - projected_hires
        else:
            kind, gap = "target_over", projected_hires - target
        return {"kind": kind, "gap": gap,
                "projected": projected_hires, "target": target}


def load_engine(path=DATA_PATH):
    with Path(path).open(encoding="utf-8") as fh:
        return Engine(json.load(fh))
