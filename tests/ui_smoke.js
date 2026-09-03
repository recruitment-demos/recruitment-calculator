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
  if (num(registry.heroValue.textContent) !== cp.submissions)
    return "ההגשות הדרושות לא הוצגו: " + registry.heroValue.textContent;
  if (!registry.heroCap.textContent.includes("400")) return "היעד לא נזכר";
  if (!registry.heroCap.textContent.includes("הגשות")) return "כותרת שגויה";
  return shown("constraintCard") ? null : "המחשבון עם האילוצים מוסתר";
});

check("במצב יעד מוצגת תשובה אחת בלבד", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const open = ["heroCard", "constraintCard", "flowCard", "gapCardPlan",
                "whenCard", "matrixCard", "timelineCard"].filter(shown);
  return JSON.stringify(open) === JSON.stringify(["heroCard", "constraintCard"])
    ? null : "הוצגו כרטיסים נוספים: " + open.join(", ");
});

check("ההגשות הדרושות ל-4,000 הן כ-82 אלף", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const v = num(registry.heroValue.textContent);
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
  const annual = num(registry.heroValue.textContent);
  setVal("targetDate", inDays(180));
  sandbox.calculate();
  const half = num(registry.heroValue.textContent);
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
  return /\d{4}/.test(t) ? null : "אין תאריך בכותרת: " + t;
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
  if (num(registry.heroValue.textContent) !==
      sandbox.Engine.constrainedPlan(4000, null).submissions)
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
                 "infoTitle", "infoText"];
  const btns = ["aboutBtn", "inputInfo", "heroInfo", "constraintInfo",
                "flowInfo", "whenInfo", "matrixInfo", "timelineInfo",
                "gapPlanInfo"];
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
