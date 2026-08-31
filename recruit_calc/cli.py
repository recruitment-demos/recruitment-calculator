#!/usr/bin/env python3
"""שורת פקודה למחשבון הגיוס.

דוגמאות:
    python3 -m recruit_calc.cli --basis
    python3 -m recruit_calc.cli --from file_check 5000
    python3 -m recruit_calc.cli --from file_check 5000 --from yachbam 300 --target 400
    python3 -m recruit_calc.cli --target 400
    python3 -m recruit_calc.cli --target 400 --by 2027-01-15
    python3 -m recruit_calc.cli --target 400 --entry file_check
"""

import argparse
import datetime

from .engine import load_engine


def pct(x):
    return f"{x * 100:.1f}%"


def parse_day(raw):
    """תאריך יעד בפורמט YYYY-MM-DD, או None."""
    if raw is None:
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise SystemExit(
            f"«{raw}» אינו תאריך תקין. הפורמט הוא YYYY-MM-DD, ויש חודשים "
            f"בני 30 יום - ל-31 בספטמבר, באפריל, ביוני ובנובמבר אין קיום.")


def day_before(target_date, days):
    """התאריך שבו צריך להיות בשלב, כדי לגייס בתאריך היעד."""
    return target_date - datetime.timedelta(days=round(days))


def fmt_day(d):
    return f"{d.day}.{d.month}.{d.year}"


def print_basis(eng):
    m = eng.data["meta"]
    print("מקורות הנתונים")
    print(f"  פעילויות: {m['activity_rows']:,} שורות, {m['activity_candidates']:,} מועמדים, "
          f"{m['activity_first']} עד {m['activity_last']}")
    print(f"  גיוסים:   {m['hire_rows']:,} שורות, {m['hire_candidates']:,} מועמדים, "
          f"{m['hire_first']} עד {m['hire_last']}")
    for s in eng.stages:
        if not s["has_data"]:
            print(f"\n  {s['label']}: אין נתונים במקור")
            continue
        print(f"\n  מתוך «{s['label']}» ממשיכים אל:")
        for f in s["forward"]:
            print(f"    {f['label']:<22}{pct(f['reach']['mid']):>7}   "
                  f"חציון {f['days']['median']:>5.0f} ימים   (n={f['days']['n']:,})")


def main():
    p = argparse.ArgumentParser(description="מחשבון גיוס")
    p.add_argument("--basis", action="store_true", help="הצגת בסיס הנתונים")
    p.add_argument("--from", dest="cohorts", nargs=2, action="append",
                   metavar=("STAGE", "COUNT"),
                   help="קבוצת מועמדים בשלב. אפשר לחזור על הדגל כמה פעמים.")
    p.add_argument("--target", type=int, help="יעד גיוס")
    p.add_argument("--by", metavar="YYYY-MM-DD",
                   help="תאריך היעד. מוסיף עד מתי צריך להיות בכל שלב.")
    p.add_argument("--entry", metavar="STAGE",
                   help="נקודת הכניסה למשפך הרציף. ברירת המחדל: השלב הראשון "
                        "שיש לו נתונים.")
    args = p.parse_args()
    by = parse_day(args.by)

    eng = load_engine()

    if args.basis or not (args.cohorts or args.target):
        print_basis(eng)
        if not (args.cohorts or args.target):
            return
        print()

    if args.cohorts:
        counts = {k: None for k in eng.stage_keys()}
        for key, raw in args.cohorts:
            counts[key] = int(raw)
        result = eng.combine(counts)

        for c in result["cohorts"]:
            print(f"מתוך {c['count']:,} מועמדים ב«{c['label']}» צפויים להגיע:")
            for step in c["steps"]:
                if step["is_source"]:
                    continue
                print(f"  {step['label']:<22}{step['count']:>8,}   "
                      f"בעוד {step['days_median']:>5.0f} ימים   ({pct(step['reach'])})")
            print()

        print("סך הכול לפי שלב:")
        for entry in result["per_stage"]:
            parts = " + ".join(f"{s['count']:,} מ-{s['from_count']:,} ב«{s['from_label']}»"
                               for s in entry["sources"])
            print(f"  {entry['label']:<22}{entry['total']:>8,}   ({parts})")

        if result["overlap_warning"]:
            print("\n  שים לב: הוזנו כמה שלבים. הסכום מניח שמדובר בקבוצות נפרדות.")
            print("  אם אותם מועמדים מופיעים ביותר משלב אחד, הם נספרים פעמיים.")

        for cc in eng.cross_check(counts):
            verdict = {"matches": "תואם", "fewer": "פחות מהצפוי",
                       "more": "יותר מהצפוי"}[cc["verdict"]]
            print(f"\n  בדיקת עקביות: מ-{cc['early_count']:,} ב«{eng.label(cc['early'])}» "
                  f"צפויים {cc['expected']:,} ב«{eng.label(cc['late'])}», "
                  f"הוזנו {cc['actual']:,} - {verdict}.")

        if by is not None:
            cutoff = (by - datetime.date.today()).days
            if cutoff < 0:
                print(f"\n  התאריך {fmt_day(by)} כבר עבר, ולכן לא ניתן לחשב "
                      f"כמה יתגייסו עד אליו.")
            else:
                bd = eng.combined_by_day(counts, cutoff)
                if bd is not None:
                    print(f"\n  עד {fmt_day(by)} (בעוד {cutoff:,} ימים) צפויים "
                          f"{bd['hires']:,} מגויסים, מתוך {bd['eventual']:,} "
                          f"שיתגייסו בסופו של דבר.")
                    for src in bd["sources"]:
                        print(f"    {src['hires']:>6,} מתוך {src['eventual']:,} "
                              f"שיתגייסו מ-{src['from_count']:,} "
                              f"ב«{src['from_label']}»   ({pct(src['share'])} מהם)")

        if args.target is not None:
            against = result["hires"]
            if by is not None:
                cutoff = (by - datetime.date.today()).days
                bd = eng.combined_by_day(counts, cutoff) if cutoff >= 0 else None
                if bd is not None:
                    against = bd["hires"]
            v = eng.target_verdict(against, args.target)
            verdict = {"target_miss": f"חסרים {v['gap']:,}",
                       "target_over": f"עודף של {v['gap']:,}",
                       "target_ok": "היעד מושג"}[v["kind"]]
            print(f"\n  יעד {v['target']:,} | צפוי {v['projected']:,} | {verdict}")

    elif args.target is not None:
        days = None
        if by is not None:
            left = (by - datetime.date.today()).days
            if left < 0:
                raise SystemExit(f"התאריך {fmt_day(by)} כבר עבר.")
            days = left

        plan = eng.required_plan(args.target, days)

        print(f"כמה מועמדים צריך בכל שלב כדי לגייס {args.target:,}" +
              (f" עד {fmt_day(by)} (בעוד {days:,} ימים)" if days is not None else ""))
        print("כל שורה עומדת בפני עצמה. השורות אינן מצטברות זו לזו.\n")
        for row in plan["rows"]:
            if not row["has_data"]:
                print(f"  {row['label']:<22}{'אין נתונים':>10}   {row['note']}")
                continue
            if row["required"] is None:
                print(f"  {row['label']:<22}{'לא יספיק':>10}   "
                      f"אף מועמד שייכנס עכשיו לא יתגייס תוך {days:,} ימים")
                continue
            when = (f"   עד {fmt_day(day_before(by, row['lead_days_median']))}"
                    if by else "")
            flag = ("   [לא מעשי: גדול מ-"
                    f"{row['observed']:,} שנמדדו אי פעם]"
                    if row["observed"] and row["required"] > row["observed"] else "")
            print(f"  {row['label']:<22}{row['required']:>10,}   "
                  f"שיעור {pct(row['effective_rate'])}   "
                  f"חציון {row['lead_days_median']:>5.0f} ימים{when}{flag}")

        entry = args.entry or next(k for k in eng.stage_keys() if eng.has_rate(k))
        pipe = eng.plan_from_target(entry, args.target, days)
        if pipe is None:
            print(f"\n  אין נתונים לשלב «{entry}», ולכן אין ממנו משפך.")
            return

        if pipe["required"] is None:
            print(f"\n  מ«{pipe['label']}» אי אפשר לגייס {args.target:,} "
                  f"תוך {days:,} ימים. צריך להתחיל משלב מאוחר יותר.")
            return

        entry_date = day_before(by, pipe["lead_days_median"]) if by else None
        print(f"\nאותו יעד כמשפך אחד רציף, מ«{pipe['label']}»")
        print(f"  צריך {pipe['required']:,} מועמדים ב«{pipe['label']}»" +
              (f", עד {fmt_day(entry_date)}" if entry_date else "") + ".")
        print(f"  הזנת {pipe['required']:,} ב«{pipe['label']}» במחשבון הרגיל "
              f"תיתן בדיוק את המשפך הזה.\n")
        for step in pipe["projection"]["steps"]:
            if step["is_source"]:
                continue
            when = (f"   סביב {fmt_day(entry_date + datetime.timedelta(days=round(step['days_median'])))}"
                    if entry_date else "")
            print(f"  {step['label']:<22}{step['count']:>10,}   "
                  f"({pct(step['reach'])})   "
                  f"חציון {step['days_median']:>5.0f} ימים{when}")
        if pipe["hires"] != args.target:
            print(f"\n  בגלל עיגול הכמות הנדרשת, התחזית בפועל היא "
                  f"{pipe['hires']:,} מגויסים ולא {args.target:,}.")


if __name__ == "__main__":
    main()
