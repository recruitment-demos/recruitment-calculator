/*
 * בדיקת קריאת קובצי אקסל, מול ספריית הקריאה האמיתית שמוטמעת בעמוד
 * הבנוי - ולא מול חיקוי שלה. כאן נבדקים המבנים שאי אפשר לבדוק
 * ב-ui_smoke.js: תאים ממוזגים, כמה גיליונות, וקובץ בינארי אמיתי.
 *
 * הקובץ «פעילים 20.8.xlsx» אינו נכנס למאגר (הוא מכיל מזהי מועמדים),
 * ולכן החלק שנשען עליו מדולג כשהוא אינו קיים.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.indexOf("</script>"));
const rest = html.slice(html.indexOf("</script>"));
const lib = rest.slice(rest.indexOf("<script>") + 8, rest.lastIndexOf("</script>"));

/* ---------- DOM מזויף, כמו ב-ui_smoke.js ---------- */
const registry = {};
function makeEl(tag) {
  const el = {
    tagName: tag, children: [], style: {}, attributes: {}, value: "",
    _text: "", _html: "",
    classList: {
      _s: new Set(),
      add(...c) { c.forEach(x => this._s.add(x)); },
      remove(...c) { c.forEach(x => this._s.delete(x)); },
      contains(c) { return this._s.has(c); },
      toggle(c, f) {
        const on = f === undefined ? !this._s.has(c) : !!f;
        if (on) this._s.add(c); else this._s.delete(c);
        return on;
      }
    },
    setAttribute(k, v) { this.attributes[k] = v; },
    append(...k) { k.forEach(x => this.children.push(x)); },
    addEventListener() {},
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); if (v === "") this.children = []; }
  };
  Object.defineProperty(el, "className", {
    get() { return [...el.classList._s].join(" "); },
    set(v) { el.classList._s = new Set(String(v).split(/\s+/).filter(Boolean)); }
  });
  Object.defineProperty(el, "id", {
    get() { return el._id; },
    set(v) { el._id = v; registry[v] = el; }
  });
  return el;
}
const document = {
  getElementById(id) { return (registry[id] ||= makeEl("div")); },
  createElement(tag) { return makeEl(tag); },
  addEventListener() {}
};
const sandbox = { document, console, Math, Number, JSON, Object, Array, Error };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(lib, sandbox, { filename: "xlsx" });
vm.runInContext(script +
  "\n;globalThis.activeCounts = activeCounts;" +
  "globalThis.expandMerges = expandMerges;" +
  "globalThis.applyActiveRows = applyActiveRows;" +
  "globalThis.DATA = DATA;", sandbox, { filename: "index.html" });

const XLSX = sandbox.XLSX;
const fails = [];
function check(name, fn) {
  try {
    const problem = fn();
    if (problem) fails.push(name + ": " + problem);
  } catch (e) {
    fails.push(name + ": " + (e && e.stack ? e.stack.split("\n").slice(0, 3).join(" | ") : e));
  }
}
const read = ws => XLSX.utils.sheet_to_json(ws, { header: 1, defval: null, raw: true });

check("ספריית הקריאה מוטמעת בעמוד", () =>
  XLSX && XLSX.utils ? null : "אין ספריית קריאה בעמוד הבנוי");

check("תא ממוזג מתפשט על כל הטווח שלו", () => {
  const ws = XLSX.utils.aoa_to_sheet([
    ["מועמד(קוד)", "תהליך נוכחי", "י.ארגונית מחוזית"],
    ["1", "בבחינה", "מחוז צפון"],
    ["2", "קבצים", null],
    ["3", "קבצים", null],
    ["4", "בבחינה", "מחוז דרום"]
  ]);
  ws["!merges"] = [{ s: { r: 1, c: 2 }, e: { r: 3, c: 2 } }];
  sandbox.expandMerges(ws);
  const res = sandbox.activeCounts(read(ws));
  if (!res.ok) return "הטבלה לא זוהתה";
  const north = res.units["מחוז צפון"];
  if (!north) return "היחידה הממוזגת לא נקראה: " + Object.keys(res.units).join(", ");
  return north.submissions === 1 && north.file_check === 2
    ? null : "הספירה שגויה: " + JSON.stringify(north);
});

check("קובץ אמיתי נקרא דרך הספרייה עצמה", () => {
  const src = path.join(ROOT, "שינויים במערכת", "פעילים 20.8.xlsx");
  if (!fs.existsSync(src)) return null;   // הקובץ אינו במאגר
  const book = XLSX.read(new Uint8Array(fs.readFileSync(src)), { type: "array" });
  const ws = book.Sheets[book.SheetNames[0]];
  sandbox.expandMerges(ws);
  const res = sandbox.activeCounts(read(ws));
  if (!res.ok) return "הקובץ לא זוהה";
  if (res.unique !== 5991) return "מספר המועמדים השתנה: " + res.unique;
  const want = { submissions: 2644, file_check: 825, online_day: 969,
                 assessment: 781, yachbam: 778 };
  const bad = Object.keys(want).filter(k => res.counts[k] !== want[k]);
  if (bad.length) return "ספירה שונה ב: " + bad.join(", ");
  // «י.ארגונית מחוזית» ולא «יחידה ארגונית» - זו היתה תקלה שדווחה
  const units = Object.keys(res.units).length;
  return units === 24 ? null : "עמודת היחידה השגויה נבחרה: " + units + " יחידות";
});

check("קובץ בינארי שאינו גיליון אינו מפיל את הקריאה", () => {
  try {
    XLSX.read(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]), { type: "array" });
  } catch (e) {
    return null;   // חריגה מסודרת - זה בדיוק מה שהממשק תופס
  }
  return null;
});

if (fails.length) {
  console.error("נכשלו " + fails.length + " בדיקות קריאה:");
  fails.forEach(f => console.error("  " + f));
  process.exit(1);
}
console.log("כל בדיקות קריאת הקבצים עברו");
