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

    def annual_flow(self):
        """תזרים 2025 מהתרשים שהתקבל, אם יש."""
        return self.data.get("annual_flow")

    def constrained_plan(self, target_hires, days=None, new_only=False):
        """המחשבון עם האילוצים: כמה צריך בכל שלב כדי לגייס X בשנה.

        זו התשובה הראשית לשאלת התכנון, והיא מחליפה את throughput_plan.
        שלושה אילוצים מפרידים בינה לבין כל מה שקדם לה:

        1. **שני נתיבים, לא אחד.** לפי התרשים, 1,418 מתוך 3,294 הגיוסים
           (43%) הם «אוכלוסייה מוכרת» ביחס 1:1 - הם אינם עוברים מיון,
           ולכן אינם נגזרים מכמות ההגשות. רק 1,876 הגיוסים של
           «האוכלוסייה החדשה» תלויים במשפך, ביחס 1:31.

        2. **הנתיב המוכר קבוע.** לפי הנחיה מפורשת של המשתמש אין דרך
           להגדיל אותו. הוא תורם 1,418 גיוסים בשנה, מתפרסים באופן
           אחיד על פני 365 יום, ולכן בחלון של חצי שנה הוא תורם 709.

        3. **היחסים באים מהתרשים, לא מקבצי הפעילויות.** רישום הפעילויות
           חסר ושגוי בחלקו (רק 51% מהמגויסים נרשמו בכלל כהגשה), ולכן
           הוא נותן יחס הגשה->קבצים של 61% במקום 51%. התרשים נבחר
           כמקור מפני שהוא שומר על היחס ההגיוני.

        התוצאה: ל-4,000 גיוסים בשנה דרושות כ-82 אלף הגשות - פי 1.37
        מ-2025 - ולא 124,778 (required_plan) ולא 61,359 (throughput_plan).
        המספר גדול מפי 1.21 (=4,000/3,294) דווקא מפני שהנתיב המוכר אינו
        גדל: כל התוספת נופלת על הנתיב היחיד שכן גדל.
        """
        af = self.annual_flow()
        if af is None or target_hires is None:
            return None
        year = af["year_days"]
        span = year if days is None else days
        if span is None or span <= 0:
            return None

        # **האוכלוסייה המוכרת יחסית ליעד, עם תקרה.** היא מהווה 43%
        # מהגיוסים בתרשים, ולכן יעד של 400 מקבל ממנה כ-172 ולא 1,418.
        # הדבקת המספר השנתי כרצפה קשיחה היתה מחזירה 1,418 גיוסים ליעד
        # של 400 - וזו היתה תקלה שדווחה. התקרה נשארת: מעל 3,294 גיוסים
        # החלק היחסי חורג מההיקף השנתי, ואז כל התוספת נופלת על
        # האוכלוסייה החדשה.
        ceiling = (0.0 if new_only
                   else af["known"]["hires_per_year"] * span / year)
        proportional = (0.0 if new_only else
                        max(0.0, target_hires) * af["known"]["share_of_hires"])
        known_hires = min(ceiling, proportional)
        new_hires = max(0.0, target_hires - known_hires)
        # יעד שקטן מהנתיב הקבוע אינו קיים עוד: החלק היחסי לעולם אינו
        # גדול מהיעד עצמו. השדה נשמר כדי שהמבנה לא ישתנה.
        shortfall = False

        chain = af["chain"]
        volumes = {af["hire_row"]["key"]: new_hires}
        v = new_hires
        for row in reversed(chain):
            r = row["rate_to_next"]
            if not r:
                return None
            v = v / r
            volumes[row["key"]] = v

        def make(row, is_hire):
            n = volumes[row["key"]]
            kn = known_hires if row["known_passes"] else 0.0
            new_i = round_half_up(n)
            known_i = round_half_up(kn)
            base_volume = row["new"] if new_only else row["volume"]
            base_per_day = base_volume / year
            per_day = (new_i + known_i) / span
            return {
                "key": row["key"], "label": row["label"],
                "is_hire": is_hire,
                "total": new_i + known_i,
                "new": new_i, "known": known_i,
                "known_passes": row["known_passes"],
                "rate_to_next": row["rate_to_next"],
                "to_next": row["to_next"],
                "baseline": base_volume,
                "baseline_new": row["new"],
                "baseline_known": 0 if new_only else row["known"],
                "baseline_per_day": round_to(base_per_day, 3),
                "per_day": round_to(per_day, 3),
                "pace": (None if not base_per_day
                         else round_to(per_day / base_per_day, 3)),
            }

        rows = [make(r, False) for r in chain]
        rows.append(make(af["hire_row"], True))

        aside = []
        for a in af["aside"]:
            total = round_half_up(volumes[a["after"]] * a["share_of_host"])
            base_per_day = a["volume"] / year
            per_day = total / span
            aside.append({
                "key": a["key"], "label": a["label"], "after": a["after"],
                "total": total, "share_of_host": a["share_of_host"],
                "baseline": a["volume"],
                "baseline_per_day": round_to(base_per_day, 3),
                "per_day": round_to(per_day, 3),
                "pace": (None if not base_per_day
                         else round_to(per_day / base_per_day, 3)),
            })

        top = rows[0]
        return {
            "target": target_hires,
            "days": days,
            "span_days": span,
            "annual": days is None,
            "source": af["source"],
            "year": af["year"],
            "shortfall": shortfall,
            "known": {
                "label": af["known"]["label"],
                "hires": round_half_up(known_hires),
                "per_year": af["known"]["hires_per_year"],
                "ratio": af["known"]["ratio"],
                "share": (None if not target_hires
                          else round_to(known_hires / target_hires, 4)),
            },
            "new": {
                "label": af["new"]["label"],
                "hires": round_half_up(new_hires),
                "per_year": af["new"]["hires_per_year"],
                "ratio": af["new"]["ratio_measured"],
                "hire_rate": af["new"]["hire_rate"],
                "share": (None if not target_hires
                          else round_to(new_hires / target_hires, 4)),
            },
            "submissions": top["total"],
            "baseline_submissions": top["baseline"],
            "new_only": new_only,
            "baseline_hires": (af["new"]["hires_per_year"] if new_only
                               else af["hires"]),
            # השוואה לשנה מלאה מול חלון קצר היתה משווה תפוחים לתפוזים:
            # 110,892 הגשות ב-119 יום נראו כמו «פי 1.85» מ-59,978 בשנה,
            # בעוד שבפועל זהו קצב של פי 5.67. שתי הצמיחות מחושבות מול
            # אותו חלון: הבסיס מוקטן לפי אורכו.
            "baseline_in_span": round_half_up(top["baseline"] * span / year),
            "baseline_hires_in_span": round_half_up(
                (af["new"]["hires_per_year"] if new_only else af["hires"])
                * span / year),
            "growth": top["pace"],
            "target_growth": rows[-1]["pace"],
            "rows": rows,
            "aside": aside,
        }

    # ------------------------------------------------------------------
    # הכיוון ההפוך: מכמות בשלב אל מספר הגיוסים
    # ------------------------------------------------------------------
    # constrained_plan עונה «כמה צריך כדי לגייס X». כאן הכיוון ההפוך:
    # «כמה יתגייסו אם יש לי X בשלב הזה». שני הכיוונים חייבים לעמוד על
    # אותה אריתמטיקה - הזנת כמות ההגשות שהתקבלה מהיעד חייבת להחזיר את
    # היעד. המספר שהיה חסר עד 2026-09-03 הוא האוכלוסייה המוכרת: היא
    # מתגייסת בלי קשר לכמות שבמשפך, ולכן 60,000 הגשות בשנה נתנו 1,923
    # גיוסים במקום כ-3,300.

    def _flow_rows(self):
        """שרשרת התזרים עם שורת הגיוס בסופה, ומפתח שם->אינדקס."""
        af = self.annual_flow()
        if af is None:
            return None
        rows = list(af["chain"]) + [af["hire_row"]]
        return af, rows, {r["key"]: i for i, r in enumerate(rows)}

    def _flow_span(self, days, new_only=False):
        """אורך החלון וכמה גיוסים תורם בו הנתיב המוכר.

        הנתיב המוכר קבוע ומתחלק אחיד על פני השנה, ולכן חלון קצר מקבל
        ממנו פחות - וזו הסיבה שדרישת ההגשות גדלה כשהחלון מתקצר.
        """
        af = self.annual_flow()
        if af is None:
            return None, None
        year = af["year_days"]
        span = year if days is None else days
        if span is None or span <= 0:
            return None, None
        if new_only:
            # מצב «אוכלוסייה חדשה בלבד»: אין נתיב מוכר כלל.
            return span, 0.0
        return span, af["known"]["hires_per_year"] * span / year

    def _measured_days(self, from_key, to_key):
        """חציון הימים מהשלב האחד לשני, כפי שנמדד בקבצים.

        התזרים נותן יחסים בלבד ואינו נושא זמנים. הזמנים ממשיכים לבוא
        מהמדידה, וזוג שלא נמדד מחזיר None ואינו נכנס לממוצע.
        """
        if from_key == to_key:
            return 0.0
        if not self.has_rate(from_key):
            return None
        for f in self.forward(from_key):
            if f["key"] == to_key:
                return f["days"]["median"]
        return None

    def known_share(self, key, new_only=False):
        """איזה חלק מהנפח בשלב הזה הוא האוכלוסייה המוכרת, לפי התרשים.

        בבדיקת קבצים עברו ב-2025 30,574 מועמדים, מהם 1,418 מוכרת -
        כלומר 4.64%. זהו התמהיל הטבעי של השלב.
        """
        packed = self._flow_rows()
        if packed is None:
            return None
        af, rows, idx = packed
        if key not in idx:
            return None
        if new_only:
            return 0.0
        row = rows[idx[key]]
        if not row["volume"]:
            return 0.0
        return round_to(row["known"] / row["volume"], 6)

    def blended_rate(self, key, new_only=False):
        """שיעור ההמרה המשוקלל מהשלב ועד הגיוס, כולל האוכלוסייה המוכרת.

        זה המספר שעונה על «יש לי 300 בבדיקת קבצים, כמה יתגייסו»:
        3,294 גיוסים מתוך 30,574 שעברו בשלב, כלומר 10.77%, ומכאן
        כ-32 גיוסים. האוכלוסייה המוכרת אינה מספר קבוע שנדבק לכל
        תשובה - היא חלק מהתמהיל, ולכן היא מגדילה את השיעור הזה.
        """
        packed = self._flow_rows()
        if packed is None:
            return None
        af, rows, idx = packed
        if key not in idx:
            return None
        row = rows[idx[key]]
        if not row["volume"]:
            return None
        acc = 1.0
        for r in af["chain"][idx[key]:]:
            acc *= r["rate_to_next"]
        if new_only:
            # במשפך של האוכלוסייה החדשה בלבד אין מי שמצטרף ביחס 1:1.
            return round_to(acc, 6)
        return round_to((row["new"] * acc + row["known"]) / row["volume"], 6)

    def reach_share(self, from_key, to_key, days):
        """איזה חלק מההגעות ל«to» מתוך «from» קורה בתוך מספר ימים נתון.

        לשלב הגיוס יש עקומה שנמדדה יום ביום, והיא המדויקת ביותר -
        ולכן היא בשימוש שם. לשאר הזוגות יש התפלגות על חלונות זמן,
        והצבירה בתוך החלון שנחתך היא ליניארית.

        לחלון האחרון («מעל 3 חודשים») אין קצה עליון, ולכן הוא נצבר
        ליניארית עד סוף השנה. זו הערכה, והיא משפיעה רק על חלונות
        ארוכים מ-3 חודשים.
        """
        if days is None:
            return 1.0
        if days < 0:
            return 0.0
        if from_key == to_key:
            return 1.0
        if to_key == self.hire_key:
            share = self.curve_share(from_key, days)
            return 1.0 if share is None else share
        buckets = self._measured_buckets(from_key, to_key)
        if not buckets:
            return None
        acc = 0.0
        for b in buckets:
            share = b.get("share") or 0.0
            lo = b["min_days"]
            hi = b["max_days"]
            if days < lo:
                continue
            if hi is None:
                span = max(1, 365 - lo + 1)
                acc += share * min(1.0, (days - lo + 1) / span)
            elif days >= hi:
                acc += share
            else:
                acc += share * (days - lo + 1) / (hi - lo + 1)
        return round_to(min(1.0, acc), 6)

    def constrained_entry(self, key, count, days=None, new_only=False):
        """מיפוי כמות שהוזנה בשלב כלשהו אל שרשרת התזרים.

        שלושה מקרים, ובכולם נאמר במפורש דרך מה נעשה המיפוי:
          chain    - השלב יושב על השרשרת.
          aside    - תחנת צד (מרכז הערכה). היא נתלית על המארח שלה לפי
                     חלקה בו, שגם הוא מהתרשים.
          measured - שלב שאינו בתרשים כלל (זימון למבחן מקוון). הגשר אל
                     השלב הבא בשרשרת נמדד מהקבצים, ונאמר שכך נעשה.

        **פיצול הכמות בין שני הנתיבים הוא יחסי, עם תקרה.** הכמות
        מתפצלת לפי התמהיל הטבעי של השלב (`known_share`), ולא על ידי
        ניכוי המספר השנתי הקבוע. הניכוי הקבוע נתן ל-300 בדיקות קבצים
        1,418 גיוסים - כל האוכלוסייה השנתית, על 300 מועמדים - וזו
        היתה תקלה שדווחה. יחסית מתקבלים 32, שהם 300 כפול 10.77%.

        התקרה: הנתיב המוכר אינו יכול לחרוג מהיקפו בחלון הנתון. כמות
        גדולה מהנפח הטבעי מקבלת את התקרה, וכל מה שמעליה נופל על
        האוכלוסייה החדשה - וזה מה ששומר על ההיפוך המדויק מול
        constrained_plan.
        """
        packed = self._flow_rows()
        if packed is None or count is None:
            return None
        af, rows, idx = packed
        span, known_span = self._flow_span(days, new_only)
        if span is None:
            return None

        via = via_rate = via_label = chain_key = landed = label_txt = None

        if key in idx:
            via, chain_key, landed = "chain", key, float(count)
            label_txt = rows[idx[key]]["label"]
        else:
            for a in af["aside"]:
                if a["key"] != key:
                    continue
                share = a["share_of_host"]
                if not share:
                    return None
                host = rows[idx[a["after"]]]
                via, via_rate, via_label = "aside", round_to(share, 6), host["label"]
                chain_key, landed, label_txt = host["key"], count / share, a["label"]
                break
            if chain_key is None:
                if not self.has_rate(key):
                    return None
                for f in self.forward(key):
                    if f["key"] not in idx:
                        continue
                    reach = f["reach"]["mid"]
                    if not reach:
                        return None
                    target = rows[idx[f["key"]]]
                    via, via_rate = "measured", round_to(reach, 6)
                    via_label, chain_key = target["label"], target["key"]
                    landed, label_txt = count * reach, self.label(key)
                    break
                if chain_key is None:
                    return None

        share_known = self.known_share(chain_key, new_only) or 0.0
        claim = landed * share_known
        known_here = min(claim, known_span)
        return {
            "key": key, "label": label_txt, "count": count,
            "chain_key": chain_key,
            "chain_label": rows[idx[chain_key]]["label"],
            "landed": round_to(landed, 4),
            "known_share": share_known,
            "known_claim": claim,
            "known_here": round_half_up(known_here),
            "new": max(0.0, landed - known_here),
            "via": via, "via_rate": via_rate, "via_label": via_label,
        }

    def constrained_combine(self, counts, days=None, new_only=False):
        """כמה יתגייסו מהכמויות שהוזנו, לפי תזרים הליך הגיוס.

        הפלט בנוי כמו זה של constrained_plan - אותן שורות, אותם שני
        נתיבים - כדי ששני הכיוונים ייראו וייקראו אותו דבר.

        הזמנים (days_median) ממשיכים לבוא מהמדידה בקבצים. הכמויות
        באות מהתזרים בלבד.
        """
        packed = self._flow_rows()
        if packed is None:
            return None
        af, rows, idx = packed
        span, known_span = self._flow_span(days, new_only)
        if span is None:
            return None

        entries = []
        for key in self.stage_keys():
            n = counts.get(key)
            if n is None:
                continue
            e = self.constrained_entry(key, n, days, new_only)
            if e is not None:
                entries.append(e)
        if not entries:
            return None

        chain = af["chain"]
        n_chain = len(chain)
        new_at = [0.0] * len(rows)
        known_at = [0.0] * len(rows)
        sources = [[] for _ in rows]

        # התקרה על הנתיב המוכר נאכפת פעם אחת על כל מה שהוזן, ולא שלב
        # אחר שלב: זו אוכלוסייה אחת, ואילו נספרה בכל שלב בנפרד היא
        # היתה מוכפלת. כשהתביעות יחד חורגות מההיקף בחלון, כולן
        # מוקטנות באותו יחס.
        claim = sum(e["known_claim"] for e in entries)
        factor = 1.0
        if claim > known_span and claim:
            factor = known_span / claim
        for e in entries:
            e["known_here"] = round_half_up(e["known_claim"] * factor)
            e["new"] = max(0.0, e["landed"] - e["known_claim"] * factor)

        for e in entries:
            i = idx[e["chain_key"]]
            v = e["new"]
            k = e["known_claim"] * factor
            new_at[i] += v
            if rows[i]["known_passes"]:
                known_at[i] += k
            sources[i].append({"entry": e, "new": v, "days_median": 0.0})
            for j in range(i, n_chain):
                v = v * chain[j]["rate_to_next"]
                new_at[j + 1] += v
                # הנתיב המוכר אינו עובר מיון: הוא ממשיך כמות שהוא
                # בכל שלב שהתרשים מסמן שהוא עובר בו.
                if rows[j + 1]["known_passes"]:
                    known_at[j + 1] += k
                sources[j + 1].append({
                    "entry": e, "new": v,
                    "days_median": self._measured_days(e["key"], rows[j + 1]["key"]),
                })

        # מאיזו שורה מתחילה התצוגה. גזירה קדימה בלבד: שלב שנתלה על
        # מארח מוקדם יותר (תחנת צד) אינו מציג את המארח, אלא את עצמו
        # ואת מה שאחריו.
        def entry_start(e):
            i = idx[e["chain_key"]]
            return i + 1 if e["via"] == "aside" else i

        start = min(entry_start(e) for e in entries)

        def source_list(items):
            return [{
                "from": s["entry"]["key"],
                "from_label": s["entry"]["label"],
                "from_count": s["entry"]["count"],
                "count": round_half_up(s["new"]),
                "days_median": s["days_median"],
            } for s in items]

        def weighted_days(items):
            timed = [s for s in items if s["days_median"] is not None]
            if not timed:
                return None
            weight = sum(s["new"] for s in timed)
            if weight:
                return round_to(
                    sum(s["new"] * s["days_median"] for s in timed) / weight, 1)
            return round_to(sum(s["days_median"] for s in timed) / len(timed), 1)

        out = []
        for i in range(start, len(rows)):
            row = rows[i]
            new_i = round_half_up(new_at[i])
            known_i = round_half_up(known_at[i]) if row["known_passes"] else 0
            total = new_i + known_i
            # מה מתוך השורה מספיק להיכנס בתוך החלון. הנתיב הקבוע
            # מתחלק אחיד על פני החלון ולכן כולו בפנים; האוכלוסייה
            # החדשה נמדדת לפי הזמן שלוקח להגיע לשלב הזה.
            in_new = None
            if days is not None and days >= 0:
                acc = 0.0
                for src in sources[i]:
                    share = self.reach_share(src["entry"]["key"], row["key"], days)
                    acc += src["new"] * (0.0 if share is None else share)
                in_new = round_half_up(acc)
            out.append({
                "key": row["key"], "label": row["label"],
                "is_hire": i == len(rows) - 1,
                "is_source": any(s["entry"]["key"] == row["key"]
                                 for s in sources[i]),
                "total": total, "new": new_i, "known": known_i,
                "new_in_time": in_new,
                "known_in_time": known_i,
                "total_in_time": None if in_new is None else in_new + known_i,
                "known_passes": row["known_passes"],
                "rate_to_next": row["rate_to_next"],
                "to_next": row["to_next"],
                "per_day": round_to(total / span, 3),
                "days_median": weighted_days(sources[i]),
                "weighted": len(sources[i]) > 1,
                "sources": source_list(sources[i]),
            })

        entered_keys = [e["key"] for e in entries]
        aside = []
        for a in af["aside"]:
            i = idx[a["after"]]
            is_src = a["key"] in entered_keys
            if i < start and not is_src:
                continue
            total = (next(e["count"] for e in entries if e["key"] == a["key"])
                     if is_src else round_half_up(new_at[i] * a["share_of_host"]))
            in_total = None
            if days is not None and days >= 0:
                if is_src:
                    in_total = total
                else:
                    acc = 0.0
                    for src in sources[i]:
                        share = self.reach_share(src["entry"]["key"],
                                                 a["key"], days)
                        acc += src["new"] * (0.0 if share is None else share)
                    in_total = round_half_up(acc * a["share_of_host"])
            aside.append({
                "key": a["key"], "label": a["label"], "after": a["after"],
                "total": total, "total_in_time": in_total,
                "share_of_host": a["share_of_host"],
                "per_day": round_to(total / span, 3),
                "days_median": 0.0 if is_src else weighted_days(sources[i]),
                "sources": source_list(sources[i]),
                "is_source": is_src,
                # תחנת צד שהוזנה יושבת לפני השורה הראשונה שמוצגת, ולכן
                # היא מצוירת בראש ולא אחרי המארח שלה - שאינו מוצג.
                "before_start": is_src and i < start,
            })

        # שלב שאינו על השרשרת ואינו תחנת צד (זימון למבחן מקוון) מוצג
        # כשורת מקור לפני השרשרת, עם הגשר שדרכו הוא נכנס אליה.
        extra = [{
            "key": e["key"], "label": e["label"], "total": e["count"],
            "is_source": True, "via": e["via"], "via_rate": e["via_rate"],
            "via_label": e["via_label"],
            "per_day": round_to(e["count"] / span, 3),
        } for e in entries if e["via"] == "measured"]

        hire = out[-1]
        # מה מזה נכנס בתוך החלון. האוכלוסייה המוכרת מתחלקת אחיד ולכן
        # כולה בפנים; החדשה נמדדת מעקומת הגיוס של השלב שממנו היא באה.
        in_time = None
        if days is not None and days >= 0:
            acc = float(hire["known"])
            for s in sources[len(rows) - 1]:
                share = self.curve_share(s["entry"]["key"], days)
                acc += s["new"] * (0.0 if share is None else share)
            in_time = round_half_up(acc)

        return {
            "days": days, "span_days": span, "annual": days is None,
            "new_only": new_only,
            "year": af["year"], "source": af["source"],
            "known": {
                "label": af["known"]["label"], "hires": hire["known"],
                "per_year": af["known"]["hires_per_year"],
                "ratio": af["known"]["ratio"],
            },
            "new": {
                "label": af["new"]["label"], "hires": hire["new"],
                "ratio": af["new"]["ratio_measured"],
                "hire_rate": af["new"]["hire_rate"],
            },
            "hires": hire["total"],
            "hires_in_time": in_time,
            "known_in_time": hire["known"],
            "new_in_time": (None if in_time is None
                            else in_time - hire["known"]),
            "entries": entries,
            "start_key": rows[start]["key"],
            "rows": out,
            "aside": aside,
            "extra": extra,
            "overlap_warning": len(entries) > 1,
        }

    def flow_funnel(self):
        """משפך הליך הגיוס השנתי, בשתי עמודות: עם האוכלוסייה המוכרת ובלעדיה.

        זהו התרשים עצמו, לא תחזית, ולכן הוא אינו תלוי במה שהוזן. שתי
        העמודות זו לצד זו מראות מה חלקה של האוכלוסייה המוכרת בכל שלב:
        היא אינה עוברת ביום מיון כלל, ולכן העמודה הימנית והשמאלית שם
        זהות, ובגיוס עצמו היא 43% מהנפח.
        """
        af = self.annual_flow()
        if af is None:
            return None
        rows = list(af["chain"]) + [af["hire_row"]]
        first_all = rows[0]["volume"]
        first_new = rows[0]["new"]

        def col(count, prev_count, first_count):
            return {
                "count": count,
                "from_prev": (round_to(count / prev_count, 6)
                              if prev_count else None),
                "from_first": (round_to(count / first_count, 6)
                               if first_count else None),
            }

        out = []
        prev = None
        for i, r in enumerate(rows):
            out.append({
                "key": r["key"], "label": r["label"],
                "is_hire": i == len(rows) - 1,
                "known": r["known"] if r["known_passes"] else 0,
                "known_passes": r["known_passes"],
                "all": col(r["volume"], prev["volume"] if prev else None, first_all),
                "new": col(r["new"], prev["new"] if prev else None, first_new),
            })
            prev = r

        by_key = {r["key"]: r for r in rows}
        aside = [{
            "key": a["key"], "label": a["label"], "after": a["after"],
            "share_of_host": a["share_of_host"],
            "all": col(a["volume"], by_key[a["after"]]["volume"], first_all),
            "new": col(round_half_up(by_key[a["after"]]["new"] * a["share_of_host"]),
                       by_key[a["after"]]["new"], first_new),
        } for a in af["aside"]]

        return {
            "year": af["year"], "source": af["source"],
            "known_label": af["known"]["label"],
            "new_label": af["new"]["label"],
            "known_per_year": af["known"]["hires_per_year"],
            "rows": out, "aside": aside,
        }

    def constrained_gap(self, counts, target_hires, days=None, new_only=False):
        """כמה עוד צריך בכל שלב כדי להגיע ליעד.

        השורה בכל שלב היא **הנפח שהתכנון דורש שם, פחות מה שכבר עובר
        שם**. כך «מה שכבר יש ועוד ההשלמה» שווה בדיוק לדרישה המלאה
        בכל שלב, ולא רק בשלב שהוזן.

        החישוב הקודם תרגם את פער הגיוסים דרך שיעורי המעבר, ומאז
        שהפיצול בין הנתיבים הפך ליחסי הוא חרג: 30,000 הגשות ועוד
        ההשלמה נתנו 103,450, כמות שמניבה 4,687 גיוסים ולא 4,000.
        """
        plan = self.constrained_plan(target_hires, days, new_only)
        if plan is None:
            return None
        af, rows, idx = self._flow_rows()
        span, known_span = self._flow_span(days, new_only)

        proj = self.constrained_combine(counts, days, new_only)
        have = proj["hires"] if proj else 0
        gap = target_hires - have

        flowing = {}
        if proj:
            for r in proj["rows"]:
                flowing[r["key"]] = r["total"]
        needed = {r["key"]: r["total"] for r in plan["rows"]}

        out = []
        for r in af["chain"]:
            total = needed.get(r["key"], 0)
            already = flowing.get(r["key"], 0)
            extra = total - already
            if gap <= 0 or extra < 0:
                extra = 0
            out.append({
                "key": r["key"], "label": r["label"],
                "needed_total": total, "have": already,
                "required": extra,
                "rate": self.blended_rate(r["key"], new_only),
                "per_day": round_to(extra / span, 3),
            })

        return {
            "target": target_hires, "have": have, "gap": gap,
            "days": days, "span_days": span, "annual": days is None,
            "year": af["year"],
            "known": {"label": af["known"]["label"],
                      "hires": plan["known"]["hires"],
                      "per_year": af["known"]["hires_per_year"]},
            "projected": proj,
            "plan": plan,
            "rows": out,
        }

    def _uniform_shares(self, span):
        """חלוקה אחידה של הנתיב הקבוע על פני חלונות הזמן.

        הוא אינו נגזר משום שלב ואינו עובר מיון, ולכן הוא מתחלק לפי
        אורך כל חלון. חלון שכולו אחרי סוף התקופה אינו מקבל דבר,
        והשאר מנורמלים לסכום אחד.
        """
        widths = []
        for b in self.buckets:
            lo = b["min_days"]
            hi = span if b["max_days"] is None else min(b["max_days"], span)
            widths.append(max(0.0, hi - lo) if lo < span else 0.0)
        total = sum(widths)
        return [(w / total if total else None) for w in widths]

    def _measured_buckets(self, from_key, to_key):
        """התפלגות הזמנים שנמדדה בקבצים בין שני שלבים."""
        if from_key is None or from_key == to_key or not self.has_rate(from_key):
            return None
        for f in self.forward(from_key):
            if f["key"] == to_key:
                return f.get("buckets")
        return None

    def constrained_matrix(self, counts, days=None, new_only=False):
        """טבלה אחת: כמה יגיעו לכל שלב, ומתי, על אותה רשת חלונות זמן.

        הכמויות באות מהתזרים ופריסת הזמן מהמדידה. השיעורים של כל
        המקורות מעורבבים במשקל הכמות שכל אחד תורם, והפיזור נעשה על
        הסכום הרץ - ולכן **סכום התאים בשורה שווה בדיוק לסך הכול**.
        טבלה שאינה מסתכמת נראית כמו טעות.

        השלב שהוזן אינו מקבל שורה: מי שכבר שם אינו "מגיע" לשם.
        """
        proj = self.constrained_combine(counts, days, new_only)
        if proj is None:
            return None
        span, known_span = self._flow_span(days, new_only)
        uniform = self._uniform_shares(span)

        def blended(sources, known, key):
            parts = []
            weight = 0.0
            for s in sources or []:
                if s["from"] == key or not s["count"]:
                    continue
                b = self._measured_buckets(s["from"], key)
                if not b:
                    continue
                parts.append((s["count"], {x["key"]: x["share"] for x in b}))
                weight += s["count"]
            total = weight + known
            if not total:
                return None
            out = []
            for i, b in enumerate(self.buckets):
                acc = known * (uniform[i] or 0.0)
                for w, shares in parts:
                    acc += w * (shares.get(b["key"]) or 0.0)
                out.append({"key": b["key"], "label": b["label"],
                            "share": acc / total})
            return out

        rows = []
        order = 0
        for r in list(proj["rows"]) + list(proj["aside"]):
            order += 1
            if r.get("is_source"):
                continue
            known = r.get("known") or 0
            shares = blended(r.get("sources"), known, r["key"])
            if shares is None:
                continue
            rows.append({
                "key": r["key"], "label": r["label"], "count": r["total"],
                "days_median": r["days_median"],
                "is_hire": bool(r.get("is_hire")),
                "is_aside": "share_of_host" in r,
                "known": known,
                "cells": self.spread(r["total"], shares),
                "order": order,
            })

        rows.sort(key=lambda x: ((x["days_median"] if x["days_median"] is not None
                                  else 0.0), x["order"]))
        for r in rows:
            del r["order"]
        return {
            "buckets": [{"key": b["key"], "label": b["label"],
                         "min_days": b["min_days"], "max_days": b["max_days"]}
                        for b in self.buckets],
            "rows": rows,
            "span_days": span, "annual": days is None,
            "hires": proj["hires"],
        }

    def constrained_plan_matrix(self, target_hires, days=None, new_only=False):
        """אותה טבלה, אבל על הכמויות של התכנון עצמו.

        במצב יעד אי אפשר לבנות את הטבלאות מהזנת כמות ההגשות שהתכנון
        החזיר: העיגול בשני הכיוונים אינו זהה, ואז המשפך אומר 2,544
        והטבלה שמתחתיו 2,543 - על אותו שלב, באותו עמוד. כאן הכמויות
        נלקחות מהתכנון עצמו, ולכן הן זהות לחלוטין.
        """
        plan = self.constrained_plan(target_hires, days, new_only)
        if plan is None:
            return None
        span, _ = self._flow_span(days, new_only)
        uniform = self._uniform_shares(span)
        first = plan["rows"][0]["key"]

        def shares_for(key, new_count, known_count):
            total = new_count + known_count
            if not total:
                return None
            buckets = self._measured_buckets(first, key)
            by_key = {x["key"]: x["share"] for x in buckets} if buckets else {}
            if not buckets and not known_count:
                return None
            out = []
            for i, b in enumerate(self.buckets):
                acc = known_count * (uniform[i] or 0.0)
                acc += new_count * (by_key.get(b["key"]) or 0.0)
                out.append({"key": b["key"], "label": b["label"],
                            "share": acc / total})
            return out

        rows = []
        order = 0
        for r in plan["rows"][1:]:
            order += 1
            shares = shares_for(r["key"], r["new"], r["known"])
            if shares is None:
                continue
            rows.append({
                "key": r["key"], "label": r["label"], "count": r["total"],
                "days_median": self._measured_days(first, r["key"]),
                "is_hire": bool(r.get("is_hire")), "is_aside": False,
                "known": r["known"],
                "cells": self.spread(r["total"], shares),
                "order": order,
            })
        for a in plan["aside"]:
            order += 1
            shares = shares_for(a["key"], a["total"], 0)
            if shares is None:
                continue
            rows.append({
                "key": a["key"], "label": a["label"], "count": a["total"],
                "days_median": self._measured_days(first, a["key"]),
                "is_hire": False, "is_aside": True, "known": 0,
                "cells": self.spread(a["total"], shares),
                "order": order,
            })

        rows.sort(key=lambda x: ((x["days_median"] if x["days_median"] is not None
                                  else 0.0), x["order"]))
        for r in rows:
            del r["order"]
        return {
            "buckets": [{"key": b["key"], "label": b["label"],
                         "min_days": b["min_days"], "max_days": b["max_days"]}
                        for b in self.buckets],
            "rows": rows,
            "span_days": span, "annual": days is None,
            "hires": target_hires,
        }

    def constrained_timeline(self, counts, days=None, new_only=False):
        """מתי יתגייסו: הגיוסים הצפויים מפוזרים על חלונות הזמן.

        האוכלוסייה החדשה מתפזרת לפי התפלגות הזמנים שנמדדה לשלב שממנו
        היא נגזרת. האוכלוסייה המוכרת אינה נגזרת משום שלב - היא
        מתחלקת אחיד על פני החלון, ולכן היא מפוזרת לפי אורך כל חלון.
        """
        proj = self.constrained_combine(counts, days, new_only)
        if proj is None:
            return None
        af, rows, idx = self._flow_rows()
        span, known_span = self._flow_span(days, new_only)

        base = [{"key": b["key"], "label": b["label"], "share": 0.0,
                 "hires": 0, "sources": []} for b in self.buckets]

        chain = af["chain"]
        to_hire = {}
        p = 1.0
        for r in reversed(chain):
            p = p * r["rate_to_next"]
            to_hire[r["key"]] = p
        to_hire[af["hire_row"]["key"]] = 1.0

        for e in proj["entries"]:
            hires = e["new"] * to_hire[e["chain_key"]]
            stage = self.stage(e["key"])
            parts = self.spread(hires, stage["buckets"])
            for i, part in enumerate(parts):
                base[i]["hires"] += part["count"]
                base[i]["sources"].append({
                    "from": e["key"], "from_label": e["label"],
                    "from_count": e["count"], "hires": part["count"],
                    "share": part["share"],
                })

        # הנתיב המוכר: אחיד על פני החלון, לפי אותו עוזר שמשמש את הטבלה.
        uniform = self._uniform_shares(span)
        known_buckets = [{
            "key": b["key"], "label": b["label"], "share": uniform[i],
        } for i, b in enumerate(self.buckets)]
        known_parts = self.spread(proj["known"]["hires"], known_buckets)
        for i, part in enumerate(known_parts):
            base[i]["hires"] += part["count"]
            if part["count"]:
                base[i]["sources"].append({
                    "from": None, "from_label": proj["known"]["label"],
                    "from_count": proj["known"]["hires"],
                    "hires": part["count"], "share": part["share"],
                })

        total = sum(r["hires"] for r in base)
        for r in base:
            r["share"] = round_to(r["hires"] / total, 6) if total else 0.0
        return {"rows": base, "total": total, "buckets": len(base),
                "known": proj["known"]["hires"], "new": proj["new"]["hires"]}

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
