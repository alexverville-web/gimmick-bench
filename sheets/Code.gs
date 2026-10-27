/**
 * Gimmick Bench result collector (Google Apps Script, bound to the studio Sheet).
 *
 * - doPost receives one raw result from a benchmarked computer, stores the full
 *   JSON as a file in Drive (raw data is never lost or truncated), and adds
 *   human-readable rows to the "Runs" and "Tests" tabs.
 * - doGet returns every stored raw result, for the dashboard and the scoring engine.
 *
 * Setup: see sheets/README.md. Run `setup` once from the Apps Script editor.
 */

var RUNS = "Runs";
var TESTS = "Tests";
var RUN_HEADERS = ["Run ID", "Received", "Computer", "Role", "Mode", "OS", "Model", "Year", "CPU", "RAM (GB)",
  "GPU", "After Effects", "Cinema 4D", "Octane", "Suite", "Tests OK", "Tests not OK", "Flags", "Raw JSON file"];
var TEST_HEADERS = ["Run ID", "Computer", "Test", "Category", "Status", "Reason", "Median", "Unit",
  "Spread (CV)", "Valid runs", "All runs", "Flags", "Cache"];

function setup() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureSheet_(ss, RUNS, RUN_HEADERS);
  ensureSheet_(ss, TESTS, TEST_HEADERS);
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty("TOKEN")) {
    props.setProperty("TOKEN", Utilities.getUuid());
  }
  if (!props.getProperty("FOLDER_ID")) {
    var folder = DriveApp.createFolder("Gimmick Bench raw results");
    props.setProperty("FOLDER_ID", folder.getId());
  }
  Logger.log("Token for config.json: " + props.getProperty("TOKEN"));
}

function ensureSheet_(ss, name, headers) {
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    sh.appendRow(headers);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, headers.length).setFontWeight("bold");
  }
  return sh;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function checkToken_(token) {
  var expected = PropertiesService.getScriptProperties().getProperty("TOKEN");
  return expected && token === expected;
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    var body = JSON.parse(e.postData.contents);
    if (!checkToken_(body.token)) { return json_({ ok: false, error: "wrong token" }); }
    var r = body.result;
    if (!r || r.schema !== "gimmick-bench/result@1") { return json_({ ok: false, error: "not a Gimmick Bench result" }); }
    if (r.simulated) { return json_({ ok: false, error: "simulated results are not accepted" }); }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var runs = ensureSheet_(ss, RUNS, RUN_HEADERS);
    var tests = ensureSheet_(ss, TESTS, TEST_HEADERS);

    var existing = runs.getLastRow() > 1 ? runs.getRange(2, 1, runs.getLastRow() - 1, 1).getValues() : [];
    for (var i = 0; i < existing.length; i++) {
      if (existing[i][0] === r.run_id) { return json_({ ok: true, run_id: r.run_id, duplicate: true }); }
    }

    var folder = DriveApp.getFolderById(PropertiesService.getScriptProperties().getProperty("FOLDER_ID"));
    var file = folder.createFile(r.run_id + ".json", JSON.stringify(r), MimeType.PLAIN_TEXT);

    var m = r.machine || {}, sw = r.software || {};
    var ok = 0, notOk = 0;
    var rows = [];
    (r.tests || []).forEach(function (t) {
      if (t.status === "ok") { ok++; } else { notOk++; }
      var s = t.summary || {};
      var all = (t.iterations || []).map(function (it) { return it.value === null || it.value === undefined ? "x" : it.value; }).join(" ");
      rows.push([r.run_id, r.label, t.id, t.category, t.status, t.reason || "", s.median === undefined ? "" : s.median,
        t.metric === "fps" ? "fps" : "s", s.cv === undefined || s.cv === null ? "" : s.cv, s.n_valid || 0, all,
        (t.flags || []).join(", "), t.cache]);
    });
    var gpu = (m.gpus || []).map(function (g) { return g.name + (g.vram_gb ? " " + g.vram_gb + " GB" : ""); }).join(" + ");
    runs.appendRow([r.run_id, new Date(), r.label, r.role, r.mode, m.os_version, m.model_name || m.model_id,
      m.model_year || "", m.cpu, m.ram_gb, gpu, sw.after_effects || "", sw.cinema4d || "", sw.octane || "",
      r.suite_version, ok, notOk, ((r.preflight || {}).flags || []).join(", "), file.getUrl()]);
    if (rows.length) {
      tests.getRange(tests.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    }
    return json_({ ok: true, run_id: r.run_id, tests: rows.length });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function doGet(e) {
  var token = (e && e.parameter && e.parameter.token) || "";
  if (!checkToken_(token)) { return json_({ ok: false, error: "wrong token" }); }
  var folder = DriveApp.getFolderById(PropertiesService.getScriptProperties().getProperty("FOLDER_ID"));
  var files = folder.getFilesByType(MimeType.PLAIN_TEXT);
  var results = [];
  while (files.hasNext()) {
    var f = files.next();
    try { results.push(JSON.parse(f.getBlob().getDataAsString())); } catch (err) {}
  }
  return json_({ ok: true, results: results });
}
