"""מנוע החישוב של מחשבון הגיוס.

הלוגיקה כאן חייבת להישאר זהה ללוגיקה שב-web/template.html.
tests/test_parity.py מוודא שהשניים מחזירים את אותן תוצאות.

עקרונות
-------
1. כל שלב מתורגם לגיוסים דרך יחס ההמרה שלו לגיוס, שנמדד מהנתונים.
   מעבר בין שני שלבים נעשה תמיד דרך הגיוסים: n_j = n_i * rate_i / rate_j.

2. כל תוצאה היא מספר יחיד. יחס ההמרה נמדד בשני בסיסים - חלון קבוע
   וקוהורט בשל - והערך שבשימוש הוא הממוצע ביניהם. שני הבסיסים נשמרים
   ב-data/recruitment_data.json וניתן לראות אותם ב-make verify.

3. שלב שאין לו נתונים במקור («הגשות») אינו מקבל יחס משוער. כל בקשה
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

    def stage_keys(self, with_data_only=False):
        return [s["key"] for s in self.stages
                if not with_data_only or (s["has_data"] and s["hire_rate"])]

    # ------------------------------------------------------------------
    # חישובים
    # ------------------------------------------------------------------

    def project_hires(self, key, count):
        """כמה מגויסים צפויים ממספר מועמדים נתון בשלב מסוים."""
        if count is None or not self.has_rate(key):
            return None
        return count * self.rate(key)

    def required_for_target(self, key, target_hires):
        """כמה מועמדים דרושים בשלב כדי להגיע ליעד גיוס נתון."""
        if target_hires is None or not self.has_rate(key):
            return None
        return target_hires / self.rate(key)

    def convert(self, from_key, count, to_key):
        """תרגום מספר מועמדים משלב אחד לשלב אחר, דרך הגיוסים."""
        if count is None:
            return None
        if from_key == to_key:
            return float(count)
        if not (self.has_rate(from_key) and self.has_rate(to_key)):
            return None
        return count * self.rate(from_key) / self.rate(to_key)

    def timeline(self, key, count):
        """פריסת המגויסים הצפויים מהשלב על פני חלונות הזמן."""
        hires = self.project_hires(key, count)
        if hires is None:
            return None
        stage = self.stage(key)
        if not stage["buckets"]:
            return None
        out = []
        for b in stage["buckets"]:
            share = b["share"]
            out.append({
                "key": b["key"],
                "label": b["label"],
                "share": share,
                "hires": None if share is None else round_half_up(hires * share),
            })
        return out

    def _is_balanced(self, actual, needed):
        """האם הפער בין המצוי לנדרש קטן מספיק כדי להיחשב איזון."""
        allowed = max(self.tolerance["min_candidates"],
                      needed * self.tolerance["pct"])
        return abs(actual - needed) <= allowed

    def gap_analysis(self, counts, target=None):
        """ניתוח פערים בין השלבים שהוזנו לבין יעד הגיוס.

        counts - מילון {stage_key: מספר מועמדים}. ערכי None מדולגים.
        """
        messages = []
        entered = [k for k in self.stage_keys()
                   if counts.get(k) is not None and self.has_rate(k)]

        # השוואה בין כל זוג שלבים שהוזנו
        for i, early in enumerate(entered):
            for late in entered[i + 1:]:
                actual = counts[early]
                needed = self.convert(late, counts[late], early)
                if needed is None:
                    continue
                needed_r = round_half_up(needed)
                if self._is_balanced(actual, needed):
                    kind, gap = "balanced", 0
                elif actual < needed:
                    kind, gap = "deficit", needed_r - actual
                else:
                    kind, gap = "surplus", actual - needed_r
                messages.append({
                    "kind": kind,
                    "stage": early,
                    "against": late,
                    "gap": gap,
                    "needed": needed_r,
                    "actual": actual,
                })

        # מול יעד הגיוס - לפי השלב המתקדם ביותר שהוזן
        if target is not None and entered:
            deepest = entered[-1]
            projected = self.project_hires(deepest, counts[deepest])
            projected_r = round_half_up(projected)
            if self._is_balanced(projected, target):
                kind, gap = "target_ok", 0
            elif projected < target:
                kind, gap = "target_miss", target - projected_r
            else:
                kind, gap = "target_over", projected_r - target
            messages.append({
                "kind": kind,
                "stage": deepest,
                "target": target,
                "gap": gap,
                "projected": projected_r,
            })

        return messages

    def fill_from(self, key, count):
        """השלמת כל שלבי המשפך מתוך נתון יחיד בשלב אחד."""
        out = {}
        for k in self.stage_keys():
            if k == key:
                out[k] = {"value": count, "source": "input"}
                continue
            conv = self.convert(key, count, k)
            out[k] = None if conv is None else {
                "value": round_half_up(conv), "source": "derived"}
        hires = self.project_hires(key, count)
        out["hires"] = None if hires is None else round_half_up(hires)
        return out

    def required_funnel(self, target_hires):
        """חישוב לאחור: כמה מועמדים נדרשים בכל שלב כדי להגיע ליעד."""
        out = {}
        for k in self.stage_keys():
            req = self.required_for_target(k, target_hires)
            out[k] = None if req is None else {
                "value": round_half_up(req), "source": "derived"}
        out["hires"] = target_hires
        return out


def load_engine(path=DATA_PATH):
    with Path(path).open(encoding="utf-8") as fh:
        return Engine(json.load(fh))
