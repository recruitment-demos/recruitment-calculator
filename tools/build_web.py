#!/usr/bin/env python3
"""בניית עמודי המחשבון מתוך web/template.html ו-data/recruitment_data.json.

נוצרים שני קבצים זהים בתוכן:
  index.html          - הגרסה שמוגשת ב-GitHub Pages משורש המאגר.
  מחשבון גיוס.html    - קובץ עצמאי לשליחה או לפתיחה בלחיצה כפולה.

שניהם עצמאיים לחלוטין: הנתונים מוטמעים בתוך ה-HTML ואין קריאות רשת.
גם ספריית קריאת האקסל (web/vendor/xlsx.mini.min.js), שמשמשת את טעינת
קובץ המועמדים הפעילים בדפדפן, מוטמעת בתוכם. הקבצים האלה הם תוצר בנייה -
אין לערוך אותם ידנית.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "web" / "template.html"
DATA = ROOT / "data" / "recruitment_data.json"
SHEETJS = ROOT / "web" / "vendor" / "xlsx.mini.min.js"
OUTPUTS = [ROOT / "index.html", ROOT / "מחשבון גיוס.html"]

MARKER = "/*__DATA__*/"
SHEETJS_MARKER = "/*__SHEETJS__*/"


def render():
    """התבנית עם הנתונים מוזרקים. משמש גם את tests/test_parity.py."""
    template = TEMPLATE.read_text(encoding="utf-8")
    dataset = json.loads(DATA.read_text(encoding="utf-8"))

    start = template.find(MARKER)
    end = template.find(MARKER, start + len(MARKER))
    if start == -1 or end == -1:
        sys.exit(f"לא נמצא סימן ההזרקה {MARKER} בתבנית.")

    payload = json.dumps(dataset, ensure_ascii=False, separators=(",", ":"))
    # </script> בתוך מחרוזת JSON היה סוגר את תגית הסקריפט בטרם עת.
    payload = payload.replace("</", "<\\/")

    html = template[:start] + payload + template[end + len(MARKER):]

    # ספריית קריאת האקסל מוטמעת ולא נטענת מרשת, כדי שהקובץ העצמאי
    # יעבוד גם בלי חיבור. הסימן יושב אחרי הסקריפט הראשי בכוונה:
    # בדיקת הממשק חותכת את הסקריפט הראשון שבעמוד.
    if SHEETJS_MARKER not in html:
        sys.exit(f"לא נמצא סימן ההזרקה {SHEETJS_MARKER} בתבנית.")
    if not SHEETJS.exists():
        sys.exit("ספריית קריאת האקסל חסרה: web/vendor/xlsx.mini.min.js")
    html = html.replace(SHEETJS_MARKER,
                        SHEETJS.read_text(encoding="utf-8"), 1)

    banner = ("<!-- קובץ זה נוצר אוטומטית על ידי tools/build_web.py. "
              "אין לערוך אותו ידנית - יש לערוך את web/template.html ולהריץ make. -->\n")
    return banner + html


def main():
    if not DATA.exists():
        sys.exit("מאגר הנתונים חסר. יש להריץ קודם: make data")

    html = render()
    for out in OUTPUTS:
        out.write_text(html, encoding="utf-8")
        print(f"נכתב {out.name} ({len(html):,} תווים)")


if __name__ == "__main__":
    main()
