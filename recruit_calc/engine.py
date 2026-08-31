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
        """הקוהורט הגדול ביותר שנמדד אי פעם בשלב הזה.

        משמש כאמת מידה: דרישה שגדולה בהרבה מכל מה שנמדד אינה מעשית,
        וזו עובדה שאפשר להצביע עליה במקום להשאיר מספר ענק בלי הקשר.
        """
        if not self.has_rate(key):
            return None
        b = self.stage(key)["basis"]
        return max(b["conservative"]["candidates"], b["mature"]["candidates"])

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
                    "measured_on": None, "observed": None, "note": st["note"],
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
            # דרישה שגדולה מכל קוהורט שנמדד אי פעם בשלב אינה בת-ביצוע.
            # זו אמת מידה מהנתונים, לא סף שנקבע מראש.
            feasible = (required is not None and
                        (required == 0 or required <= observed))
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
                "feasible": False,
                "projection": None, "hires": 0, "hires_in_time": 0,
            }
        exact = target_hires / eff
        required = round_half_up(exact)
        projection = self.project_cohort(key, required)
        d = st["days_to_hire"]
        observed = self.observed_candidates(key)
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
            "feasible": required <= observed,
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
