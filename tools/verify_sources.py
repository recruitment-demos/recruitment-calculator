#!/usr/bin/env python3
"""דוח בדיקה של קבצי המקור.

לא משנה נתונים ולא מתקן כלום - רק מדווח על מה שקיים בקבצים ועל מה שחסר
בהם, כדי שכל פער יהיה גלוי לפני שמסתמכים על המספרים.
"""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def load():
    with (ROOT / "config" / "params.json").open(encoding="utf-8") as fh:
        cfg = json.load(fh)
    a_cfg, h_cfg = cfg["sources"]["activities"], cfg["sources"]["hires"]
    act = pd.read_excel(ROOT / a_cfg["file"], sheet_name=a_cfg["sheet"])
    rec = pd.read_excel(ROOT / h_cfg["file"], sheet_name=h_cfg["sheet"])
    ac, hc = a_cfg["columns"], h_cfg["columns"]
    act = act.rename(columns={ac["candidate"]: "candidate", ac["activity_type"]: "activity",
                              ac["date"]: "date", ac["district"]: "district"})
    rec = rec.rename(columns={hc["candidate"]: "candidate", hc["date"]: "date",
                              hc["unit"]: "unit"})
    act["date"] = pd.to_datetime(act["date"])
    rec["date"] = pd.to_datetime(rec["date"], dayfirst=h_cfg.get("date_dayfirst", True))
    return cfg, act, rec


def section(title):
    print("\n" + title)
    print("-" * len(title))


def main():
    cfg, act, rec = load()
    hire_date = rec.groupby("candidate")["date"].min()
    hired = set(hire_date.index)
    act_ids = set(act["candidate"])

    section("היקף")
    print(f"פעילויות: {len(act):,} שורות, {len(act_ids):,} מועמדים ייחודיים, "
          f"{act['date'].min().date()} עד {act['date'].max().date()}")
    print(f"גיוסים:   {len(rec):,} שורות, {len(hired):,} מועמדים ייחודיים, "
          f"{rec['date'].min().date()} עד {rec['date'].max().date()}")

    section("חיבור בין הקבצים")
    no_act = hired - act_ids
    print(f"מגויסים ללא שום פעילות רשומה: {len(no_act):,} מתוך {len(hired):,} "
          f"({len(no_act)/len(hired)*100:.1f}%)")
    print("  משמעות: אלה מועמדים שהתהליך שלהם אינו מתועד בקובץ הפעילויות,")
    print("  ולכן יחסי ההמרה שמחושבים כאן לא מכסים אותם.")

    dupes = len(rec) - len(hired)
    print(f"שורות גיוס כפולות לאותו מועמד: {dupes}")

    section("שלמות שדות")
    for col in ("activity", "date", "district"):
        missing = act[col].isna().sum()
        print(f"פעילויות, {col}: {missing:,} ריקים ({missing/len(act)*100:.1f}%)")
    for col in ("unit", "date"):
        missing = rec[col].isna().sum()
        print(f"גיוסים, {col}: {missing:,} ריקים ({missing/len(rec)*100:.1f}%)")

    section("סוגי פעילות")
    mapped = {s["activity_type"] for s in cfg["stages"] if s["activity_type"]}
    counts = act["activity"].value_counts(dropna=False)
    for name, n in counts.items():
        mark = "ממופה" if name in mapped else "לא ממופה"
        print(f"  {str(name):<26} {n:>7,}  {mark}")
    missing_types = mapped - set(counts.index)
    if missing_types:
        print(f"  מוגדרים ב-config ואינם בקובץ: {', '.join(sorted(missing_types))}")

    section("שלבים ללא מקור נתונים")
    for s in cfg["stages"]:
        if s["activity_type"] is None:
            print(f"  {s['label']}: {s.get('note', 'אין מקור')}")

    section("עדות לקטיעה מימין - יחס גיוס לפי חודש הפעילות")
    print("ירידה חדה בחודשים המאוחרים אינה ירידה באיכות, אלא חוסר זמן מעקב.")
    months = sorted(act["date"].dt.to_period("M").unique())
    header = "שלב".ljust(26) + "".join(str(m).ljust(11) for m in months)
    print(header)
    for s in cfg["stages"]:
        if not s["activity_type"]:
            continue
        first = act[act["activity"] == s["activity_type"]].groupby("candidate")["date"].min()
        row = s["label"].ljust(26)
        for m in months:
            c = first[first.dt.to_period("M") == m]
            if len(c) == 0:
                row += "-".ljust(11)
                continue
            h = len(set(c.index) & hired)
            row += f"{h/len(c)*100:.0f}%".ljust(11)
        print(row)

    section("פעילויות אחרי מועד הגיוס")
    j = act.join(hire_date.rename("hire"), on="candidate")
    after = j[j["hire"].notna() & (j["date"] > j["hire"])]
    print(f"{len(after):,} שורות פעילות מתועדות אחרי מועד הגיוס של המועמד "
          f"({len(after)/len(act)*100:.1f}%).")
    print("  שורות אלה אינן נספרות בחישוב זמני הגיוס.")

    section("כיסוי יחידה מחוזית")
    cov = act["district"].notna().mean()
    print(f"לשורות פעילות יש שיוך מחוזי ב-{cov*100:.1f}% מהמקרים.")
    print("  הכיסוי החלקי הוא הסיבה לכך שהמחשבון אינו מציג פילוח מחוזי:")
    print("  פילוח על בסיס כזה היה מציג הבדלים בין מחוזות שנובעים מאיכות")
    print("  הרישום ולא מהגיוס עצמו.")


if __name__ == "__main__":
    main()
