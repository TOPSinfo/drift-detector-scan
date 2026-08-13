// Executes the REAL dashboard.app.js (not a re-implementation of it) inside a minimal
// document/Vue stub, so a Python test can exercise the leadsCount/leadRows computeds against a
// malformed `leads-data` blob and observe whether they throw — a string-presence test on the
// source text cannot catch that bug class.
//
// Usage: node leads_harness.js '<leads-data JSON text>'
//        node leads_harness.js MISSING     # simulates no leads-data element at all
//
// Prints {"leadsCount":N,"leadRows":[...]} to stdout on success. A thrown exception inside
// dashboard.app.js (e.g. the computed calling .reduce/.forEach on a non-array) propagates as a
// non-zero exit + stack trace on stderr, which is exactly what the test wants to detect.
"use strict";
var path = require("path");
var appJsPath = path.join(__dirname, "..", "..", "agent", "assets", "dashboard.app.js");

var leadsText = process.argv[2];

global.document = {
  getElementById: function (id) {
    if (id === "leads-data") {
      if (leadsText === "MISSING") return null;
      return { textContent: leadsText };
    }
    return null;
  }
};

var captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { mount: function () { return null; } };
  },
  markRaw: function (x) { return x; }
};

require(appJsPath);

if (!captured || !captured.computed || typeof captured.computed.leadsCount !== "function") {
  throw new Error("dashboard.app.js did not expose computed.leadsCount — harness is stale");
}

var leadsCount = captured.computed.leadsCount.call({});
var leadRows = captured.computed.leadRows.call({});
process.stdout.write(JSON.stringify({ leadsCount: leadsCount, leadRows: leadRows }));
