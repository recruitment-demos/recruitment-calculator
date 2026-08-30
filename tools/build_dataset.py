#!/usr/bin/env python3
"""בניית מאגר הנתונים של מחשבון הגיוס מקבצי המקור.

כל מספר במערכת נגזר כאן מקובצי האקסל שבתיקיית «נתונים למערכת».
אין מספרי תוצאה קשיחים בקוד ואין השלמות בהערכה.

שיטת החישוב
-----------
ספירה ברמת מועמד ייחודי: מועמד שהופיע כמה פעמים באותו שלב נספר פעם אחת.

לכל שלב מחושב יחס המרה לגיוס כטווח, מפני שהנתונים קטועים מימין
(right-censoring): מועמד שביצע פעילות סמוך לסוף התקופה עדיין לא הספיק
להתגייס, ולכן ייראה כמי שלא התגייס.

  גבול תחתון  - כל המועמדים עד תאריך החיתוך הקבוע שב-config, מול הגיוסים
                שלהם בכל אורך הקובץ. שלבים מאוחרים בחלון עדיין לא הבשילו,
                ולכן היחס הזה נוטה כלפי מטה.
  גבול עליון  - רק קוהורטים שהספיקו להבשיל: תאריך החיתוך לכל שלב נקבע
                כתאריך הגיוס האחרון בקובץ פחות האחוזון ה-90 של זמן הגיוס
                באותו שלב (חישוב איטרטיבי עד להתכנסות).

זמני הגיוס נמדדים מהפעילות הראשונה של המועמד בשלב ועד לגיוסו הראשון,
על קוהורט הבשל בלבד.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "params.json"
OUT_PATH = ROOT / "data" / "recruitment_data.json"


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
            "key": b["key"],
            "label": b["label"],
            "min_days": b["min_days"],
            "max_days": b["max_days"],
            "share": share,
        })
    return out


def mature_cutoff(first_activity, hire_date, last_hire, percentile, iterations):
    """חיתוך הבשלה לשלב: הרחקה מסוף הקובץ באורך האחוזון ה-90 של זמן הגיוס.

    מחושב איטרטיבית - האחוזון עצמו מושפע מהחיתוך, ולכן חוזרים עד להתכנסות.
    מחזיר (תאריך חיתוך, ערך האחוזון בימים).
    """
    cut = last_hire
    p = None
    for _ in range(iterations):
        cohort = first_activity[first_activity <= cut]
        joined = cohort.to_frame("act").join(hire_date.rename("hire"), how="inner")
        joined["days"] = (joined["hire"] - joined["act"]).dt.days
        joined = joined[joined["days"] >= 0]
        if joined.empty:
            return cut, None
        p = float(joined["days"].quantile(percentile))
        cut = last_hire - pd.Timedelta(days=p)
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


def build_stage(stage_cfg, act, hire_date, hired_ids, cfg, last_hire, conservative_date):
    label = stage_cfg["label"]
    activity_type = stage_cfg["activity_type"]

    if activity_type is None:
        # שלב שאין לו מקור בקבצים - נרשם במפורש כחסר ולא מוערך.
        return {
            "key": stage_cfg["key"],
            "label": label,
            "activity_type": None,
            "has_data": False,
            "note": stage_cfg.get("note", ""),
            "hire_rate": None,
            "days_to_hire": None,
            "buckets": None,
            "basis": None,
        }

    rows = act[act["activity"] == activity_type]
    if rows.empty:
        sys.exit(f"סוג הפעילות '{activity_type}' לא נמצא בקובץ הפעילויות.")

    first_activity = rows.groupby("candidate")["date"].min()

    # --- גבול תחתון: חלון קבוע, גיוסים לאורך כל הקובץ ---
    cons_cohort = first_activity[first_activity <= conservative_date]
    cons_n = int(len(cons_cohort))
    cons_hired = int(len(set(cons_cohort.index) & hired_ids))

    # --- גבול עליון: קוהורט בשל בלבד ---
    cut, p90 = mature_cutoff(
        first_activity, hire_date, last_hire,
        cfg["cutoff"]["mature_percentile"], cfg["cutoff"]["mature_iterations"],
    )
    mat_cohort = first_activity[first_activity <= cut]
    mat_n = int(len(mat_cohort))
    mat_hired = int(len(set(mat_cohort.index) & hired_ids))

    cons_rate = cons_hired / cons_n if cons_n else None
    mat_rate = mat_hired / mat_n if mat_n else None
    low, high = sorted([cons_rate, mat_rate])

    # --- זמני גיוס על הקוהורט הבשל ---
    joined = mat_cohort.to_frame("act").join(hire_date.rename("hire"), how="inner")
    joined["days"] = (joined["hire"] - joined["act"]).dt.days
    days = joined.loc[joined["days"] >= 0, "days"]

    return {
        "key": stage_cfg["key"],
        "label": label,
        "activity_type": activity_type,
        "has_data": True,
        "note": stage_cfg.get("note", ""),
        "hire_rate": {
            "low": round(low, 6),
            "high": round(high, 6),
            "mid": round((low + high) / 2, 6),
        },
        "days_to_hire": days_stats(days),
        "buckets": bucket_shares(days, cfg["time_buckets"]),
        "basis": {
            "conservative": {
                "cutoff": conservative_date.date().isoformat(),
                "candidates": cons_n,
                "hired": cons_hired,
                "rate": round(cons_rate, 6) if cons_rate is not None else None,
            },
            "mature": {
                "cutoff": cut.date().isoformat(),
                "followup_days_p90": round(p90, 1) if p90 is not None else None,
                "candidates": mat_n,
                "hired": mat_hired,
                "rate": round(mat_rate, 6) if mat_rate is not None else None,
            },
        },
    }


def main():
    cfg = load_config()
    act, rec = load_sources(cfg)

    hire_date = rec.groupby("candidate")["date"].min()
    hired_ids = set(hire_date.index)
    last_hire = rec["date"].max()
    conservative_date = pd.Timestamp(cfg["cutoff"]["conservative_date"])

    stages = [
        build_stage(s, act, hire_date, hired_ids, cfg, last_hire, conservative_date)
        for s in cfg["stages"]
    ]

    known_types = {s["activity_type"] for s in cfg["stages"] if s["activity_type"]}
    unmapped = sorted(set(act["activity"].dropna().unique()) - known_types)
    hires_without_activity = int(len(hired_ids - set(act["candidate"])))

    dataset = {
        "gap_tolerance": cfg["gap_tolerance"],
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "activities_file": cfg["sources"]["activities"]["file"],
            "hires_file": cfg["sources"]["hires"]["file"],
            "activity_rows": int(len(act)),
            "activity_candidates": int(act["candidate"].nunique()),
            "activity_first": act["date"].min().date().isoformat(),
            "activity_last": act["date"].max().date().isoformat(),
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
            print(f"  {s['label']:<20} אין נתונים במקור")
            continue
        r = s["hire_rate"]
        d = s["days_to_hire"]
        print(f"  {s['label']:<20} יחס גיוס {r['mid']*100:5.1f}%   "
              f"(נמדד {r['low']*100:.1f}% ו-{r['high']*100:.1f}%)   "
              f"חציון {d['median']:.0f} ימים (n={d['n']:,})")
    if unmapped:
        print(f"  סוגי פעילות שלא מופו: {', '.join(unmapped)}")


if __name__ == "__main__":
    main()
