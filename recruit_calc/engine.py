"""מנוע החישוב של מחשבון הגיוס.

הלוגיקה כאן חייבת להישאר זהה ללוגיקה שב-web/template.html.
tests/test_parity.py מוודא שהשניים מחזירים את אותן תוצאות.

עקרונות
-------
1. כל שלב מתורגם לגיוסים דרך יחס ההמרה שלו לגיוס, שנמדד מהנתונים.
   מעבר בין שני שלבים נעשה תמיד דרך הגיוסים: n_j = n_i * rate_i / rate_j.
2. כל תוצאה היא טווח. יחס ההמרה נמדד כטווח (בגלל קטיעה מימין בנתונים),
   ולכן גם התחזית היא טווח - לא מספר יחיד שמתחזה לוודאות.
3. שלב שאין לו נתונים במקור («הגשות») אינו מקבל יחס משוער. כל בקשה
   לחשב דרכו מחזירה None עם הסבר, ולא ניחוש.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "recruitment_data.json"


class Range:
    """טווח תוצאה. low/high תמיד מעוגלים כלפי מטה/מעלה לשלמים."""

    __slots__ = ("low", "high")

    def __init__(self, low, high):
        if low > high:
            low, high = high, low
        self.low = low
        self.high = high

    @property
    def mid(self):
        return (self.low + self.high) / 2

    def rounded(self):
        """הטווח כמספרים שלמים: תחתון כלפי מטה, עליון כלפי מעלה."""
        import math
        return int(math.floor(self.low)), int(math.ceil(self.high))

    def as_dict(self):
        low, high = self.rounded()
        return {"low": low, "high": high}

    def __repr__(self):
        return f"Range({self.low:.4f}, {self.high:.4f})"


class Engine:
    def __init__(self, dataset):
        self.data = dataset
        self.stages = dataset["stages"]
        self.by_key = {s["key"]: s for s in self.stages}
        self.buckets = dataset["time_buckets"]

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
        r = self.stage(key)["hire_rate"]
        return Range(count * r["low"], count * r["high"])

    def required_for_target(self, key, target_hires):
        """כמה מועמדים דרושים בשלב כדי להגיע ליעד גיוס נתון.

        יחס נמוך דורש יותר מועמדים, ולכן הגבולות מתהפכים.
        """
        if target_hires is None or not self.has_rate(key):
            return None
        r = self.stage(key)["hire_rate"]
        return Range(target_hires / r["high"], target_hires / r["low"])

    def convert(self, from_key, count, to_key):
        """תרגום מספר מועמדים משלב אחד לשלב אחר, דרך הגיוסים."""
        if count is None:
            return None
        if from_key == to_key:
            return Range(count, count)
        if not (self.has_rate(from_key) and self.has_rate(to_key)):
            return None
        a = self.stage(from_key)["hire_rate"]
        b = self.stage(to_key)["hire_rate"]
        return Range(count * a["low"] / b["high"], count * a["high"] / b["low"])

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
            if share is None:
                out.append({"key": b["key"], "label": b["label"], "share": None, "hires": None})
                continue
            out.append({
                "key": b["key"],
                "label": b["label"],
                "share": share,
                "hires": Range(hires.low * share, hires.high * share),
            })
        return out

    def gap_analysis(self, counts, target=None):
        """ניתוח פערים בין השלבים שהוזנו לבין יעד הגיוס.

        counts - מילון {stage_key: מספר מועמדים}. ערכי None מדולגים.
        מחזיר רשימת הודעות ממוינת לפי סדר השלבים.
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
                lo, hi = needed.rounded()
                if actual < lo:
                    messages.append({
                        "kind": "deficit",
                        "stage": early,
                        "against": late,
                        "shortfall": Range(lo - actual, hi - actual).as_dict(),
                        "needed": {"low": lo, "high": hi},
                        "actual": actual,
                    })
                elif actual > hi:
                    messages.append({
                        "kind": "surplus",
                        "stage": early,
                        "against": late,
                        "surplus": Range(actual - hi, actual - lo).as_dict(),
                        "needed": {"low": lo, "high": hi},
                        "actual": actual,
                    })
                else:
                    messages.append({
                        "kind": "balanced",
                        "stage": early,
                        "against": late,
                        "needed": {"low": lo, "high": hi},
                        "actual": actual,
                    })

        # מול יעד הגיוס - לפי השלב המתקדם ביותר שהוזן
        if target is not None and entered:
            deepest = entered[-1]
            projected = self.project_hires(deepest, counts[deepest])
            lo, hi = projected.rounded()
            if hi < target:
                kind = "target_miss"
            elif lo > target:
                kind = "target_over"
            else:
                kind = "target_ok"
            messages.append({
                "kind": kind,
                "stage": deepest,
                "target": target,
                "projected": {"low": lo, "high": hi},
            })

        return messages

    def fill_from(self, key, count):
        """השלמת כל שלבי המשפך מתוך נתון יחיד בשלב אחד."""
        out = {}
        for k in self.stage_keys():
            if k == key:
                out[k] = {"low": count, "high": count, "source": "input"}
                continue
            conv = self.convert(key, count, k)
            if conv is None:
                out[k] = None
                continue
            d = conv.as_dict()
            d["source"] = "derived"
            out[k] = d
        hires = self.project_hires(key, count)
        out["hires"] = hires.as_dict() if hires else None
        return out


def load_engine(path=DATA_PATH):
    with Path(path).open(encoding="utf-8") as fh:
        return Engine(json.load(fh))
