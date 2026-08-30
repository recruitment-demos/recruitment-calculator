/*
 * מריץ את מנוע החישוב של הדפדפן מחוץ לדפדפן, ומדפיס את תוצאות התרחישים
 * כ-JSON. tests/test_parity.py משווה את הפלט הזה לפלט של recruit_calc/engine.py.
 *
 * קוד המנוע נשלף מ-web/template.html עצמו, כדי שהבדיקה תרוץ תמיד על הקוד
 * האמיתי ולא על עותק שעלול להתיישן.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const template = fs.readFileSync(path.join(ROOT, "web", "template.html"), "utf8");
const DATA = JSON.parse(
  fs.readFileSync(path.join(ROOT, "data", "recruitment_data.json"), "utf8")
);

const START = "/* __ENGINE_START__ */";
const END = "/* __ENGINE_END__ */";
const from = template.indexOf(START);
const to = template.indexOf(END);
if (from === -1 || to === -1) {
  console.error("לא נמצאו סימני המנוע ב-web/template.html");
  process.exit(1);
}
const engineSource = template.slice(from + START.length, to);

// eslint-disable-next-line no-new-func
const Engine = new Function("DATA", engineSource + "\nreturn Engine;")(DATA);

const scenarios = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const results = [];

for (const sc of scenarios) {
  if (sc.op === "project_hires") {
    results.push(Engine.asDict(Engine.projectHires(sc.stage, sc.count)));
  } else if (sc.op === "required_for_target") {
    results.push(Engine.asDict(Engine.requiredForTarget(sc.stage, sc.target)));
  } else if (sc.op === "convert") {
    results.push(Engine.asDict(Engine.convert(sc.from, sc.count, sc.to)));
  } else if (sc.op === "fill_from") {
    results.push(Engine.fillFrom(sc.stage, sc.count));
  } else if (sc.op === "timeline") {
    const rows = Engine.timeline(sc.stage, sc.count);
    results.push(
      rows === null
        ? null
        : rows.map(r => ({
            key: r.key,
            label: r.label,
            share: r.share,
            hires: Engine.asDict(r.hires)
          }))
    );
  } else if (sc.op === "gap_analysis") {
    results.push(Engine.gapAnalysis(sc.counts, sc.target));
  } else {
    console.error("פעולה לא מוכרת: " + sc.op);
    process.exit(1);
  }
}

process.stdout.write(JSON.stringify(results));
