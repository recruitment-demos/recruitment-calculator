"""מריץ את בדיקת קריאת הקבצים (tests/import_check.js) כחלק מ-make test.

הבדיקה מפעילה את קוד הקריאה של index.html מול ספריית האקסל שמוטמעת
בעמוד עצמו, ולכן היא תופסת גם תקלות שמקורן בספרייה ולא בקוד שלנו.
"""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def node_available():
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@unittest.skipUnless(node_available(), "node אינו מותקן")
class TestImportCheck(unittest.TestCase):
    def test_import_reads_every_shape(self):
        proc = subprocess.run(
            ["node", str(ROOT / "tests" / "import_check.js")],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0,
                         "בדיקת קריאת הקבצים נכשלה:\n" + proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
