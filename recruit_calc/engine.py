"""מנוע החישוב של מחשבון הגיוס.

הלוגיקה כאן חייבת להישאר זהה ללוגיקה שב-web/template.html.
tests/test_parity.py מוודא שהשניים מחזירים את אותן תוצאות.

עקרונות
-------
1. גזירה קדימה בלבד. מספר שהוזן בשלב מסוים מייצג קבוצת מועמדים שנמצאת
   *עכשיו* באותו שלב. מהקבוצה הזו נגזר כמה מהם יגיעו לכל שלב מאוחר יותר
   ומתי, וכמה מהם יגויסו ומתי. לא נגזר מהם כמה היו בשלבים מוקדמים יותר -
   זה מידע שאין לנו.

   תכנון מיעד הוא דבר אחר, ומותר. השאלה "כמה צריך בשלב X כדי לגייס Y"
   אינה טענה על העבר של קבוצה קיימת אלא דרישה קדימה: איזו כמות בשלב X
   תפיק, בגזירה קדימה, את Y. לכן plan_from_target מחזיר את הכמות הנדרשת
   ואז גוזר ממנה קדימה בדיוק כמו project_cohort.

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


def round_to(x, places):
    """עיגול למספר ספרות אחרי הנקודה, זהה בפייתון וב-JS.

    נחוץ כדי שממוצעים משוקללים לא יתפצלו בין שני המנועים בגלל רעש
    בספרה ה-15 של הנקודה הצפה.
    """
    f = 10 ** places
    return round_half_up(x * f) / f


class Engine:
    def __init__(self, dataset):
        self.data = dataset
        self.stages = dataset["stages"]
        self.by_key = {s["key"]: s for s in self.stages}
        self.buckets = dataset["time_buckets"]
        self.tolerance = dataset["gap_tolerance"]
        self.coverage_floor = dataset.get("coverage_warning_below")
        self.selective_floor = dataset.get("selective_below")
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

    def coverage(self, key):
        """איזה חלק מהמגויסים בכלל עברו דרך השלב הזה, לפי הקבצים.

        שיעור המעבר אומר מה קורה למי שנמצא בשלב. הכיסוי אומר דבר אחר
        לגמרי: כמה מהגיוסים בכלל עוברים שם. שלב שרק חצי מהמגויסים
        נרשמו בו אינו יושב מעל כל המשפך, וכמות שמוזנת בו אינה יכולה
        להסביר את כלל הגיוסים - חלק מהם מגיעים בדרך אחרת.

        בלי המספר הזה, «35,711 הגשות מניבות 1,145 גיוסים» נראה כמו
        טעות בשיעור, בעוד שהארגון גייס באותה תקופה 2,328. ההסבר אינו
        בשיעור אלא בכיסוי: רק כמחצית מהמגויסים בכלל נרשמו כהגשה.
        """
        if not self.has_rate(key):
            return None
        return self.stage(key)["hire_coverage"]

    def covered_share(self, key):
        """הכיסוי בחלון שבו הקטיעה משמאל כבר אינה פועלת.

        המספר הכולל מוטה כלפי מטה: מי שהתגייס בתחילת התקופה ביצע את
        השלב לפני תחילת הקובץ. כאן נספרים רק מגויסים שהחלון שלפניהם
        מכוסה, ולכן מה שנשאר הוא כיסוי חסר אמיתי.
        """
        c = self.coverage(key)
        if c is None:
            return None
        return c["covered"] if c["covered"] is not None else c["overall"]

    def low_coverage(self, keys=None):
        """השלבים שאינם מסבירים את רוב הגיוסים, ולכן דורשים אזהרה."""
        if not self.coverage_floor:
            return []
        out = []
        for k in (keys if keys is not None else self.stage_keys()):
            if not self.has_rate(k):
                continue
            share = self.covered_share(k)
            if share is not None and share < self.coverage_floor:
                c = self.coverage(k)
                out.append({
                    "key": k, "label": self.label(k), "share": share,
                    "covered_n": c["covered_n"], "covered_hires": c["covered_hires"],
                    "overall": c["overall"], "hires": c["hires"],
                })
        return out

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

    def curve_share(self, key, days):
        """איזה חלק מהמגויסים מאותו שלב כבר התגייס בתוך מספר ימים נתון.

        נקרא מהעקומה המדודה שנבנתה יום ביום מקובצי המקור, ולא מחלונות
        הזמן. תאריך שנופל באמצע חלון מקבל כאן תשובה מדודה ולא משוערת.

        בין שתי נקודות בעקומה הערך שטוח, ולכן לוקחים את הנקודה
        האחרונה שאינה מאוחרת מהיום המבוקש.
        """
        if days is None or not self.has_rate(key):
            return None
        curve = self.stage(key)["hire_curve"]
        if not curve:
            return None
        share = 0.0
        for day, cum in curve:
            if day <= days:
                share = cum
            else:
                break
        return share

    def hires_by_day(self, key, count, days):
        """כמה מהקבוצה צפויים להתגייס בתוך מספר ימים נתון.

        זה תת-קבוצה של הגיוסים הצפויים בסך הכול, לא מספר אחר. הקבוצה
        שתתגייס בסוף היא count * hire_rate, ומתוכה החלק שכבר הספיק
        להתגייס עד היום המבוקש הוא curve_share.
        """
        if count is None or days is None or not self.has_rate(key):
            return None
        share = self.curve_share(key, days)
        if share is None:
            return None
        return round_half_up(count * self.rate(key) * share)

    def combined_by_day(self, counts, days):
        """כמה יתגייסו עד יום מסוים, מכל הקבוצות יחד, עם מקור לכל חלק."""
        if days is None:
            return None
        result = self.combine(counts)
        sources = []
        total = 0
        for c in result["cohorts"]:
            n = self.hires_by_day(c["stage"], c["count"], days)
            if n is None:
                continue
            total += n
            sources.append({
                "from": c["stage"],
                "from_label": c["label"],
                "from_count": c["count"],
                "hires": n,
                "eventual": c["hires"],
                "share": self.curve_share(c["stage"], days),
            })
        if not sources:
            return None
        return {
            "days": days,
            "hires": total,
            "eventual": result["hires"],
            "sources": sources,
        }

    def combined_when(self, counts):
        """מתי צפויים להגיע לכל שלב - שורה אחת לכל שלב, לכל הקבוצות יחד.

        המשתמש ביקש גרף אחד ולא גרף לכל שלב שהוזן. לכן כל שלב מקבל כאן
        שורה אחת: הכמות היא סכום ההגעות מכל הקבוצות, והזמן הוא ממוצע
        משוקלל של חציוני הימים, במשקל מספר המועמדים שכל קבוצה תורמת.

        שלב שהוזן ידנית אינו נספר כאן בעצמו - מי שכבר נמצא שם אינו "מגיע"
        לשם, ואין לו זמן הגעה. הוא נספר רק בשלבים שאחריו.
        """
        result = self.combine(counts)
        rows = []
        for idx, entry in enumerate(result["per_stage"]):
            parts = [x for x in entry["sources"] if x["from"] != entry["key"]]
            if not parts:
                continue
            total = sum(x["count"] for x in parts)
            if total:
                days = round_to(
                    sum(x["count"] * x["days_median"] for x in parts) / total, 1)
            else:
                # כל הקבוצות תורמות אפס. אין משקל, ולכן ממוצע פשוט.
                days = round_to(sum(x["days_median"] for x in parts) / len(parts), 1)
            rows.append({
                "key": entry["key"],
                "label": entry["label"],
                "count": total,
                "days_median": days,
                "weighted": len(parts) > 1,
                "is_hire": entry["key"] == self.hire_key,
                "sources": parts,
                "order": idx,
            })

        rows.sort(key=lambda r: (r["days_median"], r["order"]))
        for r in rows:
            del r["order"]
        return rows

    def combined_timeline(self, counts):
        """מתי צפויים להתגייס - חלון זמן אחד לכל הקבוצות יחד.

        כל קבוצה מפזרת את המגויסים שלה לפי התפלגות הזמנים של השלב שממנו
        היא נגזרת, והשורות נסכמות. הפיזור מדויק: אין כאן מיצוע של אחוזים
        אלא חיבור של מספרי מגויסים.
        """
        result = self.combine(counts)
        rows = None
        for c in result["cohorts"]:
            tl = self.timeline(c["stage"], c["count"])
            if tl is None:
                continue
            if rows is None:
                rows = [{"key": b["key"], "label": b["label"], "share": 0.0,
                         "hires": 0, "sources": []} for b in tl]
            for i, b in enumerate(tl):
                if b["hires"] is None:
                    continue
                rows[i]["hires"] += b["hires"]
                rows[i]["sources"].append({
                    "from": c["stage"],
                    "from_label": c["label"],
                    "from_count": c["count"],
                    "hires": b["hires"],
                    "share": b["share"],
                })
        if rows is None:
            return None
        total = sum(r["hires"] for r in rows)
        for r in rows:
            r["share"] = round_to(r["hires"] / total, 6) if total else 0.0
        return {"rows": rows, "total": total, "buckets": len(rows)}

    def spread(self, total, buckets):
        """פיזור כמות אחת על חלונות הזמן, בלי שהעיגול יאבד או ימציא אנשים.

        עיגול של כל חלון בנפרד גורם לסכום השורה לא להסתדר עם הסך הכול,
        וטבלה שלא מסתכמת נראית כמו טעות. לכן העיגול נעשה על הסכום הרץ:
        כל חלון מקבל את ההפרש בין הסכום המעוגל עד אליו לבין מה שכבר
        חולק. הסכום תמיד מדויק, והשיטה זהה בפייתון וב-JS.
        """
        out = []
        acc = 0.0
        done = 0
        for b in buckets or []:
            share = b.get("share")
            acc += 0.0 if share is None else total * share
            v = round_half_up(acc) - done
            done += v
            out.append({"key": b["key"], "label": b["label"],
                        "share": share, "count": v})
        return out

    def combined_matrix(self, counts):
        """טבלה אחת: כמה יגיעו לכל שלב, ומתי, על אותה רשת חלונות זמן.

        המשתמש ביקש טבלה אחת ולא טבלה לכל שלב. כל שורה היא שלב, כל
        עמודה היא חלון זמן, והתא הוא כמה מועמדים יגיעו לשלב ההוא בתוך
        החלון ההוא - מסכום כל הקבוצות שהוזנו.

        השלב שהוזן ידנית אינו מקבל שורה משל עצמו: מי שכבר שם אינו
        "מגיע" לשם ואין לו זמן הגעה. הוא נספר רק בשלבים שאחריו.

        הזמן בעמודת «חציון» הוא ממוצע משוקלל של חציוני הימים לפי מספר
        המועמדים שכל קבוצה תורמת, בדיוק כמו ב-combined_when.
        """
        result = self.combine(counts)
        rows = {}
        order = []
        for c in result["cohorts"]:
            for f in self.forward(c["stage"]):
                key = f["key"]
                if key not in rows:
                    rows[key] = {
                        "key": key, "label": f["label"], "total": 0,
                        "weighted": 0.0, "cells": None, "sources": [],
                        "is_hire": key == self.hire_key,
                        "order": len(order),
                    }
                    order.append(key)
                r = rows[key]
                arrivals = round_half_up(c["count"] * f["reach"]["mid"])
                r["total"] += arrivals
                r["weighted"] += arrivals * f["days"]["median"]
                cells = self.spread(arrivals, f.get("buckets"))
                if r["cells"] is None:
                    r["cells"] = [{"key": x["key"], "label": x["label"],
                                   "count": 0} for x in cells]
                for i, x in enumerate(cells):
                    r["cells"][i]["count"] += x["count"]
                r["sources"].append({
                    "from": c["stage"], "from_label": c["label"],
                    "from_count": c["count"], "count": arrivals,
                    "reach": f["reach"]["mid"],
                    "days_median": f["days"]["median"],
                    "cells": cells,
                })

        out = []
        for key in order:
            r = rows[key]
            n = len(r["sources"])
            if r["total"]:
                days = round_to(r["weighted"] / r["total"], 1)
            else:
                days = round_to(sum(x["days_median"] for x in r["sources"]) / n, 1)
            out.append({
                "key": r["key"], "label": r["label"], "count": r["total"],
                "days_median": days, "weighted": n > 1,
                "is_hire": r["is_hire"], "cells": r["cells"],
                "sources": r["sources"], "order": r["order"],
            })

        out.sort(key=lambda r: (r["days_median"], r["order"]))
        for r in out:
            del r["order"]
        return {
            "buckets": [{"key": b["key"], "label": b["label"],
                         "min_days": b["min_days"], "max_days": b["max_days"]}
                        for b in self.buckets],
            "rows": out,
            "overlap_warning": result["overlap_warning"],
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

    def effective_rate(self, key, days=None):
        """שיעור הגיוס שאפשר לממש בזמן שנותר.

        בלי הגבלת זמן זהו שיעור הגיוס של השלב. עם הגבלה, רק החלק
        מהמגויסים שמספיק להתגייס עד אז נחשב - כי מי שיתגייס אחרי
        התאריך אינו עונה על היעד.
        """
        if not self.has_rate(key):
            return None
        if days is None:
            return self.rate(key)
        share = self.curve_share(key, days)
        return None if share is None else self.rate(key) * share

    def observed_candidates(self, key):
        """כמה מועמדים ייחודיים עברו בשלב הזה בכל תקופת הנתונים."""
        if not self.has_rate(key):
            return None
        o = self.stage(key)["observed"]
        return None if o is None else o["candidates"]

    def observed_per_day(self, key):
        """קצב התנועה בשלב: מועמדים ליום, כפי שנמדד בקבצים."""
        if not self.has_rate(key):
            return None
        o = self.stage(key)["observed"]
        return None if o is None else o["per_day"]

    def capacity(self, key, days):
        """כמה מועמדים יכולים לעבור בשלב בתוך מספר ימים, לפי הקצב הנמדד.

        זו אמת המידה היחידה ההוגנת לשאלה אם דרישה מעשית, והיא תקפה רק
        כשיש חלון זמן. בלי תאריך יעד אין תקרה בכלל: «4,000 גיוסים»
        בלי מועד הוא יעד לגיטימי לחלוטין - הארגון מגייס כ-3,700 בשנה -
        והוא פשוט ייקח יותר זמן.

        הגרסה הקודמת השוותה כל דרישה לכמות שנמדדה ב-229 ימים, וכך
        פסלה יעד שנתי סביר בתור «לא בר-השגה» בכל שלב. זו היתה תקלה.
        ההגנה שבגללה הכלל נולד - «400 תוך חודש» שדרש 152,000 בדיקות
        קבצים - נשמרת במלואה, כי שם יש תאריך ולכן יש תקרה.
        """
        if days is None or not self.has_rate(key):
            return None
        per_day = self.observed_per_day(key)
        return None if per_day is None else per_day * days

    def pace_days(self, key, required):
        """כמה ימים של הקצב הנמדד דרושים כדי לצבור את הכמות הזו.

        זה מה שמחליף את «לא בר-השגה» כשאין תאריך יעד: לא פסילה, אלא
        המחיר בזמן. 124,778 הגשות אינן בלתי אפשריות - הן כשנתיים
        של קצב ההגשות הנוכחי.
        """
        if required is None or not self.has_rate(key):
            return None
        per_day = self.observed_per_day(key)
        if not per_day:
            return None
        return round_to(required / per_day, 1)

    def _requirement_rows(self, needed, days):
        """שורות הדרישה לכל שלב. מקור האמת היחיד לחישוב הזה.

        משמש גם את required_plan וגם את gap_plan. בעבר היו לזה שני
        מימושים נפרדים, ורק אחד מהם התחשב בזמן - כך נוצר מצב שבו
        «400 גיוסים תוך חודש» החזיר 5,205 בדיקות קבצים, כמות שמניבה
        כ-13 גיוסים בחודש ולא 400.
        """
        rows = []
        for k in self.stage_keys():
            st = self.stage(k)
            if not self.has_rate(k):
                rows.append({
                    "key": k, "label": st["label"], "has_data": False,
                    "rate": None, "share_in_time": None, "effective_rate": None,
                    "required": None, "in_time": False, "feasible": False,
                    "lead_days_median": None, "lead_days_mean": None,
                    "measured_on": None, "observed": None,
                    "observed_per_day": None, "capacity": None,
                    "pace_days": None, "note": st["note"],
                })
                continue

            d = st["days_to_hire"]
            share = 1.0 if days is None else self.curve_share(k, days)
            eff = self.rate(k) * share
            if needed <= 0:
                required = 0
            elif eff > 0:
                required = round_half_up(needed / eff)
            else:
                required = None

            observed = self.observed_candidates(k)
            cap = self.capacity(k, days)
            # דרישה נפסלת רק כשיש חלון זמן שאינו יכול להכיל אותה, לפי
            # הקצב הנמדד בשלב. בלי תאריך יעד אין תקרה: הדרישה פשוט
            # לוקחת זמן, וזה מה ש-pace_days אומר.
            if required is None:
                feasible = False
            elif required == 0 or cap is None:
                feasible = True
            else:
                feasible = required <= cap
            rows.append({
                "key": k, "label": st["label"], "has_data": True,
                "rate": self.rate(k),
                "share_in_time": share,
                "effective_rate": eff,
                "required": required,
                "in_time": eff > 0,
                "feasible": feasible,
                "lead_days_median": d["median"],
                "lead_days_mean": d["mean"],
                "measured_on": d["n"],
                "observed": observed,
                "observed_per_day": self.observed_per_day(k),
                "capacity": None if cap is None else round_half_up(cap),
                "pace_days": self.pace_days(k, required),
                "note": "",
            })
        return rows

    def feasible_stages(self, target_hires, days=None):
        """השלבים שמהם היעד בר-השגה בזמן הנתון."""
        plan = self.required_plan(target_hires, days)
        if plan is None:
            return []
        return [r["key"] for r in plan["rows"] if r["has_data"] and r["feasible"]]

    def required_plan(self, target_hires, days=None):
        """כמה מועמדים צריך בכל שלב כדי לגייס את היעד, ומתי הם צריכים להיות שם.

        כל שורה עומדת בפני עצמה ועונה על שאלה אחת: אם הקבוצה היחידה שיש
        לי נמצאת בשלב הזה, כמה מועמדים צריכים להיות בה. השורות אינן
        מצטברות זו לזו - הן שש תשובות חלופיות לאותה שאלה, לא משפך.

        days - כשהוא נתון, הדרישה מחושבת לפי מה שמספיק להתגייס בזמן
        שנותר. שלב מוקדם דורש אז כמות גדולה בהרבה, ולפעמים כמות שאינה
        מעשית - וזו התשובה הנכונה, לא תקלה.
        """
        if target_hires is None:
            return None
        return {"target": target_hires, "days": days,
                "rows": self._requirement_rows(target_hires, days)}

    def lead_time_anomalies(self):
        """שלבים שמהם הדרך לגיוס ארוכה יותר מאשר משלב מוקדם יותר.

        אפשר לצפות שככל שמתקדמים בתהליך הזמן שנותר עד הגיוס יתקצר, אבל
        זה לא מה שקורה בנתונים. הזמנים נמדדים רק על מי שהתגייס בפועל,
        והקבוצה שנמדדת בכל שלב היא אחרת. לכן ייתכן שלמי שהגיע לשלב
        מסוים לוקח יותר זמן להתגייס מאשר לקבוצה שנמדדה בשלב שלפניו.

        זה חשוב לתצוגה: המשמעות היא שהתאריך שבו צריך להיות בכל שלב
        אינו בהכרח בסדר השלבים. בלי לומר את זה במפורש, הטבלה נראית
        כאילו יש בה טעות.
        """
        ordered = [k for k in self.stage_keys() if self.has_rate(k)]
        out = []
        for i in range(1, len(ordered)):
            key = ordered[i]
            lead = self.stage(key)["days_to_hire"]["median"]
            for j in range(i):
                prev = ordered[j]
                prev_lead = self.stage(prev)["days_to_hire"]["median"]
                if lead > prev_lead:
                    out.append({
                        "key": key, "label": self.stage(key)["label"],
                        "lead_days_median": lead,
                        "earlier": prev, "earlier_label": self.stage(prev)["label"],
                        "earlier_lead_days_median": prev_lead,
                    })
        return out

    def plan_from_target(self, key, target_hires, days=None):
        """משפך רציף אחד: מה צריך בשלב הכניסה, ומה יזרום ממנו לכל שלב הלאה.

        זו התשובה לשאלה "כמה צריך בכל שלב כדי לגייס X" בקריאה המצטברת
        שלה - קבוצה אחת שנכנסת בשלב אחד ועוברת את התהליך.

        הכמות הנדרשת מחושבת מהיעד, ומיד אחריה הכול נגזר קדימה בדיוק כמו
        project_cohort. כלומר: אם תזין את המספר הנדרש במחשבון הרגיל, תקבל
        את אותו משפך בדיוק. זו הבטחה שאפשר לבדוק.

        בגלל העיגול של הכמות הנדרשת, מספר המגויסים שיוצא עשוי להיות שונה
        מהיעד במגויס או שניים. hires מחזיר את המספר האמיתי, לא את היעד.
        """
        if target_hires is None or not self.has_rate(key):
            return None
        st = self.stage(key)
        eff = self.effective_rate(key, days)
        if not eff:
            return {
                "stage": key, "label": st["label"], "target": target_hires,
                "required": None, "exact": None, "rate": self.rate(key),
                "effective_rate": eff, "share_in_time": self.curve_share(key, days),
                "days": days, "lead_days_median": st["days_to_hire"]["median"],
                "lead_days_mean": st["days_to_hire"]["mean"],
                "measured_on": st["days_to_hire"]["n"],
                "observed": self.observed_candidates(key),
                "observed_per_day": self.observed_per_day(key),
                "capacity": None if self.capacity(key, days) is None
                            else round_half_up(self.capacity(key, days)),
                "pace_days": None,
                "feasible": False,
                "projection": None, "hires": 0, "hires_in_time": 0,
            }
        exact = target_hires / eff
        required = round_half_up(exact)
        projection = self.project_cohort(key, required)
        d = st["days_to_hire"]
        observed = self.observed_candidates(key)
        cap = self.capacity(key, days)
        return {
            "stage": key,
            "label": st["label"],
            "target": target_hires,
            "required": required,
            "exact": round_to(exact, 1),
            "rate": self.rate(key),
            "effective_rate": eff,
            "share_in_time": 1.0 if days is None else self.curve_share(key, days),
            "days": days,
            "lead_days_median": d["median"],
            "lead_days_mean": d["mean"],
            "measured_on": d["n"],
            "observed": observed,
            "observed_per_day": self.observed_per_day(key),
            "capacity": None if cap is None else round_half_up(cap),
            "pace_days": self.pace_days(key, required),
            "feasible": cap is None or required <= cap,
            "projection": projection,
            # מספר המגויסים בסך הכול, בלי הגבלת זמן. כשיש תאריך יעד זהו
            # מספר אחר מהיעד, ואסור להציג אותו כאילו הוא התשובה.
            "hires": projection["hires"],
            # מה שבאמת עונה על היעד: כמה מהם יגויסו עד התאריך
            "hires_in_time": (projection["hires"] if days is None
                              else self.hires_by_day(key, required, days)),
        }

    def gap_plan(self, counts, target_hires, days=None):
        """כמה עוד צריך, אחרי שסופרים את מי שכבר נמצא בתהליך.

        זו התשובה לשאלה המעשית: יש לי יעד, ויש לי כבר מועמדים בשלבים
        שונים. כמה עוד אני צריך להכניס.

        בלי החישוב הזה המחשבון דורש להתחיל הכול מאפס ומתעלם מכל מי
        שכבר במסלול, ולכן מנפח את הדרישה.

        days - כשהוא נתון, גם המלאי הקיים וגם התוספת נמדדים לפי מה
        שיספיק עד אז. מועמד שייכנס עכשיו לשלב מוקדם לא יגויס בעוד
        שלושה שבועות, ולכן הדרישה ממנו גדולה יותר - ולפעמים בלתי
        אפשרית. שיעור הגיוס האפקטיבי הוא שיעור הגיוס של השלב כפול
        החלק ממנו שמספיק להתגייס בזמן שנותר.
        """
        if target_hires is None:
            return None

        if days is None:
            have = self.combine(counts)["hires"]
            sources = [{"from": c["stage"], "from_label": c["label"],
                        "from_count": c["count"], "hires": c["hires"]}
                       for c in self.combine(counts)["cohorts"]]
        else:
            by_day = self.combined_by_day(counts, days)
            have = 0 if by_day is None else by_day["hires"]
            sources = [] if by_day is None else by_day["sources"]

        gap = target_hires - have

        rows = self._requirement_rows(gap, days)

        return {
            "target": target_hires,
            "have": have,
            "gap": gap,
            "days": days,
            "sources": sources,
            "rows": rows,
        }

    def manager_plan(self, counts, target_hires, days=None):
        """הלוח של מנהלת הגיוס: כמה צריך בכל שלב, ועד מתי.

        לשאלה "כמה צריך בשלב X" יש שתי תשובות שונות, ושתיהן נכונות.
        הצגת אחת מהן בלבד היא מה שהטעה עד היום:

          required_now - כמה צריך *היום* בשלב הזה. מוגבל בזמן שנותר,
              ולכן שלב מוקדם דורש כמות עצומה: מי שנמצא היום בהגשות
              פשוט לא יספיק להתגייס עד התאריך. זו התשובה על "יש לי
              רק את מה שיש לי עכשיו".

          required_by - כמה צריך שיעמדו בשלב הזה כשיגיע תורו, בלי לחץ
              זמן. הכמות קטנה בהרבה, והמחיר שלה הוא תאריך: הם חייבים
              להיות שם עד deadline_days. זו התשובה על "מתי אני צריכה
              להתחיל" - וזו התשובה שמנהלת גיוס יכולה לעבוד לפיה.

        deadline_days הוא מספר הימים מהיום שבו הכמות צריכה לעמוד בשלב:
        הזמן עד היעד פחות חציון הימים מהשלב הזה עד הגיוס. מספר שלילי
        פירושו שהחלון של השלב הזה כבר נסגר עבור התאריך הזה.

        היעד מנוכה במי שכבר בתהליך, בדיוק כמו gap_plan - אותו עוזר
        _requirement_rows משמש את שניהם.
        """
        plan = self.gap_plan(counts or {}, target_hires, days)
        if plan is None:
            return None
        needed = plan["gap"]

        rows = []
        for r in plan["rows"]:
            row = dict(r)
            row["required_now"] = r["required"]
            if not r["has_data"]:
                row.update({"required_by": None, "required_by_feasible": False,
                            "deadline_days": None, "late": False})
                rows.append(row)
                continue

            if needed <= 0:
                required_by = 0
            elif r["rate"]:
                required_by = round_half_up(needed / r["rate"])
            else:
                required_by = None

            # required_by אינו מוגבל בזמן מעצם הגדרתו - הוא הכמות
            # שצריכה לעמוד בשלב כשיגיע תורה. לכן אין לו תקרה, ורק
            # המחיר בזמן (pace_days) מלווה אותו.
            row["required_by"] = required_by
            row["required_by_feasible"] = required_by is not None
            row["required_by_pace_days"] = self.pace_days(k := r["key"], required_by)
            row["deadline_days"] = (None if days is None else
                                    round_to(days - r["lead_days_median"], 1))
            row["late"] = (row["deadline_days"] is not None
                           and row["deadline_days"] < 0)
            rows.append(row)

        return {
            "target": plan["target"], "have": plan["have"], "gap": plan["gap"],
            "days": days, "sources": plan["sources"], "rows": rows,
        }

    def throughput_plan(self, target_hires, days=None):
        """כמה צריך שיעברו בכל שלב כדי לגייס X - לפי המשפך שנמדד בפועל.

        זו התשובה שמנהלת גיוס צריכה, והיא שונה מ-required_plan.

        required_plan עונה על "אם כל המועמדים שלי נמצאים בשלב אחד
        בלבד, כמה צריכים להיות שם" - לפי שיעור הגיוס של אותו שלב.
        השיעור הזה נמדד על קוהורט, והוא נמוך מהיחס האמיתי בין נפחי
        המשפך: רק כמחצית מהמגויסים בכלל נרשמו כהגשה, ולכן 3.2%
        מתארים חצי מהתמונה. לפי זה יצאו 124,778 הגשות ל-4,000
        גיוסים - כמות שאינה עומדת מול מה שקרה בפועל.

        כאן המדידה היא של הארגון כולו: ב-229 ימים עברו במשפך
        35,711 הגשות, 2,762 יחב"מ וכן הלאה, והתגייסו 2,328.
        כדי לגייס פי 1.72 צריך שכל השלבים ירוצו פי 1.72 - וזה
        כולל גם את המסלולים שאינם עוברים דרך ההגשות. התוצאה
        ל-4,000: 61,359 הגשות ו-4,746 יחב"מ.

        הכמות אינה תלויה בחלון הזמן - היא פרופורציונלית ליעד בלבד.
        מה שהזמן קובע הוא הקצב: pace הוא פי כמה מהקצב הנמדד צריך
        השלב לרוץ כדי לספק את הכמות בזמן שנותר.
        """
        if target_hires is None:
            return None
        base = self.data.get("hire_observed")
        if not base or not base["candidates"]:
            return None

        factor = target_hires / base["candidates"]
        rows = []
        for k in self.stage_keys():
            st = self.stage(k)
            if not self.has_rate(k) or not st.get("observed"):
                rows.append({
                    "key": k, "label": st["label"], "has_data": False,
                    "observed": None, "required": None, "per_day": None,
                    "observed_per_day": None, "pace": None,
                    "coverage": None, "selective": False, "note": st["note"],
                })
                continue
            o = st["observed"]
            required = round_half_up(o["candidates"] * factor)
            per_day = None if not days else round_to(required / days, 2)
            pace = (None if per_day is None or not o["per_day"]
                    else round_to(per_day / o["per_day"], 2))
            share = self.covered_share(k)
            rows.append({
                "key": k, "label": st["label"], "has_data": True,
                "observed": o["candidates"],
                "observed_days": o["days"],
                "observed_per_day": o["per_day"],
                "required": required,
                "per_day": per_day,
                "pace": pace,
                "coverage": share,
                # שלב שרוב המגויסים אינם עוברים בו. מרכז הערכה הוא
                # כזה, ואסור שייקרא כאילו כל המשפך חייב לעבור דרכו.
                "selective": bool(share is not None and self.selective_floor
                                  and share < self.selective_floor),
                "note": "",
            })

        return {
            "target": target_hires,
            "days": days,
            "factor": round_to(factor, 4),
            "observed_hires": base["candidates"],
            "observed_days": base["days"],
            "observed_from": base["first_date"],
            "observed_to": base["last_date"],
            "rows": rows,
        }

    def gap_pipeline(self, counts, target_hires, key, days=None):
        """אותה השלמה, כמשפך רציף אחד משלב כניסה נבחר."""
        plan = self.gap_plan(counts, target_hires, days)
        if plan is None or not self.has_rate(key):
            return None
        row = next(r for r in plan["rows"] if r["key"] == key)
        if plan["gap"] <= 0 or not row["in_time"] or row["required"] is None:
            return {"plan": plan, "stage": key, "label": self.stage(key)["label"],
                    "required": row["required"], "projection": None}
        return {
            "plan": plan,
            "stage": key,
            "label": self.stage(key)["label"],
            "required": row["required"],
            "projection": self.project_cohort(key, row["required"]),
        }

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
