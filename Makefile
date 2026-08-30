.PHONY: all data web test verify basis clean

all: data web

data:          ## בניית מאגר הנתונים מקובצי האקסל שבתיקיית «נתונים למערכת»
	python3 tools/build_dataset.py

web: data      ## בניית index.html ו-«מחשבון גיוס.html»
	python3 tools/build_web.py

test:          ## הרצת כל הבדיקות
	python3 -m unittest discover -s tests -v

verify:        ## דוח בדיקה של קובצי המקור
	python3 tools/verify_sources.py

basis:         ## הצגת יחסי הגיוס וזמני הגיוס בשורת פקודה
	python3 -m recruit_calc.cli --basis

clean:
	rm -f data/recruitment_data.json index.html "מחשבון גיוס.html"
	find . -name __pycache__ -type d -exec rm -rf {} +
