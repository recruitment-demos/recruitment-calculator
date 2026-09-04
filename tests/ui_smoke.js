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
                "globalThis.calculate = calculate; globalThis.reset = reset;" +
                "globalThis.activeCounts = activeCounts;" +
                "globalThis.applyActiveRows = applyActiveRows;" +
                "globalThis.setPopulation = setPopulation;" +
                "globalThis.snapshotInputs = snapshotInputs;" +
                "globalThis.restoreInputs = restoreInputs;";
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

/* כל ההסברים ירדו מגוף העמוד ועברו לחלון שנפתח בלחיצה על ⓘ. הטקסט
   נשמר ב-data-info של הכפתור, ולכן הבדיקה «כל מספר אומר ממה הוא נגזר»
   נמדדת שם ולא במלל שעל המסך. */
const infoOf = node => {
  let out = (node.attributes && node.attributes["data-info"]) || "";
  (node.children || []).forEach(c => { out += " " + infoOf(c); });
  return out;
};
const at = id => registry[id] || { children: [], attributes: {}, textContent: "" };
const hasInfo = (row, min) => infoOf(row).trim().length > (min || 10);
const fval = row => {
  // הכמות יושבת ב-span משלה, ולצידו small עם הזמן או הקצב. אסור
  // שהספרות של ה-small ייספרו כחלק מהכמות.
  const v = (row.children || []).filter(c => c.classList.contains("fval"))[0];
  if (!v) return "";
  const n = (v.children || []).filter(c => c.classList.contains("n"))[0];
  return n ? n.textContent : v.textContent;
};
const inDays = n => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
         "-" + String(d.getDate()).padStart(2, "0");
};
const pctOf = x => (x * 100).toFixed(1) + "%";
// במצב יעד הכרטיס הכחול מציג את היעד, וכמות ההגשות יושבת בשורה שמתחתיו
const heroSubs = () => num(registry.heroNote.textContent.split("·")[0]);
const flowRows = () => registry.flowBody.children;
const constraintRows = () => registry.constraintBody.children;

check("שדות הקלט נבנו", () =>
  stageKeys.every(k => registry["in_" + k]) && registry.in_target ? null : "חסר שדה קלט");

check("ההסבר הכללי יושב בחלון ולא בעמוד", () => {
  const t = infoOf(registry.aboutBtn);
  if (t.length < 400) return "ההסבר הכללי קצר מדי או חסר";
  if (!t.includes("מגבלות")) return "אין מגבלות בהסבר הכללי";
  return t.includes("שני כיוונים") || t.includes("בשני כיוונים")
    ? null : "ההסבר אינו אומר שהמחשבון עובד בשני כיוונים";
});

check("חלון ההסבר נפתח ונסגר", () => {
  registry.aboutBtn._on.click();
  if (!registry.infoModal.classList.contains("open")) return "החלון לא נפתח";
  if (!registry.infoTitle.textContent) return "אין כותרת בחלון";
  if (!registry.infoText.children.length) return "אין תוכן בחלון";
  registry.infoClose._on.click();
  return registry.infoModal.classList.contains("open") ? "החלון לא נסגר" : null;
});

check("בלי קלט התוצאות נשארות מוסתרות", () => {
  clearAll();
  sandbox.calculate();
  return shown("results") ? "התוצאות הוצגו בלי קלט" : null;
});

/* ------------------------------------------------------------------ *
 *  כיוון א': רק יעד                                                    *
 * ------------------------------------------------------------------ */

check("מצב תכנון מיעד נפתח כשהוזן רק יעד", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  if (!shown("results")) return "אזור התוצאות מוסתר";
  const cp = sandbox.Engine.constrainedPlan(400, null);
  // הכרטיס הכחול הוא היעד עצמו, וההגשות מתחתיו
  if (num(registry.heroValue.textContent) !== 400)
    return "הכרטיס אינו מציג את היעד: " + registry.heroValue.textContent;
  if (heroSubs() !== cp.submissions)
    return "ההגשות הדרושות לא הוצגו: " + registry.heroNote.textContent;
  if (!registry.heroCap.textContent.includes("יעד")) return "כותרת שגויה";
  return shown("constraintCard") ? null : "המחשבון עם האילוצים מוסתר";
});

check("במצב יעד יש תשובה אחת, ולצידה אותן טבלאות זמן", () => {
  // תשובה אחת לשאלת הכמות (המשפך), ואותן טבלאות זמן כמו במצב זרימה -
  // בקשה מפורשת. מה שאסור שיחזור הוא כרטיס נוסף שעונה על אותה שאלה
  // במספר אחר.
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const open = ["heroCard", "constraintCard", "flowCard", "gapCardPlan",
                "whenCard", "matrixCard", "timelineCard"].filter(shown);
  return JSON.stringify(open) === JSON.stringify(
    ["heroCard", "constraintCard", "whenCard", "matrixCard", "timelineCard"])
    ? null : "כרטיסים לא צפויים: " + open.join(", ");
});

check("הטבלאות במצב יעד תואמות את המשפך שמעליהן", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = plan.submissions;
  const m = sandbox.Engine.constrainedMatrix(counts, null);
  const byKey = {};
  m.rows.forEach(r => { byKey[r.key] = r.count; });
  const off = plan.rows.filter(r => byKey[r.key] !== undefined &&
                                    Math.abs(byKey[r.key] - r.total) > 2);
  if (off.length) return "הטבלה והמשפך נפרדו ב«" + off[0].label + "»";
  // והשורות אכן צוירו
  const rows = registry.matrixBody.children;
  if (rows.length !== 1 + m.rows.length) return "מספר שורות לא צפוי";
  const tl = registry.whenBody.children.filter(c => c.classList.contains("tl"))[0];
  return tl && tl.children.filter(c => c.classList.contains("tlrow")).length
    === m.rows.length ? null : "פריסת הזמנים לא צוירה";
});

check("הטבלאות במצב יעד מתכיילות לחלון הימים שנותרו", () => {
  clearAll();
  setVal("target", "4000");
  setVal("targetDate", inDays(27));
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(4000, 27);
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = plan.submissions;
  const m = sandbox.Engine.constrainedMatrix(counts, 27);
  const shownNums = registry.matrixBody.children
    .filter((r, i) => i > 0).map(r => num(allText(r.children[m.buckets.length + 1])));
  const expected = m.rows.map(r => r.count);
  if (JSON.stringify(shownNums) !== JSON.stringify(expected))
    return "הטבלה אינה מתכיילת לחלון";
  // וחלונות שמאוחרים מהתאריך מסומנים
  const late = registry.matrixBody.children[0].children
    .filter(c => c.classList.contains("late"));
  return late.length > 0 ? null : "חלונות מאוחרים אינם מסומנים";
});

check("תאריך שאינו משנה את הכמות אומר זאת במפורש", () => {
  // התקלה שדווחה: יעד 200 עם ובלי תאריך החזיר בדיוק 3,642 הגשות,
  // ולא היתה שום אמירה על כך.
  clearAll();
  setVal("target", "200");
  setVal("targetDate", inDays(27));
  sandbox.calculate();
  const withDate = heroSubs();
  const bare = sandbox.Engine.constrainedPlan(200, null).submissions;
  const txt = allText(registry.gapBody);
  if (withDate === bare) {
    return txt.includes("זהה לזו שבשנה שלמה") && txt.includes("הקצב")
      ? null : "לא נאמר למה הכמות לא השתנתה";
  }
  return txt.includes("גדולה מזו של אותו יעד בשנה שלמה")
    ? null : "לא נאמר שהחלון הגדיל את הדרישה";
});

check("חלון קצר מספיק כן משנה את הכמות", () => {
  clearAll();
  setVal("target", "200");
  sandbox.calculate();
  const annual = heroSubs();
  setVal("targetDate", inDays(10));
  sandbox.calculate();
  const short = heroSubs();
  if (short <= annual) return "חלון של 10 ימים לא הגדיל את הדרישה";
  return allText(registry.gapBody).includes("גדולה מזו של אותו יעד בשנה שלמה")
    ? null : "לא הוסבר למה";
});

check("ההגשות הדרושות ל-4,000 הן כ-82 אלף", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  if (num(registry.heroValue.textContent) !== 4000)
    return "הכרטיס אינו מציג את היעד";
  const v = heroSubs();
  if (v !== sandbox.Engine.constrainedPlan(4000, null).submissions)
    return "המספר אינו של מודל האילוצים: " + v;
  if (v < 70000 || v > 95000) return "כמות ההגשות אינה סבירה: " + v;
  const thr = sandbox.Engine.throughputPlan(4000, null);
  const thrSub = thr.rows.filter(r => r.key === "submissions")[0].required;
  const req = sandbox.Engine.requiredPlan(4000, null)
    .rows.filter(r => r.key === "submissions")[0].required;
  const page = allText(registry.constraintBody) + " " +
               allText(registry.constraintLanes) + " " +
               registry.heroValue.textContent;
  if (page.includes(thrSub.toLocaleString("he-IL")))
    return "מספר ההכפלה הרוחבית עדיין בעמוד";
  if (page.includes(req.toLocaleString("he-IL")))
    return "מספר שיעור הקוהורט עדיין בעמוד";
  return null;
});

check("המשפך עם האילוצים מציג את כל השרשרת ואת תחנת הצד", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  const rows = constraintRows();
  if (rows.length !== plan.rows.length + plan.aside.length)
    return "מספר שורות שגוי: " + rows.length;
  const asideRows = rows.filter(r => r.classList.contains("aside"));
  if (asideRows.length !== plan.aside.length)
    return "מרכז הערכה אינו מסומן כתחנת צד";
  return infoOf(asideRows[0]).includes("לא בשרשרת")
    ? null : "תחנת הצד אינה אומרת שהיא מחוץ לשרשרת";
});

check("הכמויות במשפך האילוצים תואמות את המנוע", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  const shownNums = constraintRows()
    .filter(r => !r.classList.contains("aside"))
    .map(r => num(fval(r)));
  return JSON.stringify(shownNums) === JSON.stringify(plan.rows.map(r => r.total))
    ? null : "הכמויות אינן תואמות: " + shownNums;
});

check("כל שורה במשפך האילוצים אומרת ממה היא נגזרה", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const missing = constraintRows().filter(r => !hasInfo(r, 20));
  if (missing.length) return missing.length + " שורות בלי מקור";
  const txt = infoOf(constraintRows()[0]);
  return txt.includes("אוכלוסייה מוכרת") && txt.includes("אוכלוסייה חדשה")
    ? null : "שורת ההגשות אינה מפרידה בין שני הנתיבים";
});

check("שורה מציגה שם, אחוז וכמות בלבד", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const bad = constraintRows().filter(r => r.children.length !== 3);
  if (bad.length) return bad.length + " שורות עם יותר משלושה חלקים";
  const prose = constraintRows().filter(r =>
    (r.children || []).some(c => c.classList.contains("fsrc")));
  if (prose.length) return "נשאר מלל בגוף השורה";
  const second = constraintRows()[1];
  const chip = second.children[0].children.filter(c => c.classList.contains("fpct"))[0];
  if (!chip || !chip.textContent.includes("%")) return "אין אחוז מעבר בשורה";
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  return chip.textContent.indexOf((plan.rows[0].rate_to_next * 100).toFixed(1)) === 0
    ? null : "אחוז המעבר אינו של השלב הקודם: " + chip.textContent;
});

check("אין נתוני אמת גולמיים בגוף העמוד", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  const body = allText(registry.constraintBody) + " " +
               allText(registry.constraintLanes);
  const leaked = plan.rows.filter(r =>
    body.includes(r.baseline.toLocaleString("he-IL")));
  if (leaked.length) return "נחשף נפח היסטורי בגוף העמוד: " + leaked[0].label;
  return body.includes("נמדד בפועל") ? "נשארה עמודת «נמדד בפועל»" : null;
});

/* ------------------------------------------------------------------ *
 *  תאריך יעד                                                          *
 * ------------------------------------------------------------------ */

check("תאריך יעד משנה את הכמות ולא רק את התאריך", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const annual = heroSubs();
  setVal("targetDate", inDays(180));
  sandbox.calculate();
  const half = heroSubs();
  if (half === annual) return "התאריך לא שינה את הכמות";
  if (half !== sandbox.Engine.constrainedPlan(4000, 180).submissions)
    return "הכמות אינה תואמת את המנוע";
  // הנתיב המוכר תורם רק מחצית, ולכן חלון קצר דורש יותר הגשות
  return half > annual ? null : "חלון קצר לא הגדיל את הדרישה: " + half;
});

check("תאריך יעד מציג כמה זמן נשאר", () => {
  clearAll();
  setVal("target", "4000");
  setVal("targetDate", inDays(200));
  sandbox.calculate();
  const t = registry.heroNote.textContent;
  if (!t.includes("נותרו")) return "לא נאמר כמה זמן נשאר: " + t;
  return /\d{4}/.test(registry.heroCap.textContent)
    ? null : "אין תאריך בכותרת: " + registry.heroCap.textContent;
});

check("תאריך יעד מציג קצב נדרש לכל שלב", () => {
  clearAll();
  setVal("target", "4000");
  setVal("targetDate", inDays(200));
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(4000, 200);
  const rows = constraintRows().filter(r => !r.classList.contains("aside"));
  const missing = rows.filter(r => {
    const v = r.children.filter(c => c.classList.contains("fval"))[0];
    const small = (v.children || []).filter(c => c.tagName === "small")[0];
    return !small || !/[0-9]/.test(small.textContent);
  });
  if (missing.length) return missing.length + " שורות בלי קצב";
  const first = rows[0].children.filter(c => c.classList.contains("fval"))[0]
    .children.filter(c => c.tagName === "small")[0].textContent;
  if (!/ליום|לשבוע|לחודש/.test(first)) return "הקצב אינו ליום/לשבוע: " + first;
  return num(first) === Math.round(plan.rows[0].per_day)
    ? null : "הקצב אינו תואם את המנוע: " + first;
});

check("הנתיב המוכר נחתך לפי אורך החלון", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const yearKnown = num(registry.constraintLanes.children[0].children[1].textContent);
  setVal("targetDate", inDays(182));
  sandbox.calculate();
  const halfKnown = num(registry.constraintLanes.children[0].children[1].textContent);
  if (!(halfKnown < yearKnown)) return "הנתיב המוכר לא הצטמצם: " + halfKnown;
  return halfKnown === sandbox.Engine.constrainedPlan(4000, 182).known.hires
    ? null : "אינו תואם את המנוע";
});

check("תאריך שעבר מפיק אזהרה ואינו משנה את החישוב", () => {
  clearAll();
  setVal("target", "4000");
  setVal("targetDate", "2020-01-01");
  sandbox.calculate();
  if (heroSubs() !== sandbox.Engine.constrainedPlan(4000, null).submissions)
    return "תאריך שעבר שינה את החישוב";
  return registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("כבר עבר"))
    ? null : "אין אזהרה על תאריך שעבר";
});

check("תאריך לא תקין מפיק אזהרה ואינו נבלע", () => {
  clearAll();
  setVal("target", "4000");
  setVal("targetDate", "2026-09-31");
  sandbox.calculate();
  return registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("אינו תאריך תקין"))
    ? null : "אין אזהרה על תאריך לא תקין";
});

/* ------------------------------------------------------------------ *
 *  כיוון ב': מכמות בשלב אל הגיוסים                                     *
 * ------------------------------------------------------------------ */

check("60,000 הגשות מחזירות את הנתיב המוכר יחד עם החדש", () => {
  // התקלה שדווחה: התקבלו 1,923 גיוסים - רק המסלול החדש, בלי 1,418
  // האוכלוסייה המוכרת.
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const flow = sandbox.Engine.constrainedCombine(counts, null);
  const v = num(registry.heroValue.textContent);
  if (v !== flow.hires) return "המספר אינו תואם את המנוע: " + v;
  if (v < 3000 || v > 3600) return "מספר הגיוסים אינו סביר: " + v;
  if (flow.known.hires !== 1418) return "הנתיב המוכר אינו 1,418";
  if (flow.new.hires + flow.known.hires !== v) return "שני הנתיבים אינם מסתכמים";
  return null;
});

check("שני הכיוונים הם היפוך מדויק זה של זה", () => {
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  clearAll();
  setVal("submissions", String(plan.submissions));
  sandbox.calculate();
  const back = num(registry.heroValue.textContent);
  if (back !== 4000) return "החזרה נתנה " + back + " במקום 4,000";
  // וגם עם חלון זמן
  const p2 = sandbox.Engine.constrainedPlan(4000, 182);
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = p2.submissions;
  const f2 = sandbox.Engine.constrainedCombine(counts, 182);
  return Math.abs(f2.hires - 4000) <= 1
    ? null : "עם חלון זמן החזרה נתנה " + f2.hires;
});

check("כרטיס הזרימה מציג את שני הנתיבים ואת השרשרת", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  if (!shown("flowCard")) return "הכרטיס מוסתר";
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const flow = sandbox.Engine.constrainedCombine(counts, null);
  const rows = flowRows();
  if (rows.length !== flow.rows.length + flow.aside.length + flow.extra.length)
    return "מספר שורות שגוי: " + rows.length;
  const nums = rows.filter(r => !r.classList.contains("aside")).map(r => num(fval(r)));
  if (JSON.stringify(nums) !== JSON.stringify(flow.rows.map(r => r.total)))
    return "הכמויות אינן תואמות את המנוע";
  if (registry.flowLanes.children.length !== 3) return "אין שלוש תיבות";
  const missing = rows.filter(r => !hasInfo(r, 20));
  return missing.length ? missing.length + " שורות בלי מקור" : null;
});

check("שורת הזרימה מציגה את זמן ההגעה מתחת לכמות", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const rows = flowRows().filter(r => !r.classList.contains("source"));
  const withTime = rows.filter(r => {
    const v = r.children.filter(c => c.classList.contains("fval"))[0];
    return (v.children || []).some(c => c.tagName === "small" &&
                                        /[0-9]/.test(c.textContent));
  });
  return withTime.length >= rows.length - 1
    ? null : "רק " + withTime.length + " שורות נושאות זמן";
});

check("גזירה קדימה בלבד: שלב מוקדם אינו מופיע", () => {
  clearAll();
  setVal("yachbam", "5000");
  sandbox.calculate();
  const txt = allText(registry.flowBody);
  return !txt.includes("הגשות") && !txt.includes("בדיקת קבצים")
    ? null : "הופיע שלב מוקדם יותר";
});

check("תחנת צד שהוזנה מוצגת ראשונה ובלי המארח שלה", () => {
  clearAll();
  setVal("assessment", "1000");
  sandbox.calculate();
  const rows = flowRows();
  if (!rows.length) return "אין שורות";
  if (!rows[0].classList.contains("aside")) return "תחנת הצד אינה ראשונה";
  const txt = allText(registry.flowBody);
  return !txt.includes("יום מיון") ? null : "המארח הוצג למרות שהוא מוקדם יותר";
});

check("שלב שאינו בתזרים נקשר אליו ונאמר שכך נעשה", () => {
  clearAll();
  setVal("online_invite", "10000");
  sandbox.calculate();
  const rows = flowRows();
  if (!rows[0].classList.contains("source")) return "שורת הכניסה חסרה";
  if (num(fval(rows[0])) !== 10000) return "הכמות שהוזנה אינה מוצגת";
  const warned = registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("אינו מופיע בתזרים"));
  return warned ? null : "לא הוזהר שהשלב אינו בתזרים";
});

check("נפח קטן מקבל תשובה יחסית ולא את כל האוכלוסייה השנתית", () => {
  // התקלה שדווחה: 300 בדיקות קבצים החזירו 1,418 גיוסים - כל
  // האוכלוסייה השנתית הודבקה על 300 מועמדים.
  clearAll();
  setVal("file_check", "300");
  sandbox.calculate();
  const v = num(registry.heroValue.textContent);
  if (v !== 32) return "התקבלו " + v + " גיוסים במקום 32";
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.file_check = 300;
  const flow = sandbox.Engine.constrainedCombine(counts, null);
  if (flow.known.hires >= 20) return "הנתיב המוכר לא היה יחסי: " + flow.known.hires;
  if (Math.round(300 * sandbox.Engine.blendedRate("file_check")) !== v)
    return "המספר אינו הכמות כפול שיעור ההמרה המשוקלל";
  clearAll();
  setVal("yachbam", "500");
  sandbox.calculate();
  const y = num(registry.heroValue.textContent);
  return y === 402 ? null : "500 ביחב\"מ החזירו " + y + " במקום 402";
});

check("שיעור ההמרה המשוקלל מוזכר בהסבר", () => {
  clearAll();
  setVal("file_check", "300");
  sandbox.calculate();
  const t = infoOf(registry.flowLanes) + " " + infoOf(registry.flowInfo);
  const rate = pctOf(sandbox.Engine.blendedRate("file_check"));
  return t.includes(rate) ? null : "השיעור המשוקלל " + rate + " אינו מוזכר";
});

check("תאריך יעד בזרימה קדימה מקטין את המספר הגדול", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const full = sandbox.Engine.constrainedCombine(counts, null);
  if (num(registry.heroValue.textContent) !== full.hires)
    return "בלי תאריך המספר אינו מספר הגיוסים הכולל";

  setVal("targetDate", inDays(60));
  sandbox.calculate();
  const timed = sandbox.Engine.constrainedCombine(counts, 60);
  const got = num(registry.heroValue.textContent);
  if (got !== timed.hires_in_time) return "המספר אינו מה שנכנס בזמן: " + got;
  if (got >= timed.hires) return "התאריך לא הקטין את המספר";
  return registry.heroCap.textContent.includes("עד ") ? null : "אין תאריך בכותרת";
});

check("הרכיבים הוויזואליים חוזרים בכל מצב", () => {
  // התקלה שדווחה: כרטיסי הזמנים נעלמו, ונשאר משפך בלי פריסת זמן.
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const missing = ["flowCard", "whenCard", "matrixCard", "timelineCard"]
    .filter(id => !shown(id));
  if (missing.length) return "כרטיסים חסרים: " + missing.join(", ");
  // וגם כשמוזן תאריך יעד
  setVal("targetDate", inDays(27));
  sandbox.calculate();
  const missing2 = ["flowCard", "whenCard", "matrixCard", "timelineCard"]
    .filter(id => !shown(id));
  return missing2.length ? "עם תאריך יעד חסרים: " + missing2.join(", ") : null;
});

check("המשפך הוויזואלי מופיע גם עם תאריך יעד קצר", () => {
  // 4,000 ב-27 יום: המספר הראשי גדול, והמשפך חייב להופיע מתחתיו
  clearAll();
  setVal("target", "4000");
  setVal("targetDate", inDays(27));
  sandbox.calculate();
  if (!shown("constraintCard")) return "כרטיס המשפך מוסתר";
  const plan = sandbox.Engine.constrainedPlan(4000, 27);
  const rows = constraintRows();
  if (rows.length !== plan.rows.length + plan.aside.length)
    return "מספר שורות שגוי: " + rows.length;
  if (registry.constraintLanes.children.length !== 3) return "אין שלוש תיבות";
  // פס דו-צבעי בכל שורה בשרשרת
  const noBar = rows.filter(r => !r.classList.contains("aside")).filter(r => {
    const track = r.children.filter(c => c.classList.contains("ftrack"))[0];
    const bar = track && track.children[0];
    return !bar || !bar.classList.contains("split") || bar.children.length !== 2;
  });
  return noBar.length ? noBar.length + " שורות בלי פס דו-צבעי" : null;
});

check("הכמות והשורה הקטנה שמתחתיה הן שני אלמנטים", () => {
  // בדפדפן, אנימציית הספירה כותבת ל-textContent ומוחקת כל צאצא. אם
  // הזמן או הקצב יושבים באותו תא הם נמחקים תוך פחות משנייה.
  clearAll();
  setVal("target", "4000");
  setVal("targetDate", inDays(120));
  sandbox.calculate();
  const bad = constraintRows().filter(r => {
    const v = r.children.filter(c => c.classList.contains("fval"))[0];
    if (v.textContent) return true;           // המספר חייב לשבת ב-span
    const n = (v.children || []).filter(c => c.classList.contains("n"))[0];
    const sm = (v.children || []).filter(c => c.tagName === "small")[0];
    return !n || !sm;
  });
  return bad.length ? bad.length + " תאים שבהם הכמות והזמן באותו אלמנט" : null;
});

check("מתי יגיעו לכל שלב מציג שלב, כמות וימים", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const m = sandbox.Engine.constrainedMatrix(counts, null);
  const rows = registry.whenBody.children
    .filter(c => c.classList.contains("tl"))[0].children
    .filter(c => c.classList.contains("tlrow"));
  if (rows.length !== m.rows.length) return "מספר שורות שגוי: " + rows.length;
  const txt = allText(rows[0]);
  if (!txt.includes("מועמדים")) return "אין כמות בשורת הזמן";
  if (!/[0-9]/.test(txt)) return "אין ימים בשורת הזמן";
  // נקודה על ציר הזמן לכל שורה
  const noDot = rows.filter(r => {
    const track = r.children.filter(c => c.classList.contains("tltrack"))[0];
    return !track || track.children.length !== 2;
  });
  if (noDot.length) return noDot.length + " שורות בלי נקודה על הציר";
  const missing = rows.filter(r => !hasInfo(r, 20));
  return missing.length ? missing.length + " שורות בלי מקור" : null;
});

check("הטבלה האחת מסתכמת בדיוק", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const m = sandbox.Engine.constrainedMatrix(counts, null);
  const off = m.rows.filter(r => {
    let sum = 0;
    r.cells.forEach(c => { sum += c.count; });
    return sum !== r.count;
  });
  if (off.length) return off.length + " שורות שסכום החלונות בהן אינו הסך הכול";
  const rows = registry.matrixBody.children;
  // שורת כותרת אחת, ואז שורה אחת לכל שלב. שורות המלל אינן חוזרות.
  if (rows.length !== 1 + m.rows.length) return "מספר שורות לא צפוי: " + rows.length;
  const cols = m.buckets.length + 3;
  const bad = rows.filter((r, i) => i > 0 && r.children.length !== cols);
  if (bad.length) return bad.length + " שורות עם מספר עמודות שגוי";
  const missing = rows.filter((r, i) => i > 0 && !hasInfo(r, 20));
  return missing.length ? "יש שורה בלי מקור" : null;
});

check("הטבלה והמשפך מסכימים על אותן כמויות", () => {
  clearAll();
  setVal("file_check", "20000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.file_check = 20000;
  const flow = sandbox.Engine.constrainedCombine(counts, null);
  const m = sandbox.Engine.constrainedMatrix(counts, null);
  const byKey = {};
  m.rows.forEach(r => { byKey[r.key] = r.count; });
  const off = flow.rows.filter(r => !r.is_source &&
    byKey[r.key] !== undefined && byKey[r.key] !== r.total);
  return off.length ? "הטבלה והמשפך נפרדו ב«" + off[0].label + "»" : null;
});

check("חלונות שמאוחרים מתאריך היעד מסומנים בטבלה", () => {
  clearAll();
  setVal("submissions", "60000");
  setVal("targetDate", inDays(30));
  sandbox.calculate();
  const head = registry.matrixBody.children[0];
  const late = head.children.filter(c => c.classList.contains("late"));
  // החלונות "חודש עד חודשיים" ואילך מתחילים אחרי יום 30
  return late.length === 3 ? null : "סומנו " + late.length + " עמודות במקום 3";
});

check("מתי יתגייסו מוצג ומסתכם", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  if (!shown("timelineCard")) return "הכרטיס מוסתר";
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const tl = sandbox.Engine.constrainedTimeline(counts, null);
  const rows = registry.timelineBody.children[0].children;
  if (rows.length !== tl.rows.length) return "מספר חלונות שגוי";
  let sum = 0;
  tl.rows.forEach(r => { sum += r.hires; });
  if (sum !== tl.total) return "החלונות אינם מסתכמים";
  if (tl.total !== sandbox.Engine.constrainedCombine(counts, null).hires)
    return "הסכום אינו מספר הגיוסים";
  const missing = rows.filter(r => !hasInfo(r, 5));
  return missing.length ? missing.length + " חלונות בלי מקור" : null;
});

check("הנתיב המוכר מפוזר על פני הזמן ונאמר שכך", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const txt = infoOf(registry.timelineBody) + " " + infoOf(registry.timelineInfo);
  return txt.includes("אחיד") ? null : "לא נאמר שהנתיב הקבוע מתחלק אחיד";
});

/* ------------------------------------------------------------------ *
 *  יעד יחד עם שלבים                                                    *
 * ------------------------------------------------------------------ */

check("יעד עם מלאי קיים מציג כמה עוד צריך", () => {
  clearAll();
  setVal("submissions", "30000");
  setVal("target", "4000");
  sandbox.calculate();
  if (!shown("gapCardPlan")) return "כרטיס ההשלמה מוסתר";
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 30000;
  const plan = sandbox.Engine.constrainedGap(counts, 4000, null);
  const rows = registry.gapPlanBody.children.filter(r => !r.classList.contains("msg"));
  const nums = rows.map(r => num(fval(r)));
  if (JSON.stringify(nums) !== JSON.stringify(plan.rows.map(r => r.required)))
    return "הכמויות אינן תואמות את המנוע";
  const missing = rows.filter(r => !hasInfo(r, 20));
  if (missing.length) return missing.length + " שורות בלי מקור";
  // ההשלמה חייבת להיות קטנה מהדרישה המלאה
  const bare = sandbox.Engine.constrainedPlan(4000, null);
  return nums[0] < bare.submissions ? null : "המלאי הקיים לא הקטין את הדרישה";
});

check("כמה כבר בדרך נאמר במפורש", () => {
  clearAll();
  setVal("submissions", "30000");
  setVal("target", "4000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 30000;
  const plan = sandbox.Engine.constrainedGap(counts, 4000, null);
  const sub = registry.gapPlanSub.textContent;
  const fmt = n => n.toLocaleString("he-IL");
  return sub.includes(fmt(plan.have)) && sub.includes(fmt(plan.gap))
    ? null : "לא נאמר כמה כבר בדרך וכמה חסר: " + sub;
});

check("מה שכבר יש ועוד ההשלמה = הדרישה המלאה", () => {
  clearAll();
  setVal("submissions", "30000");
  setVal("target", "4000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 30000;
  const flow = sandbox.Engine.constrainedCombine(counts, null);
  const gap = sandbox.Engine.constrainedGap(counts, 4000, null);
  if (gap.have !== flow.hires) return "«כבר בדרך» אינו המספר שבכרטיס הזרימה";
  const off = gap.rows.filter(r => r.have + r.required !== r.needed_total);
  if (off.length) return "השורה של «" + off[0].label + "» אינה מסתכמת";
  // והזנת הסכום חזרה מחזירה בדיוק את היעד
  const back = {}; stageKeys.forEach(k => { back[k] = null; });
  back.submissions = 30000 + gap.rows[0].required;
  return sandbox.Engine.constrainedCombine(back, null).hires === 4000
    ? null : "הסכום אינו מחזיר את היעד";
});

check("יעד שכבר הושג אינו מבקש תוספת", () => {
  clearAll();
  setVal("submissions", "90000");
  setVal("target", "400");
  sandbox.calculate();
  return allText(registry.gapPlanBody).includes("אין צורך בתוספת")
    ? null : "לא נאמר שהיעד מושג";
});

check("יעד מול תחזית", () => {
  clearAll();
  setVal("submissions", "30000");
  setVal("target", "4000");
  sandbox.calculate();
  return registry.gapBody.children.some(c => c.textContent.includes("יעד הגיוס"))
    ? null : "אין הודעת יעד";
});

check("שתי קבוצות מזהירות מכפילות", () => {
  clearAll();
  setVal("file_check", "5000");
  setVal("yachbam", "3000");
  sandbox.calculate();
  return registry.gapBody.children.some(
    c => c.classList.contains("warn") && c.textContent.includes("נספרים פעמיים"))
    ? null : "אין אזהרת חפיפה";
});

/* ------------------------------------------------------------------ *
 *  כללי                                                               *
 * ------------------------------------------------------------------ */

check("אין טווחים בתצוגה", () => {
  const texts = [];
  clearAll();
  setVal("submissions", "60000");
  setVal("target", "3000");
  sandbox.calculate();
  texts.push(allText(registry.flowBody), allText(registry.flowLanes),
             allText(registry.timelineBody), allText(registry.gapBody),
             allText(registry.gapPlanBody), registry.heroNote.textContent);
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  texts.push(allText(registry.constraintBody), allText(registry.constraintLanes),
             registry.heroNote.textContent);
  const bad = texts.find(t => /\d\s*[-–]\s*\d/.test(t));
  return bad ? "נמצא טווח בתצוגה: " + bad.slice(0, 90) : null;
});

check("אין מלל באנגלית בשום מקום בתצוגה", () => {
  const nodes = ["heroCap", "heroNote", "constraintBody", "constraintLanes",
                 "flowBody", "flowLanes", "whenBody", "matrixBody",
                 "timelineBody", "gapBody", "gapPlanBody", "gapPlanSub",
                 "chartAllBody", "chartNewBody", "chartAllHead", "chartNewHead",
                 "unitBody", "unitGap", "importMsg",
                 "infoTitle", "infoText"];
  const btns = ["aboutBtn", "inputInfo", "heroInfo", "constraintInfo",
                "flowInfo", "whenInfo", "matrixInfo", "timelineInfo",
                "gapPlanInfo", "chartInfo", "importInfo", "unitInfo"];
  const scan = () => {
    let t = "";
    nodes.forEach(id => { t += " " + allText(at(id)) + " " + infoOf(at(id)); });
    btns.forEach(id => { t += " " + infoOf(at(id)); });
    const m = /[A-Za-z]+/.exec(t);
    return m ? m[0] : null;
  };
  clearAll();
  setVal("target", "4000");
  setVal("targetDate", inDays(150));
  sandbox.calculate();
  let bad = scan();
  if (bad) return "אנגלית במצב יעד: " + bad;
  clearAll();
  setVal("submissions", "60000");
  setVal("online_invite", "500");
  setVal("target", "3000");
  sandbox.calculate();
  bad = scan();
  return bad ? "אנגלית במצב זרימה: " + bad : null;
});

check("הסרגל הדביק מקבל את המספר ואת שמו", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const flow = sandbox.Engine.constrainedCombine(counts, null);
  if (num(registry.stickyValue.textContent) !== flow.hires) return "הסרגל לא עודכן";
  return registry.stickyLabel.textContent.includes("מגויסים")
    ? null : "הסרגל אינו אומר מה המספר";
});

check("כל שלב שאפשר להזין בו מחזיר תשובה", () => {
  const bad = [];
  withData.forEach(k => {
    clearAll();
    setVal(k, "20000");
    sandbox.calculate();
    if (!shown("results") || !shown("flowCard")) { bad.push(k + ": אין תוצאה"); return; }
    if (!/[0-9]/.test(registry.heroValue.textContent)) bad.push(k + ": אין מספר");
    if (!flowRows().length) bad.push(k + ": משפך ריק");
    if (flowRows().some(r => !hasInfo(r, 15))) bad.push(k + ": שורה בלי מקור");
  });
  return bad.length ? bad.join(" | ") : null;
});

check("יעד קטן מקבל נתיב מוכר יחסי ולא 1,418", () => {
  // התקלה שדווחה: יעד 400 החזיר 1,418 בכרטיס הכחול.
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(400, null);
  if (plan.known.hires !== 172) return "הנתיב המוכר הוא " + plan.known.hires;
  if (plan.new.hires !== 228) return "האוכלוסייה החדשה היא " + plan.new.hires;
  const v = heroSubs();
  if (v === 1418) return "הכרטיס הראשי עדיין מציג 1,418";
  if (v !== plan.submissions) return "הכרטיס אינו תואם את המנוע: " + v;
  // והחלק היחסי הוא 43%, בדיוק כמו בתרשים
  const lane = num(registry.constraintLanes.children[0].children[1].textContent);
  if (lane !== 172) return "התיבה מציגה " + lane;
  return num(registry.heroValue.textContent) === 400
    ? null : "הכרטיס הכחול אינו היעד";
});

check("אין התייחסות לזמן כשלא הוזן תאריך", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  if (registry.heroNote.textContent.indexOf("נותרו") !== -1)
    return "נשארה שורת זמן: " + registry.heroNote.textContent;
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  if (registry.heroNote.textContent !== "")
    return "נשארה שורת זמן בזרימה: " + registry.heroNote.textContent;
  // ועם תאריך היא כן חוזרת
  setVal("targetDate", inDays(90));
  sandbox.calculate();
  return registry.heroNote.textContent.includes("נותרו")
    ? null : "עם תאריך לא הוצג כמה זמן נשאר";
});

check("משפך הליך הגיוס מוצג בשתי עמודות", () => {
  const f = sandbox.Engine.flowFunnel();
  const a = registry.chartAllBody.children;
  const b = registry.chartNewBody.children;
  const expected = f.rows.length + f.aside.length;
  if (a.length !== expected) return "עמודה ראשונה: " + a.length + " שורות";
  if (b.length !== expected) return "עמודה שנייה: " + b.length + " שורות";
  if (registry.chartAllHead.textContent !== "כלל הגיוסים")
    return "כותרת שגויה בעמודה הראשונה: " + registry.chartAllHead.textContent;
  if (registry.chartNewHead.textContent !== "אוכלוסייה חדשה בלבד")
    return "כותרת שגויה בעמודה השנייה: " + registry.chartNewHead.textContent;
  // הכמויות הן התרשים עצמו
  const nums = a.filter(r => !r.classList.contains("aside")).map(r => num(fval(r)));
  if (JSON.stringify(nums) !== JSON.stringify(f.rows.map(r => r.all.count)))
    return "העמודה הראשונה אינה תואמת את התרשים";
  const nums2 = b.filter(r => !r.classList.contains("aside")).map(r => num(fval(r)));
  if (JSON.stringify(nums2) !== JSON.stringify(f.rows.map(r => r.new.count)))
    return "העמודה השנייה אינה תואמת את התרשים";
  const missing = a.concat(b).filter(r => !hasInfo(r, 20));
  return missing.length ? missing.length + " שורות בלי מקור" : null;
});

check("המשפך שבתחתית אינו משתנה עם מה שמוזן", () => {
  const before = allText(registry.chartAllBody);
  clearAll();
  setVal("target", "9999");
  sandbox.calculate();
  return allText(registry.chartAllBody) === before
    ? null : "המשפך ההיסטורי השתנה עם הקלט";
});

check("הכרטיס הכחול שווה לשורת הגיוס שבמשפך - בשני המצבים", () => {
  // התקלה שדווחה: הכרטיס הראשי אמר 106 והתיבה שמתחתיו 2,020.
  const hireOf = bodyId => {
    const rows = registry[bodyId].children.filter(r => r.classList.contains("hire"));
    return rows.length ? num(fval(rows[0])) : null;
  };
  clearAll();
  setVal("submissions", "60000");
  setVal("targetDate", inDays(26));
  sandbox.calculate();
  const hero = num(registry.heroValue.textContent);
  if (hireOf("flowBody") !== hero)
    return "זרימה עם תאריך: הכרטיס " + hero + " מול המשפך " + hireOf("flowBody");
  const lane = num(registry.flowLanes.children[2].children[1].textContent);
  if (lane !== hero) return "תיבת סך המגויסים היא " + lane + " ולא " + hero;
  const known = num(registry.flowLanes.children[0].children[1].textContent);
  const fresh = num(registry.flowLanes.children[1].children[1].textContent);
  if (known + fresh !== hero) return "שני הנתיבים אינם מסתכמים בכרטיס הראשי";

  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  if (hireOf("flowBody") !== num(registry.heroValue.textContent))
    return "זרימה בלי תאריך: הכרטיס אינו שווה למשפך";

  clearAll();
  setVal("target", "200");
  setVal("targetDate", inDays(26));
  sandbox.calculate();
  if (num(registry.heroValue.textContent) !== 200)
    return "מצב יעד: הכרטיס אינו מציג את היעד";
  if (hireOf("constraintBody") !== 200)
    return "מצב יעד: שורת הגיוס אינה היעד";
  return null;
});

check("עם תאריך, המשפך מציג רק את מה שנכנס בחלון", () => {
  clearAll();
  setVal("submissions", "60000");
  setVal("targetDate", inDays(26));
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const flow = sandbox.Engine.constrainedCombine(counts, 26);
  const rows = registry.flowBody.children.filter(r => !r.classList.contains("aside"));
  const nums = rows.map(r => num(fval(r)));
  const expected = flow.rows.map(r => r.total_in_time);
  if (JSON.stringify(nums) !== JSON.stringify(expected))
    return "המשפך אינו מוגבל לחלון: " + nums;
  // וכל שורה קטנה מהסך הכול העתידי, חוץ מנקודת הכניסה
  const bare = sandbox.Engine.constrainedCombine(counts, null);
  if (!(flow.rows[flow.rows.length - 1].total_in_time <
        bare.rows[bare.rows.length - 1].total))
    return "שורת הגיוס לא הצטמצמה";
  return infoOf(rows[1]).includes("מאוחרים מהתאריך")
    ? null : "לא נאמר שהשאר מאוחרים מהתאריך";
});

check("בלי תאריך המשפך מציג את הסך הכול", () => {
  clearAll();
  setVal("submissions", "60000");
  sandbox.calculate();
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.submissions = 60000;
  const flow = sandbox.Engine.constrainedCombine(counts, null);
  const nums = registry.flowBody.children
    .filter(r => !r.classList.contains("aside")).map(r => num(fval(r)));
  return JSON.stringify(nums) === JSON.stringify(flow.rows.map(r => r.total))
    ? null : "המשפך אינו מציג את הסך הכול";
});

check("במצב יעד המשפך גוזר לאחור בתוך החלון", () => {
  clearAll();
  setVal("target", "200");
  setVal("targetDate", inDays(26));
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(200, 26);
  const nums = registry.constraintBody.children
    .filter(r => !r.classList.contains("aside")).map(r => num(fval(r)));
  if (JSON.stringify(nums) !== JSON.stringify(plan.rows.map(r => r.total)))
    return "המשפך אינו תואם את התכנון";
  // כל שורה נגזרת מזו שמתחתיה לפי אחוז המעבר
  for (let i = 0; i < plan.rows.length - 1; i++) {
    const r = plan.rows[i];
    if (!r.rate_to_next) continue;
    const nextNew = plan.rows[i + 1].new;
    if (Math.abs(r.new * r.rate_to_next - nextNew) > 1.5)
      return "השרשרת אינה עקבית ב«" + r.label + "»";
  }
  return heroSubs() === plan.submissions ? null : "ההגשות אינן של החלון";
});

check("התיבה השלישית מציגה תמיד מספר גיוסים", () => {
  // התקלה שדווחה: ביעד 400 התיבה הציגה «הגשות דרושות 7,283».
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const box = registry.constraintLanes.children[2];
  if (num(box.children[1].textContent) !== 400)
    return "מצב יעד: התיבה מציגה " + box.children[1].textContent;
  if (!allText(box).includes("סך הגיוסים")) return "כותרת התיבה שגויה";
  // וכמות ההגשות נשארה מתחת למספר הראשי
  if (heroSubs() !== sandbox.Engine.constrainedPlan(400, null, false).submissions)
    return "כמות ההגשות נעלמה מהשורה שמתחת למספר";

  setVal("targetDate", inDays(60));
  sandbox.calculate();
  const timedBox = registry.constraintLanes.children[2];
  if (num(timedBox.children[1].textContent) !== 400)
    return "עם תאריך: התיבה מציגה " + timedBox.children[1].textContent;
  return allText(timedBox).includes("גיוסים עד התאריך")
    ? null : "כותרת התיבה עם תאריך שגויה";
});

check("בורר האוכלוסייה מחשב מחדש על המשפך השני", () => {
  clearAll();
  setVal("target", "400");
  sandbox.calculate();
  const all = heroSubs();
  if (all !== sandbox.Engine.constrainedPlan(400, null, false).submissions)
    return "ברירת המחדל אינה «כלל הגיוסים»";
  if (!registry.popAll.classList.contains("on")) return "הכפתור אינו מסומן";

  registry.popNew._on.click();
  const fresh = heroSubs();
  if (fresh !== sandbox.Engine.constrainedPlan(400, null, true).submissions)
    return "החישוב לא עבר למשפך של האוכלוסייה החדשה";
  if (!(fresh > all)) return "המשפך השני אמור לדרוש יותר הגשות";
  if (!registry.popNew.classList.contains("on")) return "הכפתור לא סומן";
  // אין אוכלוסייה מוכרת במצב הזה
  const known = num(registry.constraintLanes.children[0].children[1].textContent);
  if (known !== 0) return "הנתיב המוכר עדיין מופיע: " + known;

  registry.popAll._on.click();
  return heroSubs() === all ? null : "החזרה ל«כלל הגיוסים» לא עבדה";
});

check("הבורר משפיע גם על מצב הזרימה", () => {
  clearAll();
  setVal("file_check", "300");
  sandbox.calculate();
  const all = num(registry.heroValue.textContent);
  registry.popNew._on.click();
  const fresh = num(registry.heroValue.textContent);
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.file_check = 300;
  if (fresh !== sandbox.Engine.constrainedCombine(counts, null, true).hires)
    return "מצב הזרימה לא עבר למשפך השני";
  if (!(fresh < all)) return "בלי הנתיב המוכר אמורים להתקבל פחות גיוסים";
  registry.popAll._on.click();
  return num(registry.heroValue.textContent) === all ? null : "החזרה נכשלה";
});

check("כפתור יצירת הקשר צף ומקושר", () => {
  // כפתור סטטי, ולכן הוא נבדק בעמוד הבנוי עצמו ולא ב-DOM המזויף
  const m = /<a class="floatbtn"[\s\S]*?<\/a>/.exec(html);
  if (!m) return "אין כפתור צף בעמוד";
  const btn = m[0];
  if (!btn.includes("https://wa.me/97235555333")) return "הקישור שגוי";
  if (!btn.includes("צור קשר")) return "אין בועית «צור קשר»";
  if (!btn.includes("<svg")) return "אין אייקון";
  if (!/\.floatbtn\s*\{[^}]*position:\s*fixed/.test(html))
    return "הכפתור אינו צף";
  if (!/\.floatbtn\s*\{[^}]*z-index:\s*9999/.test(html))
    return "אין z-index";
  return /\.floatbtn\s*\{[^}]*#25d366/.test(html) ? null : "האייקון אינו ירוק";
});

/* ---------- טעינת קובץ המועמדים הפעילים ---------- */
const IMP = D.active_import;

/* טבלה מזויפת בצורת הקובץ: שורה ראשונה כותרות. */
function activeTable(rows) {
  const head = [IMP.columns.candidate[0], "דרישה", IMP.columns.status[0]];
  return [head].concat(rows.map(r => [r[0], "דרישה כלשהי", r[1]]));
}

check("המיפוי בא מהנתונים ולא מהקוד", () => {
  if (!IMP) return "אין active_import בנתונים";
  const keys = new Set(stageKeys);
  const bad = Object.keys(IMP.map).filter(s => !keys.has(IMP.map[s]));
  if (bad.length) return "סטטוס ממופה לשלב שאינו קיים: " + bad.join(", ");
  if (!IMP.ignore.length) return "אין רשימת סטטוסים להתעלמות";
  // התבנית היא הקוד עצמו, בלי הנתונים המוזרקים. סטטוס שמופיע בה
  // פירושו מיפוי שנכתב בקוד במקום להישאב מהקונפיג.
  const tpl = fs.readFileSync(path.join(ROOT, "web", "template.html"), "utf8");
  if (!tpl.includes("DATA.active_import")) return "המיפוי אינו נשאב מהנתונים";
  return tpl.includes("בבחינה") ? "המיפוי כתוב בקוד הממשק" : null;
});

check("קובץ מועמדים פעילים ממלא את השדות ומריץ חישוב", () => {
  sandbox.reset();
  const res = sandbox.applyActiveRows(activeTable([
    ["1", "בבחינה"], ["1", "בבחינה"], ["2", "בבחינה"],   // כפילות נספרת פעם אחת
    ["3", "קבצים"],
    ["4", "יום מיון"], ["5", "רפואי"],                    // שניהם יום מיון מקוון
    ["6", "מרכז הערכה"],
    ["7", "יחב\"מ"], ["8", "זימון לגיוס"], ["9", "גיוס"],
    ["10", IMP.ignore[0]],                                // אינו נספר
    ["11", "סטטוס שלא קיים"]                              // אינו מוכר
  ]));
  if (!res.ok) return "העמודות לא זוהו";
  const want = { submissions: 2, file_check: 1, online_day: 2,
                 assessment: 1, yachbam: 3 };
  const wrong = Object.keys(want)
    .filter(k => Number(registry["in_" + k].value) !== want[k]);
  if (wrong.length) return "שדה שלא מולא נכון: " + wrong.join(", ");
  if (registry.in_screening_day.value !== "" ||
      registry.in_online_invite.value !== "")
    return "שלב בלי סטטוס מקביל מולא בכל זאת";
  if (res.ignored !== 1) return "שורה בסטטוס להתעלמות נספרה";
  if (res.unknownRows !== 1) return "סטטוס לא מוכר לא דווח";
  if (!shown("results")) return "החישוב לא רץ אחרי הטעינה";
  const msg = allText(registry.importMsg);
  if (!msg.includes("מועמדים")) return "אין סיכום מתחת לכפתור";
  return msg.includes("סטטוס שלא קיים") ? null : "הסטטוס שלא זוהה לא נאמר";
});

check("הכמויות שנטענו הן אותן כמויות שהמחשבון מקבל", () => {
  sandbox.reset();
  sandbox.applyActiveRows(activeTable([
    ["1", "קבצים"], ["2", "קבצים"], ["3", "קבצים"], ["3", "קבצים"]
  ]));
  const counts = {}; stageKeys.forEach(k => { counts[k] = null; });
  counts.file_check = 3;
  const flow = sandbox.Engine.constrainedCombine(counts, null);
  return num(registry.stickyValue.textContent) === flow.hires
    ? null : "התוצאה אינה תואמת את מה שהוזן";
});

check("קובץ בלי העמודות הדרושות אינו שובר את העמוד", () => {
  sandbox.reset();
  const res = sandbox.applyActiveRows([["עמודה", "אחרת"], ["1", "2"]]);
  if (res.ok) return "עמודות שאינן קיימות זוהו";
  const msg = allText(registry.importMsg);
  if (!msg.trim()) return "לא נאמר למשתמש שהקובץ אינו מתאים";
  return stageKeys.every(k => registry["in_" + k].value === "")
    ? null : "שדה מולא למרות שהקובץ לא נקרא";
});

check("אין מלל באנגלית באזור הטעינה", () => {
  sandbox.reset();
  sandbox.applyActiveRows(activeTable([["1", "בבחינה"], ["2", "קבצים"]]));
  const t = allText(at("importMsg")) + " " + infoOf(at("importInfo"));
  const m = /[A-Za-z]+/.exec(t);
  return m ? "אנגלית באזור הטעינה: " + m[0] : null;
});

/* ---------- כל פורמט, ולא רק זה שנשלח ---------- */
const rowsOf = table => (table || []).length;

check("שורות שער מעל שורת הכותרות אינן מפריעות", () => {
  const t = [["דוח מועמדים פעילים", null], [], []]
    .concat(activeTable([["1", "בבחינה"], ["2", "קבצים"], ["3", "קבצים"]]));
  const res = sandbox.activeCounts(t);
  if (!res.ok) return "הכותרת לא נמצאה";
  return res.counts.submissions === 1 && res.counts.file_check === 2
    ? null : "הספירה שגויה: " + JSON.stringify(res.counts);
});

check("קובץ שנכתב לאורך נקרא כמו קובץ שנכתב לרוחב", () => {
  const t = activeTable([["1", "בבחינה"], ["2", "בבחינה"], ["3", "קבצים"]]);
  const flipped = t[0].map((_, c) => t.map(r => r[c]));
  const res = sandbox.activeCounts(flipped);
  if (!res.ok) return "הפריסה ההפוכה לא זוהתה";
  if (!res.flipped) return "לא נאמר שהקובץ נקרא הפוך";
  return res.counts.submissions === 2 && res.counts.file_check === 1
    ? null : "הספירה שגויה: " + JSON.stringify(res.counts);
});

check("טבלת ריכוז לפי עמודות", () => {
  const res = sandbox.activeCounts([
    ["תהליך נוכחי", "בבחינה", "קבצים", "מרכז הערכה"],
    ["סה\"כ", 2644, 825, 781]
  ]);
  if (!res.ok || res.mode !== "pivot") return "לא זוהתה טבלת ריכוז";
  return res.counts.submissions === 2644 && res.counts.file_check === 825 &&
         res.counts.assessment === 781
    ? null : "הכמויות שגויות: " + JSON.stringify(res.counts);
});

check("טבלת ריכוז לפי שורות", () => {
  const res = sandbox.activeCounts([
    ["תהליך נוכחי", "סה\"כ"],
    ["בבחינה", 2644], ["קבצים", 825],
    ["יום מיון", 637], ["רפואי", 332],
    [IMP.ignore[0], 9]
  ]);
  if (!res.ok || res.mode !== "pivot") return "לא זוהתה טבלת ריכוז";
  // שני סטטוסים שונים שמתמפים לאותו שלב חייבים להיסכם
  return res.counts.submissions === 2644 && res.counts.online_day === 969
    ? null : "הכמויות שגויות: " + JSON.stringify(res.counts);
});

check("שורת «סה\"כ» בתוך ריכוז אינה נספרת פעמיים", () => {
  const res = sandbox.activeCounts([
    ["יחידה ארגונית", "בבחינה", "קבצים", "סה\"כ"],
    ["מחוז א", 300, 100, 400],
    ["מחוז ב", 200, 80, 280],
    ["סה\"כ", 500, 180, 680]
  ]);
  if (res.counts.submissions !== 500) return "הסך הכול נספר פעמיים";
  const units = Object.keys(res.units);
  if (units.length !== 2) return "היחידות לא זוהו: " + units.join(", ");
  return res.units["מחוז א"].file_check === 100 ? null : "פילוח שגוי";
});

check("שם עמודה אחר מתקבל", () => {
  const res = sandbox.activeCounts([
    ["מספר מועמד", "סטטוס", "מחוז"],
    ["1", "בבחינה", "צפון"], ["2", "קבצים", "דרום"], ["2", "קבצים", "דרום"]
  ]);
  if (!res.ok) return "העמודות לא זוהו";
  if (res.counts.file_check !== 1) return "כפילות נספרה פעמיים";
  return Object.keys(res.units).length === 2 ? null : "עמודת המחוז לא זוהתה";
});

check("עמודת סטטוס לבדה מספיקה", () => {
  const res = sandbox.activeCounts([
    ["תהליך נוכחי"], ["בבחינה"], ["בבחינה"], ["קבצים"]
  ]);
  if (!res.ok) return "לא זוהתה עמודת הסטטוס";
  if (res.dedup) return "נטען שיש ניכוי כפילויות בלי עמודת מועמד";
  return res.counts.submissions === 2 && res.counts.file_check === 1
    ? null : "הספירה שגויה: " + JSON.stringify(res.counts);
});

check("קובץ שאין בו שום שלב אינו נקרא", () => {
  const res = sandbox.activeCounts([["שם", "עיר"], ["דנה", "חיפה"]]);
  return res.ok ? "קובץ לא רלוונטי זוהה כטבלת מועמדים" : null;
});

/* ---------- טבלת היחידות ---------- */
check("טבלת היחידות נבנית, מסתכמת, ומופיעה רק כשיש יחידה", () => {
  sandbox.reset();
  sandbox.applyActiveRows(activeTable([["1", "בבחינה"], ["2", "קבצים"]]));
  if (revealed("unitCard") || !registry.unitCard.classList.contains("hidden"))
    return "הטבלה הופיעה בלי עמודת יחידה";

  sandbox.reset();
  const head = ["מועמד(קוד)", "תהליך נוכחי", "יחידה ארגונית"];
  const body = [];
  for (let i = 0; i < 400; i++) body.push([String(i), "בבחינה", "מחוז א"]);
  for (let i = 400; i < 600; i++) body.push([String(i), "קבצים", "מחוז ב"]);
  sandbox.applyActiveRows([head].concat(body));
  if (registry.unitCard.classList.contains("hidden")) return "הטבלה לא הופיעה";

  const rows = registry.unitBody.children;
  if (rows.length !== 4) return "מספר שורות לא צפוי: " + rows.length;
  // עמודות: צבע | יחידה | פעילים | מגויסים | חלק
  const cells = r => (rows[r].children || []).map(c => c.textContent);
  const sumRow = cells(3);
  const a = num(cells(1)[3]), b = num(cells(2)[3]);
  if (num(sumRow[2]) !== 600) return "סך המועמדים הפעילים שגוי";
  if (num(sumRow[3]) !== a + b) return "שורת הסך הכול אינה סכום השורות";
  // הטבעת נבנית מאותם נתונים
  const svg = registry.unitDonut.innerHTML;
  if (!/<svg/.test(svg)) return "אין טבעת";
  if ((svg.match(/<path/g) || []).length !== 2) return "מספר הפרוסות שגוי";
  if (registry.unitLegend.children.length !== 2) return "אין מקרא לשתי היחידות";
  return null;
});

check("יחידה קטנה מ-5% מתאחדת ל«אחר»", () => {
  sandbox.reset();
  const head = ["מועמד(קוד)", "תהליך נוכחי", "י.ארגונית מחוזית"];
  const body = [];
  for (let i = 0; i < 500; i++) body.push([String(i), "יחב\"מ", "מחוז גדול"]);
  for (let i = 500; i < 510; i++) body.push([String(i), "יחב\"מ", "מחוז קטן א"]);
  for (let i = 510; i < 520; i++) body.push([String(i), "יחב\"מ", "מחוז קטן ב"]);
  sandbox.applyActiveRows([head].concat(body));
  const rows = registry.unitBody.children;
  if (rows.length !== 5) return "הטבלה חייבת להציג את כל היחידות: " + rows.length;
  const legend = registry.unitLegend.children.map(c =>
    (c.children || []).map(x => x.textContent).join(" "));
  if (legend.length !== 2) return "המקרא חייב להיות מחוז אחד ועוד «אחר»";
  return /אחר/.test(legend[1]) ? null : "הקטנות לא אוחדו: " + legend.join(" | ");
});

check("טבלת היחידות משתנה עם בורר האוכלוסייה", () => {
  sandbox.reset();
  const head = ["מועמד(קוד)", "תהליך נוכחי", "י.ארגונית מחוזית"];
  const body = [];
  for (let i = 0; i < 400; i++) body.push([String(i), "בבחינה", "מחוז א"]);
  for (let i = 400; i < 600; i++) body.push([String(i), "קבצים", "מחוז ב"]);
  sandbox.applyActiveRows([head].concat(body));
  const sumCell = () => {
    const rows = registry.unitBody.children;
    return num((rows[rows.length - 1].children || [])[3].textContent);
  };
  const before = sumCell();
  sandbox.setPopulation(true);
  const after = sumCell();
  sandbox.setPopulation(false);
  return after < before ? null :
    "«גיוסים חדשים בלבד» חייב לתת פחות גיוסים מאותו מלאי";
});

check("הפרש העיגול נאמר במפורש", () => {
  const t = registry.unitGap.textContent;
  if (!t) return null;   // אין הפרש - אין מה לומר
  return t.includes("עיגול") ? null : "ההפרש לא הוסבר";
});

check("איפוס מנקה גם את טבלת היחידות", () => {
  sandbox.reset();
  clearAll();
  setVal("submissions", "5000");
  sandbox.calculate();
  return registry.unitCard.classList.contains("hidden")
    ? null : "טבלת היחידות נשארה אחרי איפוס";
});

check("מספרים כטקסט, עם פסיקים ועם רווחים, נקראים", () => {
  const res = sandbox.activeCounts([
    ["תהליך נוכחי", "סה\"כ"],
    ["בבחינה", "2,644"], ["קבצים", " 825 "], ["מרכז הערכה", "781"]
  ]);
  if (!res.ok) return "הטבלה לא זוהתה";
  return res.counts.submissions === 2644 && res.counts.file_check === 825 &&
         res.counts.assessment === 781
    ? null : "המספרים לא נקראו: " + JSON.stringify(res.counts);
});

check("שם עמודה עם רווחים ומירכאות חריגות מזוהה", () => {
  const res = sandbox.activeCounts([
    ["  מועמד (קוד)  ", " תהליך נוכחי "],
    ["1", " בבחינה "], ["2", "יחב״מ"]
  ]);
  if (!res.ok) return "העמודות לא זוהו";
  return res.counts.submissions === 1 && res.counts.yachbam === 1
    ? null : "הערכים לא נוקו: " + JSON.stringify(res.counts);
});

check("טעינה שנכשלה מחזירה את השדות בדיוק למצב הקודם", () => {
  sandbox.reset();
  clearAll();
  setVal("submissions", "1234");
  setVal("target", "400");
  sandbox.calculate();
  const snap = sandbox.snapshotInputs();
  setVal("submissions", "9999");
  setVal("target", "");
  sandbox.restoreInputs(snap);
  if (registry.in_submissions.value !== "1234") return "השלב לא הוחזר";
  if (registry.in_target.value !== "400") return "היעד לא הוחזר";
  return shown("results") ? null : "התוצאות לא חזרו";
});

check("קובץ פגום אינו נוגע בשדות", () => {
  sandbox.reset();
  clearAll();
  setVal("file_check", "500");
  sandbox.calculate();
  sandbox.applyActiveRows([["שם", "עיר"], ["דנה", "חיפה"]]);
  return registry.in_file_check.value === "500"
    ? null : "שדה השתנה למרות שהקובץ לא נקרא";
});

check("מסלול השגיאה קיים ומעוצב", () => {
  if (!/function failImport/.test(script)) return "אין מסלול כישלון";
  if (!/restoreInputs\(snap\)/.test(script)) return "אין שחזור מצב";
  if (!/openAlert\(/.test(script)) return "אין חלון שגיאה";
  if (!/\.modal\.alert \.sheet/.test(html)) return "לחלון השגיאה אין עיצוב";
  if (!/expandMerges\(sheet\);[\s\S]{0,200}sheet_to_json/.test(script))
    return "תאים ממוזגים אינם מורחבים לפני הקריאה";
  return /פורמט הקובץ אינו נתמך/.test(script) ? null : "אין הסבר לפורמט לא נתמך";
});

check("איפוס מנקה גם את הטעינה", () => {
  sandbox.applyActiveRows(activeTable([["1", "בבחינה"]]));
  sandbox.reset();
  return allText(registry.importMsg).trim() === "" &&
         registry.importFile.value === ""
    ? null : "האיפוס השאיר את סיכום הטעינה";
});

check("הכותרת ובורר האוכלוסייה ממורכזים", () => {
  if (!/<div class="card head">/.test(html)) return "כרטיס הכותרת אינו מסומן";
  if (!/\.card\.head\s*\{[^}]*text-align:\s*center/.test(html))
    return "הכותרת אינה ממורכזת";
  return /\.card\.head \.titlerow\s*\{[^}]*justify-content:\s*center/.test(html)
    ? null : "שורת הכותרת אינה ממורכזת";
});

check("התאמה לנייד", () => {
  if (!/viewport-fit=cover/.test(html)) return "אין viewport-fit באייפון";
  if (!/env\(safe-area-inset-bottom\)/.test(html))
    return "הכפתור הצף אינו מתחשב באזור הבטוח";
  if (!/@media \(max-width: 680px\)[\s\S]*?\.import button\.load/.test(html))
    return "כפתור הטעינה לא הותאם למסך צר";
  if (!/@media \(max-width: 680px\)[\s\S]*?\.segbar button \{[^}]*flex:\s*1/.test(html))
    return "בורר האוכלוסייה לא הותאם למסך צר";
  if (!/\.unitwrap\s*\{[^}]*overflow:\s*auto/.test(html))
    return "טבלת היחידות אינה נגללת בתוך עצמה";
  // שדות הקלט נשארים 16px כדי שהאייפון לא יבצע זום בלחיצה
  return /font-size:\s*16px/.test(html) ? null : "שדה קלט קטן מ-16px בנייד";
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
