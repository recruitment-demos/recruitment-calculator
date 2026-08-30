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
const exposed = script + "\n;globalThis.DATA = DATA;" +
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

check("שדות הקלט נבנו", () =>
  stageKeys.every(k => registry["in_" + k]) && registry.in_target
    ? null : "חסר שדה קלט");

check("חותמת הנתונים הוצגה", () =>
  registry.stamp.textContent.length > 40 ? null : "חותמת ריקה");

check("פאנל בסיס הנתונים הוצג", () =>
  registry.basisBody.innerHTML.includes("<table") ? null : "אין טבלת בסיס");

check("רשימת המגבלות הוצגה", () =>
  (registry.limitsBody.innerHTML.match(/<li>/g) || []).length >= 5
    ? null : "פחות מדי מגבלות");

check("חישוב בלי קלט מבקש נתון", () => {
  clearAll();
  sandbox.calculate();
  return registry.gapBody.children.length > 0 ? null : "לא הוצגה הודעה";
});

for (const key of withData) {
  check("חישוב קדימה משלב " + key, () => {
    clearAll();
    setVal(key, "500");
    sandbox.calculate();
    if (registry.funnelCard.classList.contains("hidden")) return "טבלת המשפך מוסתרת";
    if (registry.funnelBody.children.length !== stageKeys.length + 1) return "מספר שורות שגוי";
    if (registry.timelineCard.classList.contains("hidden")) return "ציר הזמן מוסתר";
    if (registry.timelineBody.children.length !== sandbox.DATA.time_buckets.length)
      return "מספר דליי זמן שגוי";
    if (!registry.timelineSub.textContent.includes("חציון")) return "אין תיאור לציר הזמן";
    return null;
  });
}

check("חישוב לאחור מיעד בלבד", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  if (registry.funnelCard.classList.contains("hidden")) return "טבלת המשפך מוסתרת";
  if (!registry.timelineCard.classList.contains("hidden")) return "ציר הזמן היה צריך להיות מוסתר";
  return registry.gapBody.children.length > 0 ? null : "אין הודעת הסבר";
});

check("שני שלבים מייצרים ניתוח פערים", () => {
  clearAll();
  setVal("file_check", "100");
  setVal("yachbam", "400");
  sandbox.calculate();
  return registry.gapBody.children.length > 0 ? null : "אין הודעות פער";
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
  const hidden = ["funnelCard", "gapCard", "timelineCard"]
    .every(id => registry[id].classList.contains("hidden"));
  return cleared && hidden ? null : "האיפוס לא ניקה הכל";
});

if (fails.length) {
  console.error("נכשלו " + fails.length + " בדיקות ממשק:");
  fails.forEach(f => console.error("  " + f));
  process.exit(1);
}
console.log("כל בדיקות הממשק עברו");
