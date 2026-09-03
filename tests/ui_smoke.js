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
const hasInfo = (row, min) => infoOf(row).trim().length > (min || 10);
const fval = row => {
  const v = (row.children || []).filter(c => c.classList.contains("fval"))[0];
  return v ? v.textContent : "";
};
const inDays = n => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
         "-" + String(d.getDate()).padStart(2, "0");
};

check("שדות הקלט נבנו", () =>
  stageKeys.every(k => registry["in_" + k]) && registry.in_target ? null : "חסר שדה קלט");

check("ההסבר הכללי יושב בחלון ולא בעמוד", () => {
  const t = infoOf(registry.aboutBtn);
  if (t.length < 400) return "ההסבר הכללי קצר מדי או חסר";
  return t.includes("מגבלות") ? null : "אין מגבלות בהסבר הכללי";
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
  const missing = registry.funnelBody.children.filter(r => !hasInfo(r, 3));
  return missing.length ? missing.length + " שורות בלי מקור" : null;
});

check("שורת המשפך מציגה שם וכמות בלבד", () => {
  // שם השלב (עם ⓘ ואחוז), פס, כמות. שורת מלל רביעית אינה קיימת עוד.
  clearAll();
  setVal("file_check", "5000");
  sandbox.calculate();
  const bad = registry.funnelBody.children.filter(r => r.children.length !== 3);
  if (bad.length) return bad.length + " שורות עם יותר משלושה חלקים";
  const prose = registry.funnelBody.children.filter(r =>
    (r.children || []).some(c => c.classList.contains("fsrc")));
  return prose.length ? "נשאר מלל בגוף השורה" : null;
});

check("אין גזירה לאחור", () => {
  clearAll();
  setVal("yachbam", "300");
  sandbox.calculate();
  const text = allText(registry.funnelBody);
  // בדיקת קבצים קודמת ליחב"מ ולכן אסור שתופיע עם מספר גזור
  const proj = sandbox.Engine.projectCohort("yachbam", 300);
  const keys = proj.steps.map(s => s.key);
  return keys.indexOf("file_check") === -1 && !text.includes("בדיקת קבצים ")
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
  const txt = infoOf(hire);
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
  const missing = rows.filter(r => !hasInfo(r, 3));
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

/* ------------------------------------------------------------------ *
 *  מצב תכנון מיעד. התשובה היחידה היא המחשבון עם האילוצים.              *
 * ------------------------------------------------------------------ */
const constraintRows = () => registry.constraintBody.children;

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
  if (!shown("constraintCard")) return "המחשבון עם האילוצים מוסתר";
  if (shown("whenCard")) return "גרף הזמנים היה צריך להיות מוסתר";
  if (shown("timelineCard")) return "גרף ההתפלגות היה צריך להיות מוסתר";
  return null;
});

check("במצב יעד מוצגת תשובה אחת בלבד", () => {
  // התקלה שדווחה: העמוד הציג שלוש תשובות שונות לאותה שאלה, ואחת מהן
  // (61,359 הגשות) הכפילה גם את הנתיב המוכר - מה שאינו אפשרי.
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const open = ["heroCard", "constraintCard", "gapCardPlan", "funnelCard",
                "matrixCard", "whenCard", "timelineCard"].filter(shown);
  return JSON.stringify(open) === JSON.stringify(["heroCard", "constraintCard"])
    ? null : "הוצגו כרטיסים נוספים: " + open.join(", ");
});

check("המשפך עם האילוצים מציג את כל השרשרת ואת תחנת הצד", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  if (!shown("constraintCard")) return "הכרטיס מוסתר";
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  const rows = constraintRows();
  if (rows.length !== plan.rows.length + plan.aside.length)
    return "מספר שורות שגוי: " + rows.length;
  // מרכז הערכה מסומן כתחנת צד ואינו בשרשרת
  const asideRows = rows.filter(r => r.classList.contains("aside"));
  if (asideRows.length !== plan.aside.length)
    return "מרכז הערכה אינו מסומן כתחנת צד";
  if (!infoOf(asideRows[0]).includes("לא בשרשרת"))
    return "תחנת הצד אינה אומרת שהיא מחוץ לשרשרת";
  return null;
});

check("הכמויות במשפך האילוצים תואמות את המנוע", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  const shownNums = constraintRows()
    .filter(r => !r.classList.contains("aside"))
    .map(r => num(fval(r)));
  const expected = plan.rows.map(r => r.total);
  return JSON.stringify(shownNums) === JSON.stringify(expected)
    ? null : "הכמויות אינן תואמות: " + shownNums;
});

check("כל שורה במשפך האילוצים אומרת ממה היא נגזרה", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const missing = constraintRows().filter(r => !hasInfo(r, 20));
  if (missing.length) return missing.length + " שורות בלי מקור";
  const txt = infoOf(constraintRows()[0]);
  if (!txt.includes("אוכלוסייה מוכרת") || !txt.includes("אוכלוסייה חדשה"))
    return "שורת ההגשות אינה מפרידה בין שני הנתיבים";
  return null;
});

check("שורת האילוצים מציגה שם, אחוז מעבר וכמות בלבד", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const bad = constraintRows().filter(r => r.children.length !== 3);
  if (bad.length) return bad.length + " שורות עם יותר משלושה חלקים";
  // שורה שנייה ואילך נושאת את אחוז המעבר מהשלב הקודם
  const second = constraintRows()[1];
  const chip = second.children[0].children.filter(c => c.classList.contains("fpct"))[0];
  if (!chip || !chip.textContent.includes("%")) return "אין אחוז מעבר בשורה";
  const plan = sandbox.Engine.constrainedPlan(4000, null);
  return chip.textContent.indexOf((plan.rows[0].rate_to_next * 100).toFixed(1)) === 0
    ? null : "אחוז המעבר אינו של השלב הקודם: " + chip.textContent;
});

check("ההגשות הדרושות ל-4,000 הן כ-82 אלף", () => {
  // התיקון שהתבקש: מודל האילוצים, שאינו מכפיל את הנתיב המוכר, ולא
  // ההכפלה הרוחבית שנתנה 61,359.
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const v = num(registry.heroValue.textContent);
  if (v !== sandbox.Engine.constrainedPlan(4000, null).submissions)
    return "המספר אינו של מודל האילוצים: " + v;
  if (v < 70000 || v > 95000)
    return "כמות ההגשות ל-4,000 גיוסים אינה סבירה: " + v;
  const thr = sandbox.Engine.throughputPlan(4000, null);
  const thrSub = thr.rows.filter(r => r.key === "submissions")[0].required;
  return v !== thrSub ? null : "המספר הוא של ההכפלה הרוחבית";
});

check("אין נתוני אמת גולמיים בגוף העמוד", () => {
  // «נמדד בפועל» והמספרים ההיסטוריים ירדו מהעמוד. הם קיימים בחלון
  // ההסבר בלבד.
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

check("תאריך יעד משנה את הכמות ולא רק את התאריך", () => {
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  const annual = num(registry.heroValue.textContent);
  setVal("targetDate", inDays(180));
  sandbox.calculate();
  const half = num(registry.heroValue.textContent);
  if (half === annual) return "התאריך לא שינה את הכמות";
  const cp = sandbox.Engine.constrainedPlan(4000, 180);
  if (half !== cp.submissions) return "הכמות אינה תואמת את המנוע";
  // חצי שנה ליעד שנתי דורשת יותר הגשות, לא פחות: הנתיב המוכר תורם מחצית
  return half > annual ? null : "חלון קצר לא הגדיל את הדרישה: " + half;
});

check("יעד קטן מהנתיב המוכר אינו דורש הגשות", () => {
  clearAll();
  const known = sandbox.Engine.constrainedPlan(4000, null).known.hires;
  setVal("target", String(Math.max(1, known - 100)));
  sandbox.calculate();
  const plan = sandbox.Engine.constrainedPlan(known - 100, null);
  if (!plan.shortfall) return "התרחיש אינו מתאים";
  return infoOf(registry.constraintInfo).includes("בלי אף הגשה")
    ? null : "לא נאמר שהיעד מושג בלי הגשות";
});

check("תאריך יעד מופיע בכותרת המשנה", () => {
  clearAll();
  setVal("target", "400");
  setVal("targetDate", inDays(200));
  sandbox.calculate();
  const t = registry.heroNote.textContent;
  return /\d{4}/.test(t) && t.includes("ימים") ? null : "אין תאריך בכותרת: " + t;
});

check("אין מלל באנגלית בשום מקום בתצוגה", () => {
  // דרישה מפורשת: ללא מלל או מושגים באנגלית בכלל.
  const nodes = ["heroCap", "heroNote", "constraintBody", "constraintLanes",
                 "funnelBody", "whenBody", "timelineBody", "matrixBody",
                 "gapBody", "gapPlanBody", "gapPipeBody", "gapPlanSub",
                 "infoTitle", "infoText"];
  const scan = () => {
    let t = "";
    const at = id => registry[id] || { children: [], attributes: {} };
    nodes.forEach(id => { t += " " + allText(at(id)) + " " + infoOf(at(id)); });
    ["aboutBtn", "inputInfo", "heroInfo", "constraintInfo", "funnelInfo",
     "matrixInfo", "whenInfo", "timelineInfo", "gapPlanInfo"].forEach(id => {
       t += " " + infoOf(at(id));
     });
    const m = /[A-Za-z]+/.exec(t);
    return m ? m[0] : null;
  };
  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  let bad = scan();
  if (bad) return "אנגלית במצב יעד: " + bad;
  clearAll();
  setVal("file_check", "5000");
  setVal("target", "300");
  setVal("targetDate", inDays(120));
  sandbox.calculate();
  bad = scan();
  return bad ? "אנגלית במצב גזירה: " + bad : null;
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

check("שלב עם כיסוי נמוך מפיק אזהרה מפורשת", () => {
  clearAll();
  setVal("submissions", "35711");
  sandbox.calculate();
  const low = sandbox.Engine.lowCoverage(["submissions"]);
  if (!low.length) return "ההגשות לא סומנו ככיסוי נמוך";
  const warned = registry.gapBody.children.some(
    c => c.classList.contains("warn") &&
         c.textContent.includes("נרשמו בכלל") &&
         c.textContent.includes("הגשות"));
  return warned ? null : "לא הוצגה אזהרת כיסוי";
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
  // שורת כותרת אחת, ואז שורה אחת לכל שלב. שורות המלל ירדו.
  if (rows.length !== 1 + m.rows.length) return "מספר שורות לא צפוי: " + rows.length;
  const missing = rows.filter((r, i) => i > 0 && !hasInfo(r, 20));
  return missing.length ? "יש שורה בלי מקור" : null;
});

check("אין טווחים בתצוגה", () => {
  const texts = [];
  clearAll();
  setVal("file_check", "5000");
  setVal("target", "300");
  sandbox.calculate();
  texts.push(registry.heroValue.textContent, allText(registry.funnelBody),
             allText(registry.whenBody), allText(registry.timelineBody),
             allText(registry.gapBody), allText(registry.gapPlanBody));

  clearAll();
  setVal("target", "4000");
  sandbox.calculate();
  texts.push(allText(registry.constraintBody), allText(registry.constraintLanes),
             registry.heroNote.textContent);

  const bad = texts.find(t => /\d\s*[-–]\s*\d/.test(t));
  return bad ? "נמצא טווח בתצוגה: " + bad.slice(0, 90) : null;
});

check("הסרגל הדביק מקבל את המספר", () => {
  clearAll();
  setVal("file_check", "5000");
  sandbox.calculate();
  const hires = sandbox.Engine.projectCohort("file_check", 5000).hires;
  if (num(registry.stickyValue.textContent) !== hires) return "הסרגל לא עודכן";
  return registry.stickyLabel.textContent.includes("מגויסים")
    ? null : "הסרגל אינו אומר מה המספר";
});

check("תאריך יעד בזרימה קדימה מקטין את המספר הגדול", () => {
  clearAll();
  setVal("file_check", "1000");
  sandbox.calculate();
  const eventual = sandbox.Engine.projectCohort("file_check", 1000).hires;
  if (num(registry.heroValue.textContent) !== eventual)
    return "בלי תאריך המספר אינו מספר הגיוסים הכולל";

  setVal("targetDate", inDays(30));
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
  setVal("targetDate", inDays(30));
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
  setVal("targetDate", inDays(30));
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
  const nums = rows.map(r => num(fval(r)));
  const expected = plan.rows.filter(r => r.has_data).map(r => r.required);
  if (JSON.stringify(nums) !== JSON.stringify(expected))
    return "הכמויות אינן תואמות את המנוע";
  const missing = rows.filter(r => !hasInfo(r, 20));
  if (missing.length) return missing.length + " שורות בלי מקור";
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
  setVal("targetDate", inDays(10));
  sandbox.calculate();
  const rows = registry.gapPlanBody.children.filter(r => r.classList.contains("nodata"));
  if (!rows.length) return "אף שלב לא סומן כלא מספיק";
  if (fval(rows[0]) !== "לא יספיק") return "אין סימון בשורה: " + fval(rows[0]);
  return infoOf(rows[0]).includes("לא יספיק") ? null : "אין הסבר לסימון";
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
