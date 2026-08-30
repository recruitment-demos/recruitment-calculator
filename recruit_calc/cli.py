#!/usr/bin/env python3
"""שורת פקודה למחשבון הגיוס.

דוגמאות:
    python3 -m recruit_calc.cli --basis
    python3 -m recruit_calc.cli --from file_check 5000
    python3 -m recruit_calc.cli --from file_check 5000 --from yachbam 300 --target 400
    python3 -m recruit_calc.cli --target 400
"""

import argparse

from .engine import load_engine


def pct(x):
    return f"{x * 100:.1f}%"


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
    args = p.parse_args()

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

        if args.target is not None:
            v = eng.target_verdict(result["hires"], args.target)
            verdict = {"target_miss": f"חסרים {v['gap']:,}",
                       "target_over": f"עודף של {v['gap']:,}",
                       "target_ok": "היעד מושג"}[v["kind"]]
            print(f"\n  יעד {v['target']:,} | צפוי {v['projected']:,} | {verdict}")

    elif args.target is not None:
        filled = eng.required_funnel(args.target)
        print(f"כמה מועמדים נדרשים בכל שלב כדי להגיע ל-{args.target:,} מגויסים")
        for k in eng.stage_keys():
            cell = filled.get(k)
            print(f"  {eng.stage(k)['label']:<22} " +
                  ("אין נתונים" if cell is None else f"{cell['value']:,}"))


if __name__ == "__main__":
    main()
