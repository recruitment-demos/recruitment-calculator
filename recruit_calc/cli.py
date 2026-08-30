#!/usr/bin/env python3
"""שורת פקודה למחשבון הגיוס.

דוגמאות:
    python3 -m recruit_calc.cli --basis          # טבלת הנתונים שמאחורי המחשבון
    python3 -m recruit_calc.cli --from online_day 100
    python3 -m recruit_calc.cli --from file_check 5000 --target 400
    python3 -m recruit_calc.cli --target 400     # חישוב לאחור מיעד
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
    print()
    print(f"{'שלב':<22}{'יחס גיוס':>10}{'חציון ימים':>12}{'קוהורט בשל':>14}")
    for s in eng.stages:
        if not s["has_data"]:
            print(f"{s['label']:<22}{'אין נתונים':>10}")
            continue
        d, b = s["days_to_hire"], s["basis"]["mature"]
        print(f"{s['label']:<22}{pct(eng.rate(s['key'])):>10}"
              f"{d['median']:>12.0f}{b['candidates']:>14,}")


def print_row(label, cell):
    if cell is None:
        print(f"  {label:<22} אין נתונים")
    else:
        print(f"  {label:<22} {cell['value']:,}")


def main():
    p = argparse.ArgumentParser(description="מחשבון פערי גיוס")
    p.add_argument("--basis", action="store_true", help="הצגת בסיס הנתונים")
    p.add_argument("--from", dest="from_stage", nargs=2, metavar=("STAGE", "COUNT"),
                   help="השלמת המשפך משלב ומספר מועמדים")
    p.add_argument("--target", type=int, help="יעד גיוס")
    p.add_argument("--timeline", action="store_true", help="הצגת פריסת מועדי הגיוס")
    args = p.parse_args()

    eng = load_engine()

    if args.basis or not (args.from_stage or args.target):
        print_basis(eng)
        if not (args.from_stage or args.target):
            return
        print()

    if args.from_stage:
        key, raw = args.from_stage
        count = int(raw)
        filled = eng.fill_from(key, count)
        print(f"השלמת משפך מתוך {count:,} מועמדים בשלב «{eng.stage(key)['label']}»")
        for k in eng.stage_keys():
            print_row(eng.stage(k)["label"], filled.get(k))
        print(f"  {'מגויסים צפויים':<22} {filled['hires']:,}")

        if args.timeline:
            print("\nפריסת מועדי הגיוס הצפויים")
            for row in eng.timeline(key, count) or []:
                if row["hires"] is None:
                    continue
                print(f"  {row['label']:<22} {row['hires']:,}   ({pct(row['share'])})")

        if args.target is not None:
            print()
            for msg in eng.gap_analysis({key: count}, args.target):
                if msg["kind"].startswith("target"):
                    verdict = {"target_miss": f"חסרים {msg['gap']:,}",
                               "target_over": f"עודף של {msg['gap']:,}",
                               "target_ok": "היעד מושג"}[msg["kind"]]
                    print(f"  יעד {msg['target']:,} | צפוי {msg['projected']:,} | {verdict}")

    elif args.target is not None:
        filled = eng.required_funnel(args.target)
        print(f"כמה מועמדים נדרשים בכל שלב כדי להגיע ל-{args.target:,} מגויסים")
        for k in eng.stage_keys():
            print_row(eng.stage(k)["label"], filled.get(k))


if __name__ == "__main__":
    main()
