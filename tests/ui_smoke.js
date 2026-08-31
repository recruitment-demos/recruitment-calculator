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

const whenRows = () => registry.whenBody.children
  .filter(c => c.classList.contains("tl"))[0].children
  .filter(c => c.classList.contains("tlrow"));

check("גרף הזמנים מציג שלב, כמות וימים", () => {
  clearAll();
  setVal("file_check", "5000");
  sandbox.calculate();
  const proj = sandbox.Engine.projectCohort("file_check", 5000);
  const rows = whenRows();
  if (rows.length !== proj.steps.length - 1)
    return "מספר שורות זמן שגוי: " + rows.length;
  const txt = allText(rows[0]);
  return txt.includes("מועמדים") ? null : "אין כמות בשורת הזמן";
});

check("גרף הזמנים הוא גרף אחד, לא גרף לכל קבוצה", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("yachbam", "300");
  sandbox.calculate();
  const charts = registry.whenBody.children.filter(c => c.classList.contains("tl"));
  if (charts.length !== 1) return "נמצאו " + charts.length + " גרפים במקום אחד";
  const keys = sandbox.Engine.combinedWhen({ file_check: 5000, yachbam: 300 })
    .map(r => r.key);
  if (new Set(keys).size !== keys.length) return "שלב הופיע יותר מפעם אחת";
  return whenRows().length === keys.length ? null : "מספר שורות שגוי";
});

check("שורה מאוחדת מפרטת את כל הקבוצות שתרמו לה", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("online_day", "800");
  sandbox.calculate();
  const hire = whenRows().filter(r => r.classList.contains("hire"))[0];
  const txt = allText(hire);
  return txt.includes("בדיקת קבצים") && txt.includes("יום מיון מקוון")
    ? null : "השורה המאוחדת לא מפרטת את שתי הקבוצות";
});

check("גרף מועדי הגיוס הוא גרף אחד", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("yachbam", "300");
  sandbox.calculate();
  if (registry.timelineBody.children.length !== 1)
    return "נמצאו " + registry.timelineBody.children.length + " גרפים במקום אחד";
  const merged = sandbox.Engine.combinedTimeline({ file_check: 5000, yachbam: 300 });
  const rows = registry.timelineBody.children[0].children
    .filter(c => c.classList.contains("bars"))[0].children;
  if (rows.length !== merged.rows.length) return "מספר חלונות זמן שגוי";
  const missing = rows.filter(r =>
    !r.children.some(c => c.classList.contains("fsrc") && c.textContent.length > 3));
  return missing.length ? missing.length + " שורות בלי מקור" : null;
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
  if (registry.whenBody.children.filter(c => c.classList.contains("tl")).length !== 1)
    return "גרף הזמנים אינו מאוחד";
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

const planRows = () => registry.planBody.children;
const pipeRows = () => registry.pipelineBody.children;

check("מצב תכנון מיעד נפתח כשהוזן רק יעד", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  if (!shown("results")) return "אזור התוצאות מוסתר";
  if (num(registry.heroValue.textContent) !== 400) return "היעד לא הוצג";
  if (!registry.heroCap.textContent.includes("יעד")) return "כותרת שגויה";
  if (!shown("planCard")) return "כרטיס «כמה צריך בכל שלב» מוסתר";
  if (!shown("pipelineCard")) return "כרטיס המשפך הרציף מוסתר";
  if (shown("whenCard")) return "גרף הזמנים היה צריך להיות מוסתר";
  if (shown("timelineCard")) return "גרף ההתפלגות היה צריך להיות מוסתר";
  return null;
});

check("כל שלב מקבל את הכמות שהמנוע מחשב", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const plan = sandbox.Engine.requiredPlan(400);
  if (planRows().length !== plan.rows.length)
    return "מספר שורות שגוי: " + planRows().length;
  const withData = plan.rows.filter(r => r.has_data);
  const shownNums = planRows()
    .filter(r => !r.classList.contains("nodata"))
    .map(r => num(r.children.filter(c => c.classList.contains("fval"))[0].textContent));
  const expected = withData.map(r => r.required);
  return JSON.stringify(shownNums) === JSON.stringify(expected)
    ? null : "הכמויות אינן תואמות את המנוע: " + shownNums;
});

check("כל כמות בתכנון אומרת ממה היא נגזרה", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const missing = planRows().filter(r =>
    !r.children.some(c => c.classList.contains("fsrc") && c.textContent.length > 10));
  if (missing.length) return missing.length + " שורות בלי מקור";
  const txt = allText(planRows()[1]);
  return txt.includes("שיעור גיוס") && txt.includes("חציון")
    ? null : "המקור לא מסביר את שיעור הגיוס ואת הזמן";
});

check("שלב ללא נתונים אינו מקבל כמות נדרשת", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const row = planRows()[0];
  if (!row.classList.contains("nodata")) return "השורה הראשונה אינה «הגשות»";
  const val = row.children.filter(c => c.classList.contains("fval"))[0];
  return val.textContent === "—" ? null : "הומצאה כמות לשלב ללא נתונים";
});

check("המשפך הרציף נגזר קדימה מהכמות הנדרשת", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const key = registry.planEntry.value;
  const plan = sandbox.Engine.planFromTarget(key, 400);
  if (pipeRows().length !== plan.projection.steps.length)
    return "מספר שורות שגוי: " + pipeRows().length;
  const nums = pipeRows().map(r =>
    num(r.children.filter(c => c.classList.contains("fval"))[0].textContent));
  const expected = plan.projection.steps.map(s => s.count);
  if (JSON.stringify(nums) !== JSON.stringify(expected))
    return "המשפך אינו תואם את המנוע";
  // ההבטחה שאפשר לבדוק: אותו מספר במחשבון הרגיל נותן אותו משפך
  const same = sandbox.Engine.projectCohort(key, plan.required);
  return JSON.stringify(same) === JSON.stringify(plan.projection)
    ? null : "המשפך אינו זהה לגזירה קדימה של הכמות הנדרשת";
});

check("החלפת נקודת הכניסה מציירת מחדש", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const before = allText(registry.pipelineBody);
  registry.planEntry.value = "screening_day";
  registry.planEntry._on.change();
  const after = allText(registry.pipelineBody);
  if (before === after) return "המשפך לא צויר מחדש";
  const plan = sandbox.Engine.planFromTarget("screening_day", 400);
  const first = num(pipeRows()[0].children
    .filter(c => c.classList.contains("fval"))[0].textContent);
  return first === plan.required ? null : "הכמות הנדרשת לא התעדכנה";
});

check("תאריך יעד מוסיף תאריכים ולא משנה כמויות", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const without = planRows().map(r =>
    r.children.filter(c => c.classList.contains("fval"))[0].textContent);

  registry.in_targetDate.value = "2027-01-15";
  sandbox.calculate();
  const withDate = planRows().map(r =>
    r.children.filter(c => c.classList.contains("fval"))[0].textContent);

  if (JSON.stringify(without) !== JSON.stringify(withDate))
    return "התאריך שינה את הכמויות";
  const txt = allText(registry.planBody);
  if (!txt.includes("2026") && !txt.includes("2027")) return "לא הופיעו תאריכים";
  return allText(registry.pipelineBody).includes("2026") ||
         allText(registry.pipelineBody).includes("2027")
    ? null : "אין תאריכים במשפך הרציף";
});

check("תאריך היעד קודם לתאריך שבו צריך להיות בשלב", () => {
  clearAll();
  setVal("target", "400");
  registry.in_targetDate.value = "2027-01-15";
  sandbox.calculate();
  // חציון 71 ימים מבדיקת קבצים ועד גיוס, ולכן התאריך חייב ליפול ב-2026
  const row = allText(planRows()[1]);
  return row.includes("2026") ? null : "התאריך הנדרש אינו לפני יעד הגיוס";
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
  const texts = [];
  clearAll();
  setVal("file_check", "5000");
  setVal("target", "300");
  sandbox.calculate();
  texts.push(registry.heroValue.textContent, allText(registry.funnelBody),
             allText(registry.whenBody), allText(registry.timelineBody),
             allText(registry.gapBody));

  clearAll();
  setVal("target", "300");
  registry.in_targetDate.value = "2027-01-15";
  sandbox.calculate();
  texts.push(allText(registry.planBody), allText(registry.pipelineBody),
             allText(registry.gapBody), registry.planSub.textContent,
             registry.pipelineSub.textContent);

  const bad = texts.find(t => /\d\s*[-–]\s*\d/.test(t));
  return bad ? "נמצא טווח בתצוגה: " + bad.slice(0, 90) : null;
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
  if (!cleared || shown("results")) return "האיפוס לא ניקה הכל";
  return registry.in_target.value === "" && registry.in_targetDate.value === ""
    ? null : "היעד או התאריך לא נוקו";
});

if (fails.length) {
  console.error("נכשלו " + fails.length + " בדיקות ממשק:");
  fails.forEach(f => console.error("  " + f));
  process.exit(1);
}
console.log("כל בדיקות הממשק עברו");
