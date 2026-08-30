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
    value: "",
    _text: "",
    _html: "",
    classList: {
      _s: new Set(),
      add(...c) { c.forEach(x => this._s.add(x)); },
      remove(...c) { c.forEach(x => this._s.delete(x)); },
      contains(c) { return this._s.has(c); },
      toggle(c, force) {
        const on = force === undefined ? !this._s.has(c) : !!force;
        if (on) this._s.add(c); else this._s.delete(c);
        return on;
      }
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

const D = sandbox.DATA;
const stageKeys = D.stages.map(s => s.key);
const withData = D.stages.filter(s => s.has_data).map(s => s.key);
const setVal = (id, v) => { registry["in_" + id].value = v; };
const clearAll = () => { stageKeys.forEach(k => setVal(k, "")); setVal("target", ""); };
const shown = id => !registry[id].classList.contains("hidden");
const revealed = id => registry[id].classList.contains("in");
const num = s => Number(String(s).replace(/[^0-9]/g, ""));
const allText = node => {
  let out = node.textContent || "";
  (node.children || []).forEach(c => { out += " " + allText(c); });
  return out;
};

check("שדות הקלט נבנו", () =>
  stageKeys.every(k => registry["in_" + k]) && registry.in_target ? null : "חסר שדה קלט");

check("חותמת הנתונים הוצגה", () =>
  registry.stamp.textContent.length > 40 ? null : "חותמת ריקה");

check("טבלת המעברים הוצגה", () => {
  const h = registry.basisBody.innerHTML;
  return h.includes("<table") && h.includes("<strong>") ? null : "אין טבלת מעברים";
});

check("רשימת המגבלות הוצגה", () =>
  (registry.limitsBody.innerHTML.match(/<li>/g) || []).length >= 8
    ? null : "פחות מדי מגבלות");

check("בלי קלט התוצאות נשארות מוסתרות", () => {
  clearAll();
  sandbox.calculate();
  return shown("results") ? "התוצאות הוצגו בלי קלט" : null;
});

for (const key of withData) {
  check("גזירה קדימה משלב " + key, () => {
    clearAll();
    setVal(key, "1000");
    sandbox.calculate();
    if (!shown("results")) return "אזור התוצאות מוסתר";
    ["heroCard", "funnelCard", "whenCard", "gapCard"].forEach(id => {
      if (!revealed(id)) throw new Error("הכרטיס " + id + " לא הופיע");
    });
    const proj = sandbox.Engine.projectCohort(key, 1000);
    if (num(registry.heroValue.textContent) !== proj.hires)
      return "מספר המגויסים אינו תואם את המנוע";
    // מספר שורות המשפך = שלבי הקבוצה + שלבים ללא נתונים
    const noData = D.stages.filter(s => !s.has_data).length;
    if (registry.funnelBody.children.length !== proj.steps.length + noData)
      return "מספר שורות משפך שגוי: " + registry.funnelBody.children.length;
    if (!registry.whenBody.children.length) return "גרף הזמנים ריק";
    return null;
  });
}

check("כל מספר במשפך מסומן ממה נגזר", () => {
  clearAll();
  setVal("file_check", "5000");
  sandbox.calculate();
  const rows = registry.funnelBody.children;
  const missing = rows.filter(r =>
    !r.children.some(c => c.classList.contains("fsrc") && c.textContent.length > 3));
  return missing.length ? missing.length + " שורות בלי מקור" : null;
});

check("אין גזירה לאחור", () => {
  clearAll();
  setVal("yachbam", "300");
  sandbox.calculate();
  const text = allText(registry.funnelBody);
  // בדיקת קבצים קודמת ליחב"מ ולכן אסור שתופיע עם מספר גזור
  const proj = sandbox.Engine.projectCohort("yachbam", 300);
  const keys = proj.steps.map(s => s.key);
  return keys.indexOf("file_check") === -1 && !text.includes("בדיקת קבצים ")
    ? null : "הופיע שלב מוקדם יותר";
});

check("גרף הזמנים מציג שלב, כמות וימים", () => {
  clearAll();
  setVal("file_check", "5000");
  sandbox.calculate();
  const proj = sandbox.Engine.projectCohort("file_check", 5000);
  const rows = registry.whenBody.children[0].children
    .filter(c => c.classList.contains("tl"))[0].children
    .filter(c => c.classList.contains("tlrow"));
  if (rows.length !== proj.steps.length - 1)
    return "מספר שורות זמן שגוי: " + rows.length;
  const txt = allText(rows[0]);
  return txt.includes("מועמדים") ? null : "אין כמות בשורת הזמן";
});

check("שתי קבוצות מסתכמות ומזהירות מכפילות", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("yachbam", "300");
  sandbox.calculate();
  const a = sandbox.Engine.projectCohort("file_check", 5000).hires;
  const b = sandbox.Engine.projectCohort("yachbam", 300).hires;
  if (num(registry.heroValue.textContent) !== a + b) return "הסכום שגוי";
  const warned = registry.gapBody.children.some(c => c.classList.contains("warn"));
  if (!warned) return "אין אזהרת חפיפה";
  if (registry.whenBody.children.length !== 2) return "אין גרף זמנים לכל קבוצה";
  return null;
});

check("בדיקת עקביות מוצגת", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("yachbam", "10");
  sandbox.calculate();
  return registry.gapBody.children.some(c => c.textContent.includes("חסרים"))
    ? null : "לא הוצגה בדיקת עקביות";
});

check("חישוב לאחור מיעד בלבד", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  if (!shown("results")) return "אזור התוצאות מוסתר";
  if (num(registry.heroValue.textContent) !== 400) return "היעד לא הוצג";
  if (!registry.heroCap.textContent.includes("יעד")) return "כותרת שגויה";
  if (shown("whenCard")) return "גרף הזמנים היה צריך להיות מוסתר";
  if (shown("timelineCard")) return "גרף ההתפלגות היה צריך להיות מוסתר";
  return null;
});

check("יעד מול תחזית", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("target", "400");
  sandbox.calculate();
  return registry.gapBody.children.some(c => c.textContent.includes("יעד הגיוס"))
    ? null : "אין הודעת יעד";
});

check("שלב ללא נתונים מפיק אזהרה ולא תחזית", () => {
  clearAll();
  setVal("submissions", "9999");
  setVal("yachbam", "100");
  sandbox.calculate();
  const warned = registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("הגשות"));
  const cohorts = sandbox.Engine.combine({ submissions: 9999, yachbam: 100 }).cohorts;
  if (cohorts.length !== 1) return "שלב ללא נתונים נכנס לחישוב";
  return warned ? null : "לא הוצגה אזהרה";
});

check("אין טווחים בתצוגה", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("target", "300");
  sandbox.calculate();
  const texts = [registry.heroValue.textContent, allText(registry.funnelBody),
                 allText(registry.whenBody), allText(registry.timelineBody),
                 allText(registry.gapBody)];
  const bad = texts.find(t => /\d\s*[-–]\s*\d/.test(t));
  return bad ? "נמצא טווח בתצוגה" : null;
});

check("הסרגל הדביק מקבל את המספר", () => {
  clearAll();
  setVal("file_check", "5000");
  sandbox.calculate();
  const hires = sandbox.Engine.projectCohort("file_check", 5000).hires;
  return num(registry.stickyValue.textContent) === hires ? null : "הסרגל לא עודכן";
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
console.log("כל בדיקות הממשק עברו");
