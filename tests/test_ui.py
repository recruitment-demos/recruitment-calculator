"""מריץ את בדיקת הממשק (tests/ui_smoke.js) כחלק מ-make test.

הבדיקה מפעילה את קוד הממשק של index.html מול DOM מזויף ומוודאת
שהמסלולים המרכזיים רצים ומייצרים תוכן.
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
class TestUiSmoke(unittest.TestCase):
    def test_ui_runs_without_errors(self):
        proc = subprocess.run(
            ["node", str(ROOT / "tests" / "ui_smoke.js")],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0,
                         "בדיקת הממשק נכשלה:\n" + proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
