.PHONY: all data web excel test verify basis plan constrained clean

all: data web excel

data:          ## בניית מאגר הנתונים מקובצי האקסל שבתיקיית «נתונים למערכת»
	python3 tools/build_dataset.py

web: data      ## בניית index.html ו-«מחשבון גיוס.html»
	python3 tools/build_web.py

excel: data    ## משפך המיון המלא והפער בין ערוצי הגיוס, כקובצי אקסל
	python3 tools/export_funnel.py
	python3 tools/analyze_durations.py

test:          ## הרצת כל הבדיקות
	python3 -m unittest discover -s tests -v

verify:        ## דוח בדיקה של קובצי המקור
	python3 tools/verify_sources.py

basis:         ## הצגת יחסי הגיוס וזמני הגיוס בשורת פקודה
	python3 -m recruit_calc.cli --basis

constrained:   ## המחשבון עם האילוצים. שימוש: make constrained T=4000
	python3 -m recruit_calc.cli --target $(T) $(if $(BY),--by $(BY),) --constrained

plan:          ## הלוח של מנהלת הגיוס. שימוש: make plan T=400 BY=2026-12-31
	python3 -m recruit_calc.cli --target $(T) $(if $(BY),--by $(BY),) --manager

clean:
	rm -f data/recruitment_data.json index.html "מחשבון גיוס.html"
	rm -f "קבצים/התקבל/משפך מיון מלא.xlsx" "קבצים/התקבל/פער בין ערוצי גיוס.xlsx"
	find . -name __pycache__ -type d -exec rm -rf {} +
