#!/usr/bin/env python3
"""בניית מאגר הנתונים של מחשבון הגיוס מקבצי המקור.

כל מספר במערכת נגזר כאן מקובצי האקסל שבתיקיית «נתונים למערכת».
אין מספרי תוצאה קשיחים בקוד ואין השלמות בהערכה.

שיטת החישוב
-----------
ספירה ברמת מועמד ייחודי: מועמד שהופיע כמה פעמים באותו שלב נספר פעם אחת,
לפי מועד הפעילות הראשונה שלו באותו שלב.

לכל זוג שלבים (משלב מקור לשלב יעד מאוחר יותר) נמדדים שני דברים:
  שיעור הגעה - איזה חלק מהמועמדים שהיו בשלב המקור הגיעו בפועל לשלב היעד.
  זמן הגעה   - כמה ימים חלפו בין השלבים.
שלב היעד יכול להיות גם הגיוס עצמו, ואז שיעור ההגעה הוא יחס הגיוס.

כל שיעור נמדד בשני בסיסים, מפני שהנתונים קטועים מימין (right-censoring):
מועמד שביצע פעילות סמוך לסוף התקופה עדיין לא הספיק להתקדם, ולכן ייראה
כמי שלא הגיע לשלב הבא.

  בסיס א' - כל המועמדים עד תאריך החיתוך הקבוע שב-config, מול ההגעות
            שלהם בכל אורך הקובץ. שלבים מאוחרים בחלון עדיין לא הבשילו,
            ולכן השיעור הזה נוטה כלפי מטה.
  בסיס ב' - רק קוהורטים שהספיקו להבשיל: תאריך החיתוך נקבע כתאריך האירוע
            האחרון בקובץ פחות האחוזון ה-90 של זמן ההגעה (חישוב איטרטיבי
            עד להתכנסות).

השיעור שבשימוש הוא הממוצע בין השניים. שני הבסיסים נשמרים בקובץ הפלט.
"""

import json
import sys

import numpy as np
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "params.json"
OUT_PATH = ROOT / "data" / "recruitment_data.json"

HIRE_KEY = "hire"
HIRE_LABEL = "גיוס"


def activity_types(stage):
    """סוגי הפעילות של שלב. שלב יכול להיות ממופה לכמה סוגים."""
    at = stage.get("activity_type")
    if at is None:
        return []
    return at if isinstance(at, list) else [at]



def annual_flow(cfg, labels):
    """פירוק תזרים הליך הגיוס לשני נתיבים, לפי התרשים שהתקבל.

    התרשים נותן משפך אחד לכל הארגון, ומתחתיו פילוח של הגיוסים לשתי
    אוכלוסיות: «מוכרת» ביחס 1:1 ו«חדשה» ביחס 1:31. שני המספרים האלה
    אינם מתיישבים עם משפך אחד - אם 1,418 מגויסים מגיעים ביחס 1:1, הם
    אינם עוברים סינון, ולכן אינם יכולים להימנות בשלבי הסינון.

    הפירוק כאן הופך את זה למודל מפורש: האוכלוסייה המוכרת עוברת רק
    בתחנות המנהליות (`passes` בקונפיג), האוכלוסייה החדשה עוברת בכל
    השרשרת, ושיעורי המעבר מחושבים על האוכלוסייה החדשה בלבד. זה
    ההבדל בין מחשבון שדורש כמות מטורפת של הגשות לבין מחשבון שאומר
    את האמת: רק חלק מהגיוסים בכלל תלוי בהגשות.

    אין כאן שום מספר שאינו מועתק מהתרשים או נגזר ממנו בחשבון פשוט.
    """
    af = cfg.get("annual_flow")
    if not af:
        return None

    known = af["populations"]["known"]
    new = af["populations"]["new"]
    kh = known["hires"]
    passes = set(known["passes"])

    chain = []
    for item in af["chain"]:
        k = item["key"]
        on_path = k in passes
        chain.append({
            "key": k,
            "label": labels.get(k, k),
            "volume": item["volume"],
            "known": kh if on_path else 0,
            "new": item["volume"] - (kh if on_path else 0),
            "known_passes": on_path,
        })

    hire_row = {
        "key": HIRE_KEY, "label": HIRE_LABEL,
        "volume": af["hires"], "known": kh, "new": af["hires"] - kh,
        "known_passes": True,
    }

    # שיעור ההגעה בין שני שלבים בשרשרת, נמדד על האוכלוסייה החדשה
    # בלבד. שיעור על הנפח המעורב היה מערבב אוכלוסייה שאינה עוברת שם
    # כלל, וכך היה מנפח את המעבר האחרון (יחב"מ->גיוס 80% בתרשים,
    # 70% על האוכלוסייה החדשה).
    steps = chain + [hire_row]
    for i, row in enumerate(steps):
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        row["to_next"] = nxt["key"] if nxt else None
        row["rate_to_next"] = (None if nxt is None or not row["new"]
                               else round(nxt["new"] / row["new"], 6))
        # השיעור שבתרשים עצמו, על הנפח המעורב. נשמר לצורך השוואה בלבד.
        row["chart_rate_to_next"] = (None if nxt is None or not row["volume"]
                                     else round(nxt["volume"] / row["volume"], 6))

    aside = []
    for item in af.get("aside", []):
        host = next(r for r in chain if r["key"] == item["after"])
        aside.append({
            "key": item["key"],
            "label": labels.get(item["key"], item["key"]),
            "after": item["after"],
            "volume": item["volume"],
            # תחנת צד: כולה על האוכלוסייה החדשה, כי המוכרת אינה עוברת
            # סינון בכלל.
            "share_of_host": round(item["volume"] / host["new"], 6),
        })

    return {
        "source": af["source"],
        "year": af["year"],
        "year_days": af["year_days"],
        "hires": af["hires"],
        "known": {
            "label": known["label"], "hires_per_year": kh,
            "ratio": known["ratio"], "fixed": bool(known.get("fixed")),
            "passes": known["passes"],
            "share_of_hires": round(kh / af["hires"], 6),
        },
        "new": {
            "label": new["label"], "hires_per_year": af["hires"] - kh,
            "ratio_stated": new["ratio"],
            "submissions": chain[0]["new"],
            "ratio_measured": round(chain[0]["new"] / (af["hires"] - kh), 4),
            "hire_rate": round((af["hires"] - kh) / chain[0]["new"], 6),
            "share_of_hires": round((af["hires"] - kh) / af["hires"], 6),
        },
        "chain": chain,
        "hire_row": hire_row,
        "aside": aside,
        "overall_rate": round(af["hires"] / chain[0]["volume"], 6),
    }


def load_config():
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_sources(cfg):
    src = cfg["sources"]

    a_cfg = src["activities"]
    ac = a_cfg["columns"]
    files = a_cfg.get("files") or [{"file": a_cfg["file"],
                                    "sheet": a_cfg.get("sheet", "Data")}]

    # שלושת הקבצים הם אותה טבלה בשלושה חתכים חופפים. הם מאוחדים לטבלה
    # אחת, ושורה כפולה - אותו מועמד, אותה פעילות, אותו תאריך - נספרת
    # פעם אחת. בלי האיחוד היו נמדדות תקופות שונות בשלבים שונים.
    frames = []
    for spec in files:
        path = ROOT / spec["file"]
        if not path.exists():
            sys.exit(f"קובץ הפעילויות חסר: {path}")
        df = pd.read_excel(path, sheet_name=spec.get("sheet", "Data"))
        keep = {}
        for name, target in (("candidate", "candidate"),
                             ("activity_type", "activity"),
                             ("date", "date"),
                             ("result", "result"),
                             ("district", "district"),
                             ("requisition", "requisition")):
            col = ac.get(name)
            # עמודה שאינה קיימת בקובץ הזה נשארת ריקה בשורותיו במקום להפיל
            # את הבנייה. «כלל פעולות» למשל אינו כולל את «תוצאה».
            keep[target] = df[col] if col in df.columns else pd.NA
        one = pd.DataFrame(keep)
        one["source_file"] = spec["file"]
        frames.append(one)

    act = pd.concat(frames, ignore_index=True)
    act["candidate"] = act["candidate"].astype(str).str.strip()
    act["date"] = pd.to_datetime(act["date"])
    before = len(act)
    act = act.sort_values("source_file").drop_duplicates(
        subset=["candidate", "activity", "date"], keep="first")
    act = act.reset_index(drop=True)
    duplicates_dropped = before - len(act)

    h_cfg = src["hires"]
    h_path = ROOT / h_cfg["file"]
    if not h_path.exists():
        sys.exit(f"קובץ הגיוסים חסר: {h_path}")
    rec = pd.read_excel(h_path, sheet_name=h_cfg["sheet"])
    hc = h_cfg["columns"]
    rec = rec.rename(columns={
        hc["candidate"]: "candidate",
        hc["date"]: "date",
        hc["group"]: "group",
        hc["profession"]: "profession",
        hc["unit"]: "unit",
    })
    rec["date"] = pd.to_datetime(rec["date"], dayfirst=h_cfg.get("date_dayfirst", True))
    rec["candidate"] = rec["candidate"].astype(str).str.strip()

    return act, rec, duplicates_dropped


def days_between(cohort, event_dates, window=None):
    """ימים מהאירוע בשלב המקור עד האירוע בשלב היעד, למי שהגיע.

    window - חלון (מ, עד) בימים. תצפית מחוצה לו אינה נספרת כהגעה.
    """
    joined = cohort.to_frame("from").join(event_dates.rename("to"), how="inner")
    joined["days"] = (joined["to"] - joined["from"]).dt.days
    ok = joined["days"] >= 0
    if window is not None:
        ok &= (joined["days"] >= window[0]) & (joined["days"] <= window[1])
    return joined.loc[ok, "days"]


def sigma_floor(days, cfg):
    """רצפת סטיות תקן על log(ימים+1). מדווחת בלבד, אינה מסננת.

    נשמרת כדי שאפשר יהיה לראות מדוע היא נפסלה כשיטה: היא נותנת
    לבדיקת קבצים רצפה של כ-4.6 ימים ומשאירה גיוסים תוך שבוע.
    """
    k = cfg.get("duration_filter", {}).get("report_sigmas")
    if not k or len(days) < 2:
        return None
    lg = np.log(days.astype(float) + 1.0)
    return round(float(np.exp(lg.mean() - k * lg.std(ddof=1)) - 1.0), 1)


def antimode_floor(days, cfg):
    """הרצפה, לפי השקע בין האוכלוסייה המזויפת לאמיתית.

    רישום שנעשה בדיעבד יוצר בליטה בימים הראשונים. אחריה יש שקע, ואז
    מתחילה האוכלוסייה שבאמת עברה את התהליך. הרצפה נקבעת בסוף השקע.

    שלוש הגנות מפני זיהוי שווא:
      1. החיפוש נעצר בחציון. בלי זה הוא נתקע ברעש הזנב הדליל.
      2. הבליטה חייבת להיות גדולה פי spike_ratio מהשקע.
      3. גם מה שאחרי השקע חייב להיות גדול פי spike_ratio ממנו.
    בלי שלושתן, התפלגות חלקה אחת נחתכת בטעות. זה בדיוק מה שמונע
    חיתוך של מעבר מהיר אמיתי כמו יחב"מ אל גיוס.

    מחזיר (רצפה, הסבר). רצפה None פירושה שלא נמצאו שתי אוכלוסיות.
    """
    f = cfg.get("duration_filter", {})
    if len(days) < f.get("min_observations", 100):
        return None, "מעט מדי תצפיות לזיהוי אמין"

    d = days.astype(float)
    bin_days = f.get("bin_days", 3)
    ratio = f.get("spike_ratio", 2.0)
    top = float(np.median(d)) if f.get("search_to_median", True) else float(d.max())

    edges = np.arange(0, top + bin_days, bin_days)
    if len(edges) < 6:
        return None, "טווח קצר מדי לזיהוי שקע"
    cnt = np.array([int(((d >= edges[i]) & (d < edges[i + 1])).sum())
                    for i in range(len(edges) - 1)])

    inner = cnt[1:-1]
    if not len(inner):
        return None, "אין אזור פנימי לחפש בו"
    v = int(np.argmin(inner)) + 1
    low = max(int(cnt[v]), 1)
    before = int(cnt[:v].max())
    after = int(cnt[v + 1:].max())

    if before < ratio * low:
        return None, (f"אין בליטה בהתחלה: {before} מול שקע {cnt[v]}, "
                      f"פחות מפי {ratio}")
    if after < ratio * low:
        return None, (f"אין עלייה אחרי השקע: {after} מול {cnt[v]}, "
                      f"פחות מפי {ratio}")

    floor = float(edges[v + 1])
    return floor, (f"בליטה {before} בהתחלה, שקע {cnt[v]} סביב יום "
                   f"{edges[v]:.0f}, ואחריו {after}")


def duration_window(days, cfg, pair=None):
    """חלון התצפיות הקבילות של מעבר אחד, או None אם לא מסננים."""
    f = cfg.get("duration_filter", {})
    if not f.get("enabled"):
        return None, None

    floor, why = antimode_floor(days, cfg)

    # ידע מקצועי שאינו בקבצים גובר על מה שנמצא בהם
    manual = f.get("min_days", {}).get(pair) if pair else None
    if manual is not None and (floor is None or manual > floor):
        floor, why = float(manual), f"רצפה ידנית של {manual} ימים מקובץ ההגדרות"

    if floor is None:
        return None, why
    return (floor, float("inf")), why


def window_record(window, why, days_before, days_after, cfg):
    """תיעוד החלון לשקיפות. נשמר בנתונים ומוצג בעמוד."""
    sig = sigma_floor(days_before, cfg)
    if window is None:
        return {
            "from_days": None, "to_days": None, "reason": why,
            "observations_before": int(len(days_before)),
            "observations_after": int(len(days_after)),
            "dropped_fast": 0, "dropped_slow": 0,
            "sigma_floor_days": sig,
        }
    return {
        "from_days": round(window[0], 1),
        "to_days": None if window[1] == float("inf") else round(window[1], 1),
        "reason": why,
        "observations_before": int(len(days_before)),
        "observations_after": int(len(days_after)),
        "dropped_fast": int((days_before < window[0]).sum()),
        "dropped_slow": int((days_before > window[1]).sum()),
        "sigma_floor_days": sig,
    }


def mature_cutoff(source_dates, event_dates, horizon, percentile, iterations):
    """חיתוך הבשלה: הרחקה מסוף הקובץ באורך האחוזון ה-90 של זמן ההגעה.

    האחוזון עצמו מושפע מהחיתוך, ולכן חוזרים עד להתכנסות.
    מחזיר (תאריך חיתוך, ערך האחוזון בימים).
    """
    cut = horizon
    p = None
    for _ in range(iterations):
        days = days_between(source_dates[source_dates <= cut], event_dates)
        if days.empty:
            return cut, None
        p = float(days.quantile(percentile))
        cut = horizon - pd.Timedelta(days=p)
    return cut, p


def days_stats(days):
    if len(days) == 0:
        return None
    return {
        "n": int(len(days)),
        "mean": round(float(days.mean()), 1),
        "median": round(float(days.median()), 1),
        "p25": round(float(days.quantile(0.25)), 1),
        "p75": round(float(days.quantile(0.75)), 1),
        "p90": round(float(days.quantile(0.90)), 1),
    }


def bucket_shares(days, buckets):
    """התפלגות סדרת ימים לפי הדליים שהוגדרו ב-config."""
    n = len(days)
    out = []
    for b in buckets:
        if n == 0:
            share = None
        else:
            mask = days >= b["min_days"]
            if b["max_days"] is not None:
                mask &= days <= b["max_days"]
            share = round(float(mask.mean()), 6)
        out.append({
            "key": b["key"], "label": b["label"],
            "min_days": b["min_days"], "max_days": b["max_days"],
            "share": share,
        })
    return out


def hire_curve(days):
    """עקומת גיוס מצטברת: איזה חלק מהמגויסים התגייס תוך X ימים.

    נמדדת ישירות מהנתונים, יום ביום, ולא נגזרת מחלונות הזמן. הסיבה:
    שאלה כמו "כמה יתגייסו עד 30.9" נופלת באמצע חלון, וחלוקה יחסית
    בתוך החלון היתה ניחוש על משהו שאפשר פשוט למדוד.

    נשמרות רק הנקודות שבהן העקומה משתנה - כלומר ימים שבהם התגייס
    לפחות מועמד אחד. בין שתי נקודות העקומה שטוחה, ולכן זה מדויק
    לחלוטין ולא דחיסה מאבדת.

    כל איבר הוא [יום, חלק מצטבר].
    """
    n = len(days)
    if n == 0:
        return None
    counts = days.value_counts().sort_index()
    curve = []
    seen = 0
    for day, c in counts.items():
        seen += int(c)
        curve.append([int(day), round(seen / n, 6)])
    return curve


def reached_ids_after(cohort, event_dates, window=None):
    """מי מהקוהורט הגיע לשלב היעד *אחרי* השלב שממנו מודדים.

    מועמד שביצע את פעילות היעד לפני שלב המקור אינו "הגיע" - זו הגשה
    חוזרת או רישום קודם, ולא התקדמות במשפך.

    window - כשהוא נתון, גם מי שהגיע מחוץ לחלון אינו נספר כמי שהגיע.
    תצפית שנפסלה כלא-אמינה נפסלת בשלמותה: אין היגיון לפסול אותה
    בזמנים ולספור אותה בשיעור ההגעה.
    """
    joined = cohort.to_frame("from").join(event_dates.rename("to"), how="inner")
    days = (joined["to"] - joined["from"]).dt.days
    ok = days >= 0
    if window is not None:
        ok &= (days >= window[0]) & (days <= window[1])
    return set(joined.index[ok])


def measure(source_dates, event_dates, horizon, conservative_date, cfg,
            want_buckets=False, want_curve=False, pair=None):
    """מדידת שיעור הגעה וזמן הגעה משלב מקור לשלב יעד, בשני בסיסים."""
    cut, p90 = mature_cutoff(
        source_dates, event_dates, horizon,
        cfg["cutoff"]["mature_percentile"], cfg["cutoff"]["mature_iterations"],
    )
    mat_cohort = source_dates[source_dates <= cut]
    cons_cohort = source_dates[source_dates <= conservative_date]
    cons_n, mat_n = int(len(cons_cohort)), int(len(mat_cohort))
    if cons_n == 0 or mat_n == 0:
        return None

    # החלון נקבע מהקוהורט הבשל, שהוא המדידה השלמה ביותר של המעבר הזה,
    # ואז מוחל על שני הבסיסים כדי ששניהם ימדדו את אותו דבר.
    raw_days = days_between(mat_cohort, event_dates)
    window, why = duration_window(raw_days, cfg, pair)

    cons_reached = int(len(reached_ids_after(cons_cohort, event_dates, window)))
    mat_reached = int(len(reached_ids_after(mat_cohort, event_dates, window)))

    cons_rate = cons_reached / cons_n
    mat_rate = mat_reached / mat_n
    low, high = sorted([cons_rate, mat_rate])

    days = days_between(mat_cohort, event_dates, window)
    stats = days_stats(days)
    if stats is None:
        return None

    out = {
        "reach": {
            "low": round(low, 6),
            "high": round(high, 6),
            "mid": round((low + high) / 2, 6),
        },
        "days": stats,
        "window": window_record(window, why, raw_days, days, cfg),
        "basis": {
            "conservative": {
                "cutoff": conservative_date.date().isoformat(),
                "candidates": cons_n, "reached": cons_reached,
                "rate": round(cons_rate, 6),
            },
            "mature": {
                "cutoff": cut.date().isoformat(),
                "followup_days_p90": round(p90, 1) if p90 is not None else None,
                "candidates": mat_n, "reached": mat_reached,
                "rate": round(mat_rate, 6),
            },
        },
    }
    if want_buckets:
        out["buckets"] = bucket_shares(days, cfg["time_buckets"])
    if want_curve:
        out["curve"] = hire_curve(days)
    return out


def hire_coverage(stage_dates, hire_date, activity_first, p90_lead):
    """איזה חלק מהמגויסים בכלל עברו דרך השלב הזה, לפי הקבצים.

    זה המספר שמונע את הטעות הקשה ביותר בקריאת המשפך: שיעור המעבר
    אומר מה קורה למי שנמצא בשלב, ולא אומר דבר על כמה מהגיוסים בכלל
    עוברים שם. שלב שרק שליש מהמגויסים נרשמו בו אינו יושב מעל כל
    המשפך, וכמות שמוזנת בו אינה יכולה להסביר את כלל הגיוסים.

    שתי מדידות, כי יש שתי סיבות שונות לכיסוי חלקי:

      overall - מכלל המגויסים. מוטה כלפי מטה בגלל קטיעה משמאל:
                מי שהתגייס בינואר 2026 הגיש ב-2025, לפני תחילת
                הקובץ, ולכן ההגשה שלו אינה קיימת בו.

      covered - רק מגויסים שהחלון שלפניהם מכוסה בקובץ, כלומר
                שתאריך הגיוס פחות האחוזון ה-90 של זמן ההגעה נופל
                אחרי תחילת הנתונים. כאן הקטיעה משמאל כבר לא פועלת,
                ומה שנשאר הוא כיסוי אמיתי חסר.
    """
    ids = hire_date.index.intersection(stage_dates.index)
    before = sum(1 for c in ids if stage_dates[c] <= hire_date[c])
    total = len(hire_date)

    if p90_lead is None:
        return {"overall": round(before / total, 6) if total else None,
                "overall_n": before, "hires": total,
                "covered": None, "covered_n": None, "covered_hires": None}

    edge = activity_first + pd.Timedelta(days=p90_lead)
    late = hire_date[hire_date >= edge]
    late_ids = late.index.intersection(stage_dates.index)
    late_before = sum(1 for c in late_ids if stage_dates[c] <= late[c])

    return {
        "overall": round(before / total, 6) if total else None,
        "overall_n": before,
        "hires": total,
        "covered": round(late_before / len(late), 6) if len(late) else None,
        "covered_n": late_before,
        "covered_hires": int(len(late)),
        "covered_from": edge.date().isoformat(),
    }


def build_funnel(cfg, first, hire_date, data_keys, last_activity,
                 conservative_date, last_hire, first_date_of_data):
    """המשפך המלא: כמה מועמדים ייחודיים נמדדו בכל שלב, ומה עובר הלאה.

    שתי מדידות נפרדות לכל שלב, ושתיהן ישירות:
      from_prev  - המעבר מהשלב שלפניו, נמדד בין שני השלבים האלה בלבד.
      from_first - המעבר מהשלב הראשון, נמדד בין השלב הראשון לשלב הזה.

    from_first אינו מכפלה של אחוזי from_prev. המשפך אינו סדרתי - יש
    מועמדים שמדלגים על שלב ויש שנכנסים באמצע - ולכן שרשור אחוזים היה
    מייצר מספרים שאינם בנתונים.

    candidates הוא ספירה גולמית: כמה מועמדים ייחודיים הופיעו אי פעם
    בשלב הזה בקבצים. זה לא קוהורט מדוד אלא היקף התנועה בפועל.
    """
    first_key = data_keys[0]
    rows = []
    prev = None
    for key in data_keys:
        st = next(x for x in cfg["stages"] if x["key"] == key)
        src = first[key]
        row = {
            "key": key,
            "label": st["label"],
            "candidates": int(len(src)),
            "first_date": src.min().date().isoformat() if len(src) else None,
            "last_date": src.max().date().isoformat() if len(src) else None,
            "from_prev": None,
            "from_first": None,
            "coverage": None,
            "is_hire": False,
        }
        if prev is not None:
            m = measure(first[prev], src, last_activity, conservative_date, cfg,
                        pair=f"{prev}->{key}")
            if m is not None:
                row["from_prev"] = {
                    "key": prev,
                    "label": next(x["label"] for x in cfg["stages"]
                                  if x["key"] == prev),
                    "reach": m["reach"], "days": m["days"], "basis": m["basis"],
                }
        if key != first_key:
            m = measure(first[first_key], src, last_activity, conservative_date,
                        cfg, pair=f"{first_key}->{key}")
            if m is not None:
                row["from_first"] = {
                    "key": first_key,
                    "label": next(x["label"] for x in cfg["stages"]
                                  if x["key"] == first_key),
                    "reach": m["reach"], "days": m["days"], "basis": m["basis"],
                }
        m = measure(src, hire_date, last_hire, conservative_date, cfg,
                    pair=f"{key}->hire")
        row["coverage"] = hire_coverage(
            src, hire_date, first_date_of_data,
            m["days"]["p90"] if m else None)
        rows.append(row)
        prev = key

    hired = hire_date
    row = {
        "key": HIRE_KEY, "label": HIRE_LABEL,
        "candidates": int(len(hired)),
        "first_date": hired.min().date().isoformat() if len(hired) else None,
        "last_date": hired.max().date().isoformat() if len(hired) else None,
        "from_prev": None, "from_first": None,
        "coverage": {"overall": 1.0, "overall_n": int(len(hired)),
                     "hires": int(len(hired)), "covered": 1.0,
                     "covered_n": int(len(hired)),
                     "covered_hires": int(len(hired))},
        "is_hire": True,
    }
    m = measure(first[prev], hired, last_hire, conservative_date, cfg,
                pair=f"{prev}->hire")
    if m is not None:
        row["from_prev"] = {
            "key": prev,
            "label": next(x["label"] for x in cfg["stages"] if x["key"] == prev),
            "reach": m["reach"], "days": m["days"], "basis": m["basis"],
        }
    m = measure(first[first_key], hired, last_hire, conservative_date, cfg,
                pair=f"{first_key}->hire")
    if m is not None:
        row["from_first"] = {
            "key": first_key,
            "label": next(x["label"] for x in cfg["stages"]
                          if x["key"] == first_key),
            "reach": m["reach"], "days": m["days"], "basis": m["basis"],
        }
    rows.append(row)
    return {"first_key": first_key, "rows": rows}


def assign_segments(act, cfg, first):
    """שיוך כל מועמד לפלח אחד לפי עמודת «דרישה».

    הדרישה נלקחת מרשומת ההגשה של המועמד. למי שאין לו רשומת הגשה
    בקבצים, נלקחת הדרישה מהפעילות המוקדמת ביותר שלו. מועמד מקבל
    שיוך אחד בלבד, כדי שסכום הפלחים לא יעלה על המספר האמיתי.
    """
    seg_cfg = cfg.get("segments")
    if not seg_cfg:
        return None, None

    sub_types = activity_types(
        next(s for s in cfg["stages"] if s["key"] == "submissions"))
    rows = act.dropna(subset=["requisition"]).copy()
    rows["requisition"] = rows["requisition"].astype(str).str.strip()

    subs = rows[rows["activity"].isin(sub_types)].sort_values("date")
    req = subs.groupby("candidate")["requisition"].first()

    rest = rows[~rows["candidate"].isin(req.index)].sort_values("date")
    req = pd.concat([req, rest.groupby("candidate")["requisition"].first()])

    groups = []
    for g in seg_cfg["groups"]:
        if g["match"] is None:
            members = None          # None = כל המועמדים, בלי סינון
        else:
            wanted = {m.strip() for m in g["match"]}
            members = set(req.index[req.isin(wanted)])
        groups.append({"key": g["key"], "label": g["label"],
                       "match": g["match"], "members": members})
    return groups, req


def segment_funnel(groups, first, hire_date, data_keys, cfg,
                   last_activity, conservative_date, last_hire,
                   first_date_of_data):
    """אותו משפך, בנפרד לכל פלח. זה מה שמראה את הפער בין הערוצים."""
    out = []
    for g in groups:
        sub_first = {}
        for k in data_keys:
            src = first[k]
            sub_first[k] = src if g["members"] is None else src[
                src.index.isin(g["members"])]
        sub_hire = hire_date if g["members"] is None else hire_date[
            hire_date.index.isin(g["members"])]
        if any(len(v) == 0 for v in sub_first.values()) or len(sub_hire) == 0:
            out.append({"key": g["key"], "label": g["label"],
                        "match": g["match"], "funnel": None,
                        "note": "אין מספיק נתונים בפלח הזה"})
            continue
        out.append({
            "key": g["key"], "label": g["label"], "match": g["match"],
            "funnel": build_funnel(cfg, sub_first, sub_hire, data_keys,
                                   last_activity, conservative_date, last_hire,
                                   first_date_of_data),
            "note": "",
        })
    return out


def main():
    cfg = load_config()
    act, rec, duplicates_dropped = load_sources(cfg)

    hire_date = rec.groupby("candidate")["date"].min()
    hired_ids = set(hire_date.index)
    last_hire = rec["date"].max()
    last_activity = act["date"].max()
    conservative_date = pd.Timestamp(cfg["cutoff"]["conservative_date"])

    # מועד הפעילות הראשונה של כל מועמד בכל שלב.
    # שלב יכול להיות ממופה לכמה סוגי פעילות - «הגשות» למשל מורכב
    # משלוש צורות של הקמת מועמדות, והמוקדמת שבהן היא ההגשה.
    first = {}
    for s in cfg["stages"]:
        if s["activity_type"] is None:
            continue
        types = activity_types(s)
        rows = act[act["activity"].isin(types)]
        if rows.empty:
            sys.exit(f"סוגי הפעילות {types} לא נמצאו בקובצי הפעילויות.")
        first[s["key"]] = rows.groupby("candidate")["date"].min()

    data_keys = [s["key"] for s in cfg["stages"] if s["activity_type"] is not None]
    stages = []

    for s in cfg["stages"]:
        if s["activity_type"] is None:
            # שלב שאין לו מקור בקבצים - נרשם במפורש כחסר ולא מוערך.
            stages.append({
                "key": s["key"], "label": s["label"], "activity_type": None,
                "has_data": False, "note": s.get("note", ""),
                "hire_coverage": None, "observed": None,
                "hire_rate": None, "days_to_hire": None,
                "buckets": None, "hire_curve": None, "hire_window": None,
                "basis": None, "forward": None,
            })
            continue

        src = first[s["key"]]
        forward = []

        # שלבי היעד: רק שלבים שבאים אחרי השלב הזה בסדר התהליך.
        # הסדר שב-config תואם את הסדר שנמדד בפועל לפי חציון הימים.
        later = data_keys[data_keys.index(s["key"]) + 1:]
        for other in later:
            m = measure(src, first[other], last_activity, conservative_date, cfg,
                        want_buckets=True, pair=f"{s['key']}->{other}")
            if m is None or m["days"]["n"] < cfg["min_transition_n"]:
                continue
            forward.append({
                "key": other,
                "label": next(x["label"] for x in cfg["stages"] if x["key"] == other),
                "reach": m["reach"], "days": m["days"],
                "buckets": m["buckets"],
                "window": m["window"], "basis": m["basis"],
            })

        hire_m = measure(src, hire_date, last_hire, conservative_date, cfg,
                         want_buckets=True, want_curve=True,
                         pair=f"{s['key']}->hire")
        if hire_m is None:
            sys.exit(f"אין נתוני גיוס לשלב {s['label']}")

        # סדר התצוגה נקבע מהנתונים: לפי חציון הימים עד ההגעה.
        forward.sort(key=lambda f: f["days"]["median"])
        forward.append({
            "key": HIRE_KEY, "label": HIRE_LABEL,
            "reach": hire_m["reach"], "days": hire_m["days"],
            "buckets": hire_m["buckets"],
            "window": hire_m["window"], "basis": hire_m["basis"],
        })

        # היקף התנועה האמיתי בשלב: כמה מועמדים ייחודיים עברו בו, על פני
        # כמה ימים. זו אמת המידה לשאלה אם דרישה היא מעשית - אבל רק מול
        # חלון זמן באותו אורך. דרישה בלי תאריך יעד אינה מוגבלת בכלל,
        # ואין להשוות אותה לכמות שנמדדה ב-229 ימים.
        span_days = int((src.max() - src.min()).days) + 1 if len(src) else 0
        observed = {
            "candidates": int(len(src)),
            "first_date": src.min().date().isoformat() if len(src) else None,
            "last_date": src.max().date().isoformat() if len(src) else None,
            "days": span_days,
            "per_day": round(len(src) / span_days, 6) if span_days else None,
        }

        coverage = hire_coverage(
            src, hire_date, act["date"].min(),
            hire_m["days"]["p90"] if hire_m["days"] else None)

        stages.append({
            "key": s["key"], "label": s["label"],
            "activity_type": s["activity_type"],
            "has_data": True, "note": s.get("note", ""),
            "hire_coverage": coverage,
            "observed": observed,
            "hire_rate": hire_m["reach"],
            "days_to_hire": hire_m["days"],
            "hire_window": hire_m["window"],
            "buckets": hire_m["buckets"],
            "hire_curve": hire_m["curve"],
            "basis": hire_m["basis"],
            "forward": forward,
        })

    known_types = {t for s in cfg["stages"] for t in activity_types(s)}
    unmapped = sorted(set(act["activity"].dropna().unique()) - known_types)
    hires_without_activity = int(len(hired_ids - set(act["candidate"])))

    first_date_of_data = act["date"].min()
    funnel = build_funnel(cfg, first, hire_date, data_keys, last_activity,
                          conservative_date, last_hire, first_date_of_data)
    groups, req = assign_segments(act, cfg, first)
    segments = (None if groups is None else
                segment_funnel(groups, first, hire_date, data_keys, cfg,
                               last_activity, conservative_date, last_hire,
                               first_date_of_data))

    hire_span = int((last_hire - rec["date"].min()).days) + 1
    dataset = {
        "gap_tolerance": cfg["gap_tolerance"],
        # היקף הגיוס שנמדד בפועל. זו נקודת הייחוס לתכנון לפי נפח:
        # כדי לגייס פי X, כל המשפך צריך לרוץ פי X.
        "hire_observed": {
            "candidates": int(len(hired_ids)),
            "first_date": rec["date"].min().date().isoformat(),
            "last_date": last_hire.date().isoformat(),
            "days": hire_span,
            "per_day": round(len(hired_ids) / hire_span, 6),
        },
        "coverage_warning_below": cfg["coverage_warning_below"],
        "selective_below": cfg["selective_below"],
        "funnel": funnel,
        # תזרים 2025 מהתרשים שהתקבל: הבסיס לתכנון עם האילוצים.
        "annual_flow": annual_flow(
            cfg, {s["key"]: s["label"] for s in cfg["stages"]}),
        "segments": segments,
        "hire_key": HIRE_KEY,
        "hire_label": HIRE_LABEL,
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "activities_files": [f["file"] for f in
                                 cfg["sources"]["activities"]["files"]],
            "activity_duplicate_rows_dropped": duplicates_dropped,
            "hires_file": cfg["sources"]["hires"]["file"],
            "activity_rows": int(len(act)),
            "activity_candidates": int(act["candidate"].nunique()),
            "activity_first": act["date"].min().date().isoformat(),
            "activity_last": last_activity.date().isoformat(),
            "hire_rows": int(len(rec)),
            "hire_candidates": int(len(hired_ids)),
            "hire_first": rec["date"].min().date().isoformat(),
            "hire_last": last_hire.date().isoformat(),
            "conservative_cutoff": conservative_date.date().isoformat(),
            "unmapped_activity_types": unmapped,
            "hires_without_activity": hires_without_activity,
        },
        # מיפוי הסטטוסים של קובץ «מועמדים פעילים». הקובץ עצמו נקרא
        # בדפדפן ואינו נכנס לכאן - רק כללי המיפוי, כדי שלא ייכתבו בקוד.
        "active_import": cfg["active_import"],
        "duration_filter": cfg["duration_filter"],
        "time_buckets": cfg["time_buckets"],
        "stages": stages,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(dataset, fh, ensure_ascii=False, indent=2)

    print(f"נכתב {OUT_PATH.relative_to(ROOT)}")
    print(f"  פעילויות: {len(act):,} שורות, {act['candidate'].nunique():,} מועמדים ייחודיים")
    print(f"  גיוסים:   {len(rec):,} שורות, {len(hired_ids):,} מועמדים ייחודיים")
    for s in stages:
        if not s["has_data"]:
            print(f"\n  {s['label']}: אין נתונים במקור")
            continue
        print(f"\n  מתוך «{s['label']}» ממשיכים אל:")
        for f in s["forward"]:
            print(f"    {f['label']:<22} {f['reach']['mid']*100:5.1f}%   "
                  f"חציון {f['days']['median']:>5.0f} ימים   (n={f['days']['n']:,})")
    if unmapped:
        print(f"\n  סוגי פעילות שלא מופו: {', '.join(unmapped)}")


if __name__ == "__main__":
    main()
