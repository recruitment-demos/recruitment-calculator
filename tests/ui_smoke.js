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
    fails.push(name + ": " + (e && e.stack ? e.stack.split("\n").slice(0,4).join(" | ") : e));
  }
}

const D = sandbox.DATA;
const stageKeys = D.stages.map(s => s.key);
const withData = D.stages.filter(s => s.has_data).map(s => s.key);
const setVal = (id, v) => { registry["in_" + id].value = v; };
const clearAll = () => {
  stageKeys.forEach(k => setVal(k, ""));
  setVal("target", "");
  setVal("targetDate", "");
};
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

check("אין שורה בלי מספר ובלי הסבר", () => {
  // מאז שהתקבל קובץ ההגשות יש לכל שלב מקור נתונים. הכלל שנשמר: שורה
  // בלי מספר חייבת לומר במפורש «לא בר-השגה» או «לא יספיק», ולא להישאר
  // ריקה - ושורה עם מספר חייבת להיות מספר, לא טקסט.
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const rows = planRows();
  if (!rows.length) return "אין שורות במשפך הנדרש";
  const bad = rows.filter(r => {
    const val = r.children.filter(c => c.classList.contains("fval"))[0];
    const t = val ? val.textContent : "";
    return !t || (!/[0-9]/.test(t) && t.indexOf("לא ") !== 0);
  });
  return bad.length ? bad.length + " שורות בלי מספר ובלי הסבר" : null;
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

check("דדליין קרוב מעלה את הכמות הנדרשת", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const open = num(planRows()[6].children
    .filter(c => c.classList.contains("fval"))[0].textContent);

  // חודש קדימה: רק חלק קטן ממי שנכנס יספיק להתגייס
  const soon = new Date();
  soon.setDate(soon.getDate() + 30);
  setVal("targetDate", soon.getFullYear() + "-" +
    String(soon.getMonth() + 1).padStart(2, "0") + "-" +
    String(soon.getDate()).padStart(2, "0"));
  sandbox.calculate();
  const tight = num(planRows()[6].children
    .filter(c => c.classList.contains("fval"))[0].textContent);

  if (!(tight > open)) return "הדדליין לא העלה את הדרישה: " + tight + " מול " + open;
  const expected = sandbox.Engine.requiredPlan(400, 30).rows[6].required;
  return tight === expected ? null : "הכמות אינה תואמת את המנוע";
});

check("שלב שלא יכול לספק את היעד בזמן מסומן ולא מקבל מספר", () => {
  clearAll();
  setVal("target", "400");
  const soon = new Date();
  soon.setDate(soon.getDate() + 10);
  setVal("targetDate", soon.getFullYear() + "-" +
    String(soon.getMonth() + 1).padStart(2, "0") + "-" +
    String(soon.getDate()).padStart(2, "0"));
  sandbox.calculate();
  // בדיקת קבצים אינה מגייסת כלל תוך 10 ימים - הרצפה שלה 21 ימים
  const row = planRows()[1];
  const val = row.children.filter(c => c.classList.contains("fval"))[0];
  if (/[0-9]/.test(val.textContent))
    return "הוצג מספר לשלב שאינו יכול לספק: " + val.textContent;
  if (val.textContent !== "לא יספיק")
    return "סימון לא צפוי: " + val.textContent;
  return allText(row).includes("לא יספיק להתגייס") ? null : "אין הסבר";
});

/* ---- המקרה שדווח: 400 גיוסים עד סוף ספטמבר ---- */
const inDays = n => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
         "-" + String(d.getDate()).padStart(2, "0");
};
const valuesOf = body => body.children.map(r => {
  const v = r.children.filter(c => c.classList.contains("fval"))[0];
  return v ? v.textContent : "";
});

check("יעד בלתי אפשרי אינו מוצג כמספר ענק", () => {
  clearAll();
  setVal("target", "400");
  setVal("targetDate", inDays(30));
  sandbox.calculate();
  // אף תא ערך לא יציג כמות שגדולה מכל מה שנמדד אי פעם
  const plan = sandbox.Engine.requiredPlan(400, 30);
  const shown = valuesOf(registry.planBody);
  for (let i = 0; i < plan.rows.length; i++) {
    const r = plan.rows[i];
    if (r.has_data && !r.feasible && /[0-9]/.test(shown[i]))
      return "הוצג מספר לשלב שאינו בר-השגה: " + shown[i];
  }
  return shown.some(v => v.includes("לא בר-השגה")) ? null : "אין סימון";
});

check("שורת הגיוס במשפך מציגה את היעד ולא את הגיוסים בסך הכול", () => {
  clearAll();
  setVal("target", "400");
  setVal("targetDate", inDays(30));
  sandbox.calculate();
  const rows = registry.pipelineBody.children;
  const hire = rows.filter(r => r.classList.contains("hire"))[0];
  if (!hire) return "אין שורת גיוס";
  const shown = num(hire.children.filter(c => c.classList.contains("fval"))[0].textContent);
  const key = registry.planEntry.value;
  const plan = sandbox.Engine.planFromTarget(key, 400, 30);
  if (shown !== plan.hires_in_time)
    return "שורת הגיוס מציגה " + shown + " ולא " + plan.hires_in_time;
  if (shown !== 400) return "שורת הגיוס אינה היעד: " + shown;
  return null;
});

check("המשפך נפתח בשלב שממנו היעד אפשרי", () => {
  clearAll();
  setVal("target", "400");
  setVal("targetDate", inDays(30));
  sandbox.calculate();
  const feasible = sandbox.Engine.feasibleStages(400, 30);
  if (!feasible.length) return "התרחיש אינו מתאים - אין שלב אפשרי";
  return feasible.indexOf(registry.planEntry.value) !== -1
    ? null : "נפתח בשלב שאינו אפשרי: " + registry.planEntry.value;
});

check("כשאין שום שלב אפשרי נאמר זאת במפורש", () => {
  clearAll();
  setVal("target", "100000");
  setVal("targetDate", inDays(30));
  sandbox.calculate();
  if (sandbox.Engine.feasibleStages(100000, 30).length)
    return "התרחיש אינו מתאים";
  const txt = allText(registry.pipelineBody);
  return txt.includes("אינו בר-השגה") ? null : "לא נאמר שהיעד בלתי אפשרי";
});

check("יעד רחוק כן מוצג עם מספרים אמיתיים", () => {
  clearAll();
  setVal("target", "400");
  setVal("targetDate", inDays(122));
  sandbox.calculate();
  const rows = registry.pipelineBody.children;
  const hire = rows.filter(r => r.classList.contains("hire"))[0];
  const shown = num(hire.children.filter(c => c.classList.contains("fval"))[0].textContent);
  if (shown !== 400) return "שורת הגיוס אינה 400 אלא " + shown;
  const first = num(rows[0].children
    .filter(c => c.classList.contains("fval"))[0].textContent);
  const obs = sandbox.Engine.observedCandidates(registry.planEntry.value);
  return first <= obs ? null : "הכמות גדולה מכל מה שנמדד: " + first;
});

check("דרישה גדולה מכל מה שנמדד מוסברת במפורש", () => {
  clearAll();
  setVal("target", "400");
  setVal("targetDate", inDays(30));
  sandbox.calculate();
  const txt = allText(registry.planBody);
  return txt.includes("הגדולה ביותר שנמדדה") && txt.includes("מעולם לא היתה קיימת")
    ? null : "לא הוסבר למה הכמות אינה בת-השגה";
});

check("תאריך יעד מוסיף גם תאריכים", () => {
  clearAll();
  setVal("target", "400");
  setVal("targetDate", "2027-01-15");
  sandbox.calculate();
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

check("שלב ההגשות נכנס לחישוב ככל שלב אחר", () => {
  clearAll();
  setVal("submissions", "9999");
  setVal("yachbam", "100");
  sandbox.calculate();
  const cohorts = sandbox.Engine.combine({ submissions: 9999, yachbam: 100 }).cohorts;
  if (cohorts.length !== 2) return "ההגשות לא נכנסו לחישוב";
  const warned = registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("קבוצות"));
  if (!warned) return "לא הוצגה אזהרת חפיפה";
  return allText(registry.funnelBody).includes("הגשות")
    ? null : "ההגשות אינן מופיעות במשפך";
});

check("משפך המיון המלא מוצג", () => {
  const rows = registry.fullFunnelBody.children;
  // שתי שורות כותרת ועוד שורה לכל שלב, כולל הגיוס
  if (rows.length !== 2 + D.funnel.rows.length) return "מספר שורות לא צפוי";
  const txt = allText(registry.fullFunnelBody);
  return D.funnel.rows.every(r => txt.includes(r.label))
    ? null : "חסר שלב במשפך המלא";
});

check("הפער בין הערוצים מוצג ומוסבר", () => {
  const txt = allText(registry.segmentsBody);
  const named = D.segments.filter(g => g.funnel);
  if (!named.every(g => txt.includes(g.label))) return "חסר ערוץ";
  return txt.includes("פי ") ? null : "אין השוואה מספרית בין הערוצים";
});

check("הלוח של מנהלת הגיוס מציג כמות ותאריך לכל שלב", () => {
  clearAll();
  setVal("target", "400");
  const soon = new Date();
  soon.setDate(soon.getDate() + 150);
  setVal("targetDate", soon.getFullYear() + "-" +
    String(soon.getMonth() + 1).padStart(2, "0") + "-" +
    String(soon.getDate()).padStart(2, "0"));
  sandbox.calculate();
  if (!shown("managerCard")) return "הכרטיס לא הוצג";
  const rows = registry.managerBody.children;
  // שורת כותרת, ואז זוג שורות לכל שלב: הנתונים וההסבר שמתחתיו
  if (rows.length !== 1 + withData.length * 2) return "מספר שורות לא צפוי";
  const why = rows.filter(r => r.classList.contains("why"));
  if (why.some(r => allText(r).length < 30)) return "יש שורה בלי הסבר מקור";
  const data = rows.filter((r, i) => i > 0 && !r.classList.contains("why"));
  const bad = data.filter(r => {
    const by = r.children[1], when = r.children[2];
    const t = by.textContent;
    if (!t || (!/[0-9]/.test(t) && t !== "לא בר-השגה" && t !== "—")) return true;
    return !when.textContent;
  });
  return bad.length ? bad.length + " שורות בלי כמות או בלי תאריך" : null;
});

check("בלי תאריך יעד שתי הכמויות בלוח זהות", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const plan = sandbox.Engine.managerPlan({}, 400, null);
  const diff = plan.rows.filter(r => r.has_data &&
                                r.required_by !== r.required_now);
  if (diff.length) return "הכמויות נפרדו בלי תאריך יעד";
  return plan.rows.every(r => r.deadline_days === null)
    ? null : "נקבע תאריך יעד בלי שהוזן";
});

check("הטבלה האחת מסתכמת בדיוק", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("yachbam", "200");
  sandbox.calculate();
  if (!shown("matrixCard")) return "הטבלה לא הוצגה";
  const m = sandbox.Engine.combinedMatrix({ file_check: 5000, yachbam: 200 });
  const off = m.rows.filter(r => {
    let sum = 0;
    r.cells.forEach(c => { sum += c.count; });
    return sum !== r.count;
  });
  if (off.length) return off.length + " שורות שסכום החלונות בהן אינו הסך הכול";
  const rows = registry.matrixBody.children;
  // כותרת, זוג שורות לכל שלב, ושורת הסבר החלונות בסוף
  if (rows.length !== 2 + m.rows.length * 2) return "מספר שורות לא צפוי";
  const why = rows.filter(r => r.classList.contains("why"));
  return why.every(r => allText(r).length > 20)
    ? null : "יש שורה בלי מקור";
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

check("תאריך יעד בזרימה קדימה מקטין את המספר הגדול", () => {
  clearAll();
  setVal("file_check", "1000");
  sandbox.calculate();
  const eventual = sandbox.Engine.projectCohort("file_check", 1000).hires;
  if (num(registry.heroValue.textContent) !== eventual)
    return "בלי תאריך המספר אינו מספר הגיוסים הכולל";

  // תאריך עתידי קרוב: רק חלק מהמגויסים יספיקו עד אז
  const soon = new Date();
  soon.setDate(soon.getDate() + 30);
  const iso = soon.getFullYear() + "-" +
    String(soon.getMonth() + 1).padStart(2, "0") + "-" +
    String(soon.getDate()).padStart(2, "0");
  setVal("targetDate", iso);
  sandbox.calculate();

  const expected = sandbox.Engine.hiresByDay("file_check", 1000, 30);
  const got = num(registry.heroValue.textContent);
  if (got !== expected) return "המספר " + got + " אינו " + expected;
  if (got >= eventual) return "התאריך לא הקטין את המספר";
  if (!registry.heroCap.textContent.includes("עד ")) return "הכותרת לא מזכירה תאריך";
  return allText(registry.gapBody).includes(String(eventual))
    ? null : "לא נאמר מהו מספר הגיוסים הכולל";
});

check("חלונות שמאוחרים מתאריך היעד מסומנים", () => {
  clearAll();
  setVal("file_check", "1000");
  const soon = new Date();
  soon.setDate(soon.getDate() + 30);
  setVal("targetDate", soon.getFullYear() + "-" +
    String(soon.getMonth() + 1).padStart(2, "0") + "-" +
    String(soon.getDate()).padStart(2, "0"));
  sandbox.calculate();
  const rows = registry.timelineBody.children[0].children
    .filter(c => c.classList.contains("bars"))[0].children;
  const late = rows.filter(r => r.classList.contains("late"));
  // החלונות "חודש עד חודשיים" ואילך מתחילים אחרי יום 30
  if (late.length !== 3) return "סומנו " + late.length + " חלונות במקום 3";
  return allText(late[0]).includes("אחרי תאריך היעד") ? null : "אין הסבר לסימון";
});

check("תאריך שעבר אינו משנה את המספר ומפיק אזהרה", () => {
  clearAll();
  setVal("file_check", "1000");
  setVal("targetDate", "2020-01-01");
  sandbox.calculate();
  const eventual = sandbox.Engine.projectCohort("file_check", 1000).hires;
  if (num(registry.heroValue.textContent) !== eventual)
    return "תאריך שעבר שינה את המספר";
  return registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("כבר עבר"))
    ? null : "אין אזהרה על תאריך שעבר";
});

check("תאריך לא תקין מפיק אזהרה ואינו נבלע", () => {
  clearAll();
  setVal("file_check", "1000");
  setVal("targetDate", "2026-09-31");
  sandbox.calculate();
  const eventual = sandbox.Engine.projectCohort("file_check", 1000).hires;
  if (num(registry.heroValue.textContent) !== eventual)
    return "תאריך לא תקין השפיע על החישוב";
  return registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("אינו תאריך תקין"))
    ? null : "אין אזהרה על תאריך לא תקין";
});

check("היעד נמדד מול מה שיתגייס עד התאריך", () => {
  clearAll();
  setVal("file_check", "1000");
  setVal("target", "50");
  const soon = new Date();
  soon.setDate(soon.getDate() + 30);
  setVal("targetDate", soon.getFullYear() + "-" +
    String(soon.getMonth() + 1).padStart(2, "0") + "-" +
    String(soon.getDate()).padStart(2, "0"));
  sandbox.calculate();
  // 99 בסך הכול עוברים את היעד 50, אבל עד 30 יום רק 25 - כלומר חוסר
  const txt = allText(registry.gapBody);
  return txt.includes("חסרים") ? null : "היעד נמדד מול המספר הכולל ולא עד התאריך";
});

check("יעד עם מלאי קיים מציג כמה עוד צריך", () => {
  clearAll();
  setVal("yachbam", "200");
  setVal("target", "400");
  sandbox.calculate();
  if (!shown("gapCardPlan")) return "כרטיס ההשלמה מוסתר";
  const plan = sandbox.Engine.gapPlan({ yachbam: 200 }, 400, null);
  const rows = registry.gapPlanBody.children.filter(r => !r.classList.contains("msg"));
  const nums = rows.map(r =>
    num(r.children.filter(c => c.classList.contains("fval"))[0].textContent));
  const expected = plan.rows.filter(r => r.has_data).map(r => r.required);
  if (JSON.stringify(nums) !== JSON.stringify(expected))
    return "הכמויות אינן תואמות את המנוע";
  // חייב להיות קטן מהדרישה כשאין מלאי כלל
  const bare = sandbox.Engine.gapPlan({}, 400, null);
  const bareFirst = bare.rows.filter(r => r.has_data)[0].required;
  return nums[0] < bareFirst ? null : "המלאי הקיים לא הקטין את הדרישה";
});

check("כמה כבר בדרך נאמר במפורש", () => {
  clearAll();
  setVal("yachbam", "200");
  setVal("target", "400");
  sandbox.calculate();
  const plan = sandbox.Engine.gapPlan({ yachbam: 200 }, 400, null);
  const sub = registry.gapPlanSub.textContent;
  return sub.includes(String(plan.have)) && sub.includes(String(plan.gap))
    ? null : "לא נאמר כמה כבר בדרך וכמה חסר";
});

check("יעד שכבר הושג אינו מבקש תוספת", () => {
  clearAll();
  setVal("yachbam", "1000");
  setVal("target", "400");
  sandbox.calculate();
  const txt = allText(registry.gapPlanBody);
  return txt.includes("אין צורך בתוספת") ? null : "לא נאמר שהיעד מושג";
});

check("שלב שלא יספיק עד התאריך מסומן", () => {
  clearAll();
  setVal("file_check", "100");
  setVal("target", "400");
  const soon = new Date();
  soon.setDate(soon.getDate() + 10);
  setVal("targetDate", soon.getFullYear() + "-" +
    String(soon.getMonth() + 1).padStart(2, "0") + "-" +
    String(soon.getDate()).padStart(2, "0"));
  sandbox.calculate();
  const rows = registry.gapPlanBody.children.filter(r => r.classList.contains("nodata"));
  if (!rows.length) return "אף שלב לא סומן כלא מספיק";
  return allText(rows[0]).includes("לא יספיק") ? null : "אין הסבר לסימון";
});

check("החלפת נקודת הכניסה בהשלמה מציירת מחדש", () => {
  clearAll();
  setVal("yachbam", "100");
  setVal("target", "400");
  sandbox.calculate();
  const before = allText(registry.gapPipeBody);
  registry.gapEntry.value = "screening_day";
  registry.gapEntry._on.change();
  return allText(registry.gapPipeBody) !== before ? null : "לא צויר מחדש";
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
