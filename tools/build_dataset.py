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
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "params.json"
OUT_PATH = ROOT / "data" / "recruitment_data.json"

HIRE_KEY = "hire"
HIRE_LABEL = "גיוס"


def load_config():
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_sources(cfg):
    src = cfg["sources"]

    a_cfg = src["activities"]
    a_path = ROOT / a_cfg["file"]
    if not a_path.exists():
        sys.exit(f"קובץ הפעילויות חסר: {a_path}")
    act = pd.read_excel(a_path, sheet_name=a_cfg["sheet"])
    ac = a_cfg["columns"]
    act = act.rename(columns={
        ac["candidate"]: "candidate",
        ac["activity_type"]: "activity",
        ac["date"]: "date",
        ac["result"]: "result",
        ac["district"]: "district",
        ac["requisition"]: "requisition",
    })
    act["date"] = pd.to_datetime(act["date"])

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

    return act, rec


def days_between(cohort, event_dates):
    """ימים מהאירוע בשלב המקור עד האירוע בשלב היעד, למי שהגיע."""
    joined = cohort.to_frame("from").join(event_dates.rename("to"), how="inner")
    joined["days"] = (joined["to"] - joined["from"]).dt.days
    return joined.loc[joined["days"] >= 0, "days"]


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


def reached_ids_after(cohort, event_dates):
    """מי מהקוהורט הגיע לשלב היעד *אחרי* השלב שממנו מודדים.

    מועמד שביצע את פעילות היעד לפני שלב המקור אינו "הגיע" - זו הגשה
    חוזרת או רישום קודם, ולא התקדמות במשפך.
    """
    joined = cohort.to_frame("from").join(event_dates.rename("to"), how="inner")
    return set(joined.index[joined["to"] >= joined["from"]])


def measure(source_dates, event_dates, horizon, conservative_date, cfg,
            want_buckets=False):
    """מדידת שיעור הגעה וזמן הגעה משלב מקור לשלב יעד, בשני בסיסים."""
    cons_cohort = source_dates[source_dates <= conservative_date]
    cons_n = int(len(cons_cohort))
    cons_reached = int(len(reached_ids_after(cons_cohort, event_dates)))

    cut, p90 = mature_cutoff(
        source_dates, event_dates, horizon,
        cfg["cutoff"]["mature_percentile"], cfg["cutoff"]["mature_iterations"],
    )
    mat_cohort = source_dates[source_dates <= cut]
    mat_n = int(len(mat_cohort))
    mat_reached = int(len(reached_ids_after(mat_cohort, event_dates)))

    if cons_n == 0 or mat_n == 0:
        return None

    cons_rate = cons_reached / cons_n
    mat_rate = mat_reached / mat_n
    low, high = sorted([cons_rate, mat_rate])

    days = days_between(mat_cohort, event_dates)
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
    return out


def main():
    cfg = load_config()
    act, rec = load_sources(cfg)

    hire_date = rec.groupby("candidate")["date"].min()
    hired_ids = set(hire_date.index)
    last_hire = rec["date"].max()
    last_activity = act["date"].max()
    conservative_date = pd.Timestamp(cfg["cutoff"]["conservative_date"])

    # מועד הפעילות הראשונה של כל מועמד בכל שלב
    first = {}
    for s in cfg["stages"]:
        if s["activity_type"] is None:
            continue
        rows = act[act["activity"] == s["activity_type"]]
        if rows.empty:
            sys.exit(f"סוג הפעילות '{s['activity_type']}' לא נמצא בקובץ הפעילויות.")
        first[s["key"]] = rows.groupby("candidate")["date"].min()

    data_keys = [s["key"] for s in cfg["stages"] if s["activity_type"] is not None]
    stages = []

    for s in cfg["stages"]:
        if s["activity_type"] is None:
            # שלב שאין לו מקור בקבצים - נרשם במפורש כחסר ולא מוערך.
            stages.append({
                "key": s["key"], "label": s["label"], "activity_type": None,
                "has_data": False, "note": s.get("note", ""),
                "hire_rate": None, "days_to_hire": None,
                "buckets": None, "basis": None, "forward": None,
            })
            continue

        src = first[s["key"]]
        forward = []

        # שלבי היעד: רק שלבים שבאים אחרי השלב הזה בסדר התהליך.
        # הסדר שב-config תואם את הסדר שנמדד בפועל לפי חציון הימים.
        later = data_keys[data_keys.index(s["key"]) + 1:]
        for other in later:
            m = measure(src, first[other], last_activity, conservative_date, cfg)
            if m is None or m["days"]["n"] < cfg["min_transition_n"]:
                continue
            forward.append({
                "key": other,
                "label": next(x["label"] for x in cfg["stages"] if x["key"] == other),
                "reach": m["reach"], "days": m["days"], "basis": m["basis"],
            })

        hire_m = measure(src, hire_date, last_hire, conservative_date, cfg,
                         want_buckets=True)
        if hire_m is None:
            sys.exit(f"אין נתוני גיוס לשלב {s['label']}")

        # סדר התצוגה נקבע מהנתונים: לפי חציון הימים עד ההגעה.
        forward.sort(key=lambda f: f["days"]["median"])
        forward.append({
            "key": HIRE_KEY, "label": HIRE_LABEL,
            "reach": hire_m["reach"], "days": hire_m["days"],
            "basis": hire_m["basis"],
        })

        stages.append({
            "key": s["key"], "label": s["label"],
            "activity_type": s["activity_type"],
            "has_data": True, "note": s.get("note", ""),
            "hire_rate": hire_m["reach"],
            "days_to_hire": hire_m["days"],
            "buckets": hire_m["buckets"],
            "basis": hire_m["basis"],
            "forward": forward,
        })

    known_types = {s["activity_type"] for s in cfg["stages"] if s["activity_type"]}
    unmapped = sorted(set(act["activity"].dropna().unique()) - known_types)
    hires_without_activity = int(len(hired_ids - set(act["candidate"])))

    dataset = {
        "gap_tolerance": cfg["gap_tolerance"],
        "hire_key": HIRE_KEY,
        "hire_label": HIRE_LABEL,
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "activities_file": cfg["sources"]["activities"]["file"],
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
