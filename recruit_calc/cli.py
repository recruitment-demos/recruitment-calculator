#!/usr/bin/env python3
"""שורת פקודה למחשבון הגיוס.

דוגמאות:
    python3 -m recruit_calc.cli --basis
    python3 -m recruit_calc.cli --from file_check 5000
    python3 -m recruit_calc.cli --from file_check 5000 --from yachbam 300 --target 400
    python3 -m recruit_calc.cli --target 400
    python3 -m recruit_calc.cli --target 400 --by 2027-01-15
    python3 -m recruit_calc.cli --target 400 --entry file_check
    python3 -m recruit_calc.cli --target 4000 --volume
    python3 -m recruit_calc.cli --target 400 --by 2027-01-15 --manager
    python3 -m recruit_calc.cli --funnel
    python3 -m recruit_calc.cli --segments
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


def fmt_span(days):
    """המחיר בזמן, בלשון קריאה."""
    if days is None:
        return "—"
    if days < 45:
        return f"{round(days):,} ימים"
    if days < 400:
        return f"כ-{days / 30.4:.1f} חודשים".replace(".0 ", " ")
    return f"כ-{days / 365:.1f} שנים".replace(".0 ", " ")


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


def print_funnel(eng):
    """משפך המיון המלא, כפי שנמדד בקבצים."""
    f = eng.data.get("funnel")
    if not f:
        raise SystemExit("אין נתוני משפך במאגר. יש להריץ make.")
    first = f["rows"][0]["label"]
    print("משפך המיון המלא")
    print(f"  «מהקודם» ו«מ{first}» הן שתי מדידות ישירות ונפרדות. "
          f"השנייה אינה מכפלה של הראשונות.\n")
    print(f"  {'שלב':<20}{'מועמדים':>10}{'מהקודם':>10}{'ימים':>7}"
          f"{'מ' + first:>12}{'ימים':>7}")
    for row in f["rows"]:
        prev, ff = row["from_prev"], row["from_first"]
        print(f"  {row['label']:<20}{row['candidates']:>10,}"
              f"{(pct(prev['reach']['mid']) if prev else '—'):>10}"
              f"{(f"{prev['days']['median']:.0f}" if prev else '—'):>7}"
              f"{(pct(ff['reach']['mid']) if ff else '—'):>12}"
              f"{(f"{ff['days']['median']:.0f}" if ff else '—'):>7}")


def print_segments(eng):
    """הפער בין ערוצי הגיוס."""
    segs = [g for g in (eng.data.get("segments") or []) if g["funnel"]]
    if not segs:
        raise SystemExit("אין פילוח ערוצים במאגר. יש להריץ make.")
    base = next((g for g in segs if g["key"] == "all"), None)
    base_rate = base and base["funnel"]["rows"][-1]["from_first"]["reach"]["mid"]
    print("הפער בין ערוצי הגיוס")
    print("  כל מועמד משויך לערוץ אחד לפי «דרישה» שברשומת ההגשה שלו.\n")
    print(f"  {'ערוץ':<38}{'מגישים':>9}{'מגויסים':>9}"
          f"{'מהגשה לגיוס':>13}{'ימים':>7}{'פי':>6}")
    for g in segs:
        rows = g["funnel"]["rows"]
        ff = rows[-1]["from_first"]
        ratio = "" if not (ff and base_rate) else f"{ff['reach']['mid']/base_rate:.2f}"
        print(f"  {g['label']:<38}{rows[0]['candidates']:>9,}"
              f"{rows[-1]['candidates']:>9,}"
              f"{(pct(ff['reach']['mid']) if ff else '—'):>13}"
              f"{(f"{ff['days']['median']:.0f}" if ff else '—'):>7}{ratio:>6}")


def print_volume(eng, target, days):
    """כמה צריך שיעברו בכל שלב, לפי המשפך שנמדד בפועל."""
    plan = eng.throughput_plan(target, days)
    if plan is None:
        raise SystemExit("אין נתוני נפח במאגר. יש להריץ make.")

    print(f"\nכמה צריך שיעברו בכל שלב כדי לגייס {target:,}")
    print(f"  בפועל: {plan['observed_hires']:,} גיוסים ב-"
          f"{plan['observed_days']:,} ימים ({plan['observed_from']} עד "
          f"{plan['observed_to']}).")
    print(f"  כדי לגייס {target:,} צריך שכל המשפך ירוץ פי {plan['factor']:.2f}.\n")

    head = f"  {'שלב':<20}{'צריך שיעברו':>13}{'נמדד':>10}"
    if days:
        head += f"{'ליום':>8}{'פי כמה':>8}"
    head += f"{'עברו כאן':>10}"
    print(head)

    for r in plan["rows"]:
        if not r["has_data"]:
            print(f"  {r['label']:<20}{'—':>13}   {r['note']}")
            continue
        line = f"  {r['label']:<20}{r['required']:>13,}{r['observed']:>10,}"
        if days:
            line += f"{round(r['per_day']):>8,}{'×' + format(r['pace'], '.2f'):>8}"
        line += f"{pct(r['coverage']):>10}"
        if r["selective"]:
            line += "   [סלקטיבי - רוב המגויסים אינם עוברים כאן]"
        print(line)

    print("\n  הכמויות פרופורציוניות ליעד ואינן תלויות בתאריך - התאריך "
          "קובע רק את הקצב.\n  הן נגזרות מנפחי המשפך של הארגון כולו, ולכן "
          "כוללות גם מי שאינו עובר\n  דרך ההגשות.")


def print_constrained(eng, target, days):
    """המחשבון עם האילוצים: המשפך של תזרים 2025, בשני נתיבים.

    זו התשובה הראשית. היא שונה מ-print_volume בכך שהיא אינה מניחה
    שכל הגיוסים גדלים יחד: הנתיב המוכר קבוע ואינו נגזר מההגשות.
    """
    plan = eng.constrained_plan(target, days)
    if plan is None:
        raise SystemExit("אין תזרים שנתי במאגר, או שחלון הזמן אינו חוקי. "
                         "יש להריץ make.")

    span = ("שנה שלמה (365 יום)" if plan["annual"]
            else f"-{plan['span_days']:,} ימים")
    print(f"\nכמה צריך כדי לגייס {target:,} ב{span}")
    print(f"  מקור היחסים: תזרים הליך הגיוס {plan['year']} "
          f"({plan['baseline_submissions']:,} הגשות, "
          f"{plan['baseline_hires']:,} גיוסים).\n")

    print(f"  {plan['known']['label']:<20}{plan['known']['hires']:>9,}   "
          f"יחס 1:{plan['known']['ratio']}, קבוע - אינו עובר מיון ואינו גדל")
    print(f"  {plan['new']['label']:<20}{plan['new']['hires']:>9,}   "
          f"יחס 1:{round(plan['new']['ratio'])}, הנתיב היחיד שנגזר מההגשות\n")

    print(f"  {'שלב':<20}{'סך הכול':>10}{'חדשה':>10}{'מוכרת':>9}"
          f"{plan['year']:>10}{'פי כמה':>9}")
    aside_after = {}
    for a in plan["aside"]:
        aside_after.setdefault(a["after"], []).append(a)

    for r in plan["rows"]:
        print(f"  {r['label']:<20}{r['total']:>10,}{r['new']:>10,}"
              f"{r['known']:>9,}{r['baseline']:>10,}"
              f"{'×' + format(r['pace'], '.2f'):>9}")
        for a in aside_after.get(r["key"], []):
            print(f"    ↳ {a['label']:<17}{a['total']:>10,}{'—':>10}{'—':>9}"
                  f"{a['baseline']:>10,}{'×' + format(a['pace'], '.2f'):>9}"
                  f"   [תחנת צד, לא בשרשרת]")

    if plan["shortfall"]:
        print(f"\n  היעד קטן מהנתיב המוכר ({plan['known']['per_year']:,} "
              f"בשנה), ולכן אינו דורש אף הגשה חדשה.")
    else:
        print(f"\n  {plan['submissions']:,} הגשות לעומת "
              f"{plan['baseline_in_span']:,} בקצב של {plan['year']} "
              f"באותו אורך זמן - פי {plan['growth']:.2f},\n  בעוד "
              f"שהגיוסים גדלים פי {plan['target_growth']:.2f} בלבד. "
              f"ההפרש נובע מכך שהנתיב המוכר אינו גדל,\n  וכל התוספת "
              f"נופלת על הנתיב היחיד שכן גדל.")


def print_manager(eng, target, by, days, counts=None):
    """הלוח של מנהלת הגיוס: כמה צריך בכל שלב, ועד מתי."""
    plan = eng.manager_plan(counts or {}, target, days)
    today = datetime.date.today()

    print(f"\nהלוח של מנהלת הגיוס: כמה צריך בכל שלב כדי לגייס {target:,}" +
          (f" עד {fmt_day(by)} (בעוד {days:,} ימים)" if days is not None else ""))
    if plan["have"]:
        print(f"  מי שכבר בתהליך מנוכה: {plan['have']:,} מהיעד מכוסים, "
              f"והפער הוא {plan['gap']:,}.")
    print("  «צריך שיעמדו שם» היא הכמות בלי לחץ זמן, והמחיר שלה הוא התאריך.")
    print("  «אם הם שם היום» היא הכמות ממי שכבר עומד בשלב עכשיו.\n")
    print(f"  {'שלב':<20}{'צריך שיעמדו שם':>16}{'עד מתי':>16}{'אם הם שם היום':>16}")

    for row in plan["rows"]:
        if not row["has_data"]:
            print(f"  {row['label']:<20}{'—':>16}{'—':>16}{'—':>16}   {row['note']}")
            continue
        by_txt = f"{row['required_by']:,}"
        if days is None:
            when = f"בעוד {row['lead_days_median']:.0f} ימים"
        elif row["late"]:
            when = "החלון נסגר"
        else:
            when = fmt_day(today + datetime.timedelta(
                days=round(row["deadline_days"])))
        now_txt = ("—" if row["required_now"] is None
                   else "לא בזמן הזה" if not row["feasible"]
                   else f"{row['required_now']:,}")
        pace = ("" if row["required_by_pace_days"] is None else
                f"   ({fmt_span(row['required_by_pace_days'])} של הקצב הנמדד)")
        print(f"  {row['label']:<20}{by_txt:>16}{when:>16}{now_txt:>16}{pace}")

    print("\n  התאריכים אינם בסדר השלבים: הזמן עד הגיוס נמדד בכל שלב על "
          "קבוצה אחרת,\n  רק על מי שהתגייס בפועל.")


def main():
    p = argparse.ArgumentParser(description="מחשבון גיוס")
    p.add_argument("--basis", action="store_true", help="הצגת בסיס הנתונים")
    p.add_argument("--funnel", action="store_true",
                   help="משפך המיון המלא, כפי שנמדד בקבצים")
    p.add_argument("--segments", action="store_true",
                   help="הפער בין ערוצי הגיוס")
    p.add_argument("--constrained", action="store_true",
                   help="המחשבון עם האילוצים: המשפך של תזרים 2025 בשני נתיבים")
    p.add_argument("--volume", action="store_true",
                   help="כמה צריך שיעברו בכל שלב, לפי המשפך שנמדד בפועל")
    p.add_argument("--manager", action="store_true",
                   help="הלוח של מנהלת הגיוס: כמה צריך בכל שלב, ועד מתי")
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

    if args.funnel:
        print_funnel(eng)
        if not (args.cohorts or args.target or args.segments):
            return
        print()

    if args.segments:
        print_segments(eng)
        if not (args.cohorts or args.target):
            return
        print()

    if args.basis or not (args.cohorts or args.target or args.funnel
                          or args.segments):
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

            if args.manager:
                left = None if by is None else (by - datetime.date.today()).days
                print_manager(eng, args.target, by,
                              left if left is not None and left >= 0 else None,
                              counts)

    elif args.target is not None:
        days = None
        if by is not None:
            left = (by - datetime.date.today()).days
            if left < 0:
                raise SystemExit(f"התאריך {fmt_day(by)} כבר עבר.")
            days = left

        if args.constrained:
            print_constrained(eng, args.target, days)
            return

        if args.volume:
            print_volume(eng, args.target, days)
            return

        if args.manager:
            print_constrained(eng, args.target, days)
            print_volume(eng, args.target, days)
            print_manager(eng, args.target, by, days)
            return

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
            flag = ("" if row.get("pace_days") is None else
                    f"   [{fmt_span(row['pace_days'])} של הקצב הנמדד]")
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
