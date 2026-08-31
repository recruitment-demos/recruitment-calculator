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
            want_buckets=False, pair=None):
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
        out["curve"] = hire_curve(days)
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
                        pair=f"{s['key']}->{other}")
            if m is None or m["days"]["n"] < cfg["min_transition_n"]:
                continue
            forward.append({
                "key": other,
                "label": next(x["label"] for x in cfg["stages"] if x["key"] == other),
                "reach": m["reach"], "days": m["days"],
                "window": m["window"], "basis": m["basis"],
            })

        hire_m = measure(src, hire_date, last_hire, conservative_date, cfg,
                         want_buckets=True, pair=f"{s['key']}->hire")
        if hire_m is None:
            sys.exit(f"אין נתוני גיוס לשלב {s['label']}")

        # סדר התצוגה נקבע מהנתונים: לפי חציון הימים עד ההגעה.
        forward.sort(key=lambda f: f["days"]["median"])
        forward.append({
            "key": HIRE_KEY, "label": HIRE_LABEL,
            "reach": hire_m["reach"], "days": hire_m["days"],
            "window": hire_m["window"], "basis": hire_m["basis"],
        })

        stages.append({
            "key": s["key"], "label": s["label"],
            "activity_type": s["activity_type"],
            "has_data": True, "note": s.get("note", ""),
            "hire_rate": hire_m["reach"],
            "days_to_hire": hire_m["days"],
            "hire_window": hire_m["window"],
            "buckets": hire_m["buckets"],
            "hire_curve": hire_m["curve"],
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
