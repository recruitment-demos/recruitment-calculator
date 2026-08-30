#!/usr/bin/env python3
"""שורת פקודה למחשבון הגיוס.

דוגמאות:
    python3 -m recruit_calc.cli --basis          # טבלת הנתונים שמאחורי המחשבון
    python3 -m recruit_calc.cli --from online_day 100
    python3 -m recruit_calc.cli --from file_check 5000 --target 400
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
    print(f"{'שלב':<22}{'יחס גיוס':>18}{'חציון ימים':>12}{'קוהורט בשל':>14}")
    for s in eng.stages:
        if not s["has_data"]:
            print(f"{s['label']:<22}{'אין נתונים במקור':>18}")
            continue
        r, d, b = s["hire_rate"], s["days_to_hire"], s["basis"]["mature"]
        print(f"{s['label']:<22}{pct(r['low']) + '-' + pct(r['high']):>18}"
              f"{d['median']:>12.0f}{b['candidates']:>14,}")


def print_range(label, rng, suffix=""):
    if rng is None:
        print(f"  {label:<22} אין נתונים")
        return
    lo, hi = rng["low"], rng["high"]
    if lo == hi:
        print(f"  {label:<22} {lo:,}{suffix}")
    else:
        print(f"  {label:<22} {lo:,} - {hi:,}{suffix}")


def main():
    p = argparse.ArgumentParser(description="מחשבון פערי גיוס")
    p.add_argument("--basis", action="store_true", help="הצגת בסיס הנתונים")
    p.add_argument("--from", dest="from_stage", nargs=2, metavar=("STAGE", "COUNT"),
                   help="השלמת המשפך משלב ומספר מועמדים")
    p.add_argument("--target", type=int, help="יעד גיוס להשוואה")
    p.add_argument("--timeline", action="store_true", help="הצגת פריסת מועדי הגיוס")
    args = p.parse_args()

    eng = load_engine()

    if args.basis or not (args.from_stage or args.target):
        print_basis(eng)
        if not args.from_stage:
            return
        print()

    if args.from_stage:
        key, raw = args.from_stage
        count = int(raw)
        filled = eng.fill_from(key, count)
        print(f"השלמת משפך מתוך {count:,} מועמדים בשלב «{eng.stage(key)['label']}»")
        for k in eng.stage_keys():
            print_range(eng.stage(k)["label"], filled.get(k))
        print_range("מגויסים צפויים", filled["hires"])

        if args.timeline:
            print("\nפריסת מועדי הגיוס הצפויים")
            for row in eng.timeline(key, count) or []:
                if row["hires"] is None:
                    continue
                lo, hi = row["hires"].rounded()
                print(f"  {row['label']:<22} {lo:,} - {hi:,}   ({pct(row['share'])})")

        if args.target is not None:
            print()
            for msg in eng.gap_analysis({key: count}, args.target):
                if msg["kind"].startswith("target"):
                    pr = msg["projected"]
                    verdict = {"target_miss": "מתחת ליעד",
                               "target_over": "מעל היעד",
                               "target_ok": "היעד בתוך הטווח"}[msg["kind"]]
                    print(f"  יעד {msg['target']:,} | צפוי {pr['low']:,}-{pr['high']:,} | {verdict}")


if __name__ == "__main__":
    main()
