/*
 * מריץ את קוד הממשק של העמוד הבנוי מול DOM מזויף מינימלי, כדי לוודא
 * שהמסלולים המרכזיים רצים בלי שגיאת ריצה ושהם באמת מייצרים תוכן.
 *
 * זו אינה בדיקה ויזואלית - היא בודקת שהלוגיקה של הממשק לא נשברת.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.indexOf("</script>"));

/* ---------- DOM מזויף ---------- */
function makeEl(tag) {
  const el = {
    tagName: tag,
    children: [],
    style: {},
    attributes: {},
    _text: "",
    _html: "",
    classList: {
      _s: new Set(),
      add(...c) { c.forEach(x => this._s.add(x)); },
      remove(...c) { c.forEach(x => this._s.delete(x)); },
      contains(c) { return this._s.has(c); }
    },
    setAttribute(k, v) { this.attributes[k] = v; },
    append(...kids) { kids.forEach(k => this.children.push(k)); },
    addEventListener(type, fn) { (this._on ||= {})[type] = fn; },
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); if (v === "") this.children = []; }
  };
  Object.defineProperty(el, "className", {
    get() { return [...el.classList._s].join(" "); },
    set(v) { el.classList._s = new Set(String(v).split(/\s+/).filter(Boolean)); }
  });
  // אלמנט שמקבל id נרשם, כדי ש-getElementById ימצא גם אלמנטים שנוצרו בקוד
  Object.defineProperty(el, "id", {
    get() { return el._id; },
    set(v) { el._id = v; registry[v] = el; }
  });
  return el;
}

const registry = {};
const document = {
  getElementById(id) { return (registry[id] ||= makeEl("div")); },
  createElement(tag) { return makeEl(tag); },
  addEventListener() {}
};

const sandbox = { document, console, Math, Number, JSON, Object, Array, Error };
sandbox.window = sandbox;
vm.createContext(sandbox);

// הצהרות const בראש הסקריפט אינן הופכות למשתני גלובל בהקשר של vm,
// ולכן נחשפות במפורש בסוף כדי שהבדיקה תוכל להפעיל אותן.
const exposed = script + "\n;globalThis.DATA = DATA; globalThis.Engine = Engine;" +
                "globalThis.calculate = calculate; globalThis.reset = reset;";
vm.runInContext(exposed, sandbox, { filename: "index.html" });

/* ---------- תרחישים ---------- */
const fails = [];
function check(name, fn) {
  try {
    const problem = fn();
    if (problem) fails.push(name + ": " + problem);
  } catch (e) {
    fails.push(name + ": " + (e && e.stack ? e.stack.split("\n")[0] : e));
  }
}

const stageKeys = sandbox.DATA.stages.map(s => s.key);
const withData = sandbox.DATA.stages.filter(s => s.has_data).map(s => s.key);
const setVal = (id, v) => { registry["in_" + id].value = v; };
const clearAll = () => { stageKeys.forEach(k => setVal(k, "")); setVal("target", ""); };
const shown = id => !registry[id].classList.contains("hidden");
const revealed = id => registry[id].classList.contains("in");
const num = s => Number(String(s).replace(/[^0-9]/g, ""));

check("שדות הקלט נבנו", () =>
  stageKeys.every(k => registry["in_" + k]) && registry.in_target
    ? null : "חסר שדה קלט");

check("חותמת הנתונים הוצגה", () =>
  registry.stamp.textContent.length > 40 ? null : "חותמת ריקה");

check("פאנל בסיס הנתונים הוצג", () =>
  registry.basisBody.innerHTML.includes("<table") ? null : "אין טבלת בסיס");

check("טבלת הבסיס מציגה יחס יחיד ולא טווח", () =>
  registry.basisBody.innerHTML.includes("<strong>") ? null : "אין יחס מודגש");

check("רשימת המגבלות הוצגה", () =>
  (registry.limitsBody.innerHTML.match(/<li>/g) || []).length >= 6
    ? null : "פחות מדי מגבלות");

check("בלי קלט התוצאות נשארות מוסתרות", () => {
  clearAll();
  sandbox.calculate();
  return shown("results") ? "התוצאות הוצגו בלי קלט" : null;
});

for (const key of withData) {
  check("חישוב קדימה משלב " + key, () => {
    clearAll();
    setVal(key, "500");
    sandbox.calculate();
    if (!shown("results")) return "אזור התוצאות מוסתר";
    if (!revealed("heroCard")) return "כרטיס התוצאה לא הופיע";
    if (!revealed("funnelCard")) return "המשפך לא הופיע";
    if (!revealed("timelineCard")) return "ציר הזמן לא הופיע";
    if (registry.funnelBody.children.length !== stageKeys.length + 1)
      return "מספר שורות משפך שגוי";
    if (registry.timelineBody.children.length !== sandbox.DATA.time_buckets.length)
      return "מספר דליי זמן שגוי";
    if (!registry.heroCap.textContent.includes("מגויסים")) return "כותרת שגויה";
    if (!registry.heroNote.textContent.includes("500")) return "אין הסבר לתוצאה";
    const hero = num(registry.heroValue.textContent);
    if (!(hero > 0)) return "מספר המגויסים אינו חיובי";
    if (!registry.timelineSub.textContent.includes("חציון")) return "אין תיאור לציר הזמן";
    return null;
  });
}

check("מספר המגויסים תואם את המנוע", () => {
  clearAll();
  setVal("online_day", "1000");
  sandbox.calculate();
  const expected = sandbox.Engine.fillFrom("online_day", 1000).hires;
  const shownVal = num(registry.heroValue.textContent);
  return shownVal === expected ? null : "הוצג " + shownVal + " במקום " + expected;
});

check("אין טווחים בתצוגה", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("target", "300");
  sandbox.calculate();
  const texts = [registry.heroValue.textContent]
    .concat(registry.funnelBody.children.map(r =>
      r.children.map(c => c.textContent).join(" ")))
    .concat(registry.gapBody.children.map(c => c.textContent))
    .concat(registry.timelineBody.children.map(r =>
      r.children.map(c => c.textContent).join(" ")));
  const bad = texts.find(t => /\d\s*[-–]\s*\d/.test(t));
  return bad ? "נמצא טווח בתצוגה: " + bad : null;
});

check("חישוב לאחור מיעד בלבד", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  if (!shown("results")) return "אזור התוצאות מוסתר";
  if (num(registry.heroValue.textContent) !== 400) return "היעד לא הוצג";
  if (!registry.heroCap.textContent.includes("יעד")) return "כותרת שגויה";
  if (!registry.timelineCard.classList.contains("hidden"))
    return "ציר הזמן היה צריך להיות מוסתר";
  return registry.gapBody.children.length > 0 ? null : "אין הודעת הסבר";
});

check("שני שלבים מייצרים ניתוח פערים", () => {
  clearAll();
  setVal("file_check", "100");
  setVal("yachbam", "400");
  sandbox.calculate();
  return registry.gapBody.children.some(c => c.classList.contains("bad"))
    ? null : "לא הוצג חוסר";
});

check("שלב ללא נתונים מפיק אזהרה ולא תחזית", () => {
  clearAll();
  setVal("submissions", "9999");
  setVal("yachbam", "100");
  sandbox.calculate();
  const warned = registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("הגשות"));
  return warned ? null : "לא הוצגה אזהרה על שלב ללא נתונים";
});

check("איפוס מנקה הכל", () => {
  sandbox.reset();
  const cleared = stageKeys.every(k => registry["in_" + k].value === "");
  return cleared && !shown("results") ? null : "האיפוס לא ניקה הכל";
});

if (fails.length) {
  console.error("נכשלו " + fails.length + " בדיקות ממשק:");
  fails.forEach(f => console.error("  " + f));
  process.exit(1);
}
console.log("כל בדיקות הממשק עברו (" + (stageKeys.length + 10) + " תרחישים)");
