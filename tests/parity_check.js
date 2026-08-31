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
  if (sc.op === "rate") {
    results.push(Engine.rate(sc.stage));
  } else if (sc.op === "forward") {
    results.push(Engine.forward(sc.stage));
  } else if (sc.op === "project_cohort") {
    results.push(Engine.projectCohort(sc.stage, sc.count));
  } else if (sc.op === "timeline") {
    results.push(Engine.timeline(sc.stage, sc.count));
  } else if (sc.op === "combine") {
    results.push(Engine.combine(sc.counts));
  } else if (sc.op === "curve_share") {
    results.push(Engine.curveShare(sc.stage, sc.days));
  } else if (sc.op === "hires_by_day") {
    results.push(Engine.hiresByDay(sc.stage, sc.count, sc.days));
  } else if (sc.op === "combined_by_day") {
    results.push(Engine.combinedByDay(sc.counts, sc.days));
  } else if (sc.op === "combined_when") {
    results.push(Engine.combinedWhen(sc.counts));
  } else if (sc.op === "combined_timeline") {
    results.push(Engine.combinedTimeline(sc.counts));
  } else if (sc.op === "lead_time_anomalies") {
    results.push(Engine.leadTimeAnomalies());
  } else if (sc.op === "gap_plan") {
    results.push(Engine.gapPlan(sc.counts, sc.target, sc.days));
  } else if (sc.op === "gap_pipeline") {
    results.push(Engine.gapPipeline(sc.counts, sc.target, sc.stage, sc.days));
  } else if (sc.op === "required_plan") {
    results.push(Engine.requiredPlan(sc.target));
  } else if (sc.op === "plan_from_target") {
    results.push(Engine.planFromTarget(sc.stage, sc.target));
  } else if (sc.op === "cross_check") {
    results.push(Engine.crossCheck(sc.counts));
  } else if (sc.op === "required_for_target") {
    results.push(Engine.requiredForTarget(sc.stage, sc.target));
  } else if (sc.op === "required_funnel") {
    results.push(Engine.requiredFunnel(sc.target));
  } else if (sc.op === "target_verdict") {
    results.push(Engine.targetVerdict(sc.projected, sc.target));
  } else if (sc.op === "label") {
    results.push(Engine.label(sc.stage));
  } else {
    console.error("unknown op: " + sc.op);
    process.exit(1);
  }
}

process.stdout.write(JSON.stringify(results));
