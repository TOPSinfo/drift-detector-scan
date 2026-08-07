(function(){
  function blob(id){ var el=document.getElementById(id); try{ return el?JSON.parse(el.textContent):{}; }catch(e){ return {}; } }
  var DATA = blob("drift-data");
  var C = DATA.counts || {}, OWN = (C.byOwner || {});
  // the SBOM/SPDX/SARIF side-payloads (same standard-format bundle `drift-scan sbom`/`sarif`
  // write) — embedded verbatim so the dashboard's SBOM/SARIF panels and the JSON views are
  // byte-for-byte what those commands would produce. Read-only, so markRaw skips Vue's deep
  // reactivity conversion (these can be large and never mutate).
  var SBOM = blob("sbom-data"), SPDX = blob("spdx-data"), SARIF = blob("sarif-data");
  // the AI-SHAPED tier (drift-adhoc/v1) — a SEPARATE, optional blob. null when the ad-hoc pass
  // never ran: the tab is then HIDDEN, not shown as "0" ("cannot see" ≠ "clean", extended here).
  var ADHOC = document.getElementById("adhoc-data") ? blob("adhoc-data") : null;
  // generic scan methodology (Sources / Versions / Parked tiers / catalog note) is boilerplate,
  // identical every scan — it goes to its own "methodology" footer, NOT mixed into the
  // data-specific coverage warnings (unaudited vendors, unreachable sources, …).
  var GENERIC_NOTE = [/^Sources:/, /^Versions are/, /^Parked:/, /^Vendor API sunsets:/];
  function isGenericNote(n){ return GENERIC_NOTE.some(function(r){ return r.test(n); }); }

  // Deterministic "YYYY-MM-DD" -> a comparable day-ordinal, used ONLY to place the Retirement
  // Timeline's points and its "today" line. Pure integer arithmetic (Howard Hinnant's
  // days_from_civil) — no Date object, no wall-clock read, so two runs of the SAME drift.json
  // place every point identically. "Today" is always DATA.generated, the scan's own date —
  // reading the CURRENT wall clock instead would make the chart's own reference line
  // non-deterministic and wrong the moment the page is opened a day after the scan ran.
  function dayOrdinal(s){
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ""));
    if(!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3];
    y -= mo <= 2 ? 1 : 0;
    var era = Math.floor((y >= 0 ? y : y - 399) / 400);
    var yoe = y - era * 400;                                              // [0, 399]
    var doy = Math.floor((153 * (mo + (mo > 2 ? -3 : 9)) + 2) / 5) + d - 1; // [0, 365]
    var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy; // [0, 146096]
    return era * 146097 + doe;
  }

  Vue.createApp({
    data: function(){
      return {
        DATA: DATA, counts: C,
        SBOM: Vue.markRaw(SBOM), SPDX: Vue.markRaw(SPDX), SARIF: Vue.markRaw(SARIF),
        ADHOC: ADHOC ? Vue.markRaw(ADHOC) : null,
        generated: DATA.generated || "",
        scope: "",            // global repo scope ("" = all)
        plane: "drift",        // active TOP-LEVEL plane: supply | drift | ai. Opens on Vendor
                               // Drift (the moat + timeline hero). Each plane owns its own
                               // tiles, hero and content; SBOM/SARIF live ONLY under supply.
        tab: null,             // active PRIMARY tab = the metric-tile dimension (cockpit IA);
                               // null = OVERVIEW default = no scope = the full ranked action
                               // queue in Summary. Was `filter` pre-restructure.
        sub: "summary",        // active sub-tab: summary | sbom | sarif (replaces the old
                               // top-level tab bar; "Retirement timeline" retires into the
                               // hero region — Task 2/3 — so it is not a sub-tab option)
        expanded: {},         // row drill-down: idx (within `rows`) -> open/closed
        sumView: "prev",       // Summary sub-tab: Preview | JSON · drift.json
        sbomView: "prev",      // SBOM sub-tab: Preview | CycloneDX | SPDX
        sarifView: "prev",     // SARIF sub-tab: Preview | JSON · sarif.json
        copyState: {},         // per-view "Copy"/"Copied" label for the JSON copy buttons
        q: "",
        theme: "dark",
        // the Retirement Timeline's hover tooltip: reactive state bound via {{ }}/:style ONLY
        // (no raw-HTML sink of any kind) — see showTip/moveTip/hideTip below.
        tip: {visible: false, x: 0, y: 0, vendor: "", unit: "", repo: "",
              date: "", when: "", statusLabel: "", pillClass: ""}
      };
    },
    computed: {
      repoOptions: function(){
        var m = {};
        (this.DATA.actions||[]).forEach(function(a){ if(a.repo) m[a.repo]=a.repoLabel||a.repo; });
        (this.DATA.shapes||[]).forEach(function(s){ if(s.repo && !(s.repo in m)) m[s.repo]=s.repoLabel||s.repo; });
        return Object.keys(m).sort(function(a,b){ return m[a].localeCompare(m[b]); })
                     .map(function(k){ return {key:k, label:m[k]}; });
      },
      // ---- THREE PLANES (top-level cockpit split, in ascending uniqueness / descending
      // certainty): Supply Chain (CVE + end-of-life software + SBOM/SARIF — table-stakes
      // supply-chain hygiene any SCA tool does), Vendor Drift (the deterministic vendor-API
      // sunsets, all CERTIFIED — the moat, with the retirement timeline as its hero) and AI
      // Frontier (SHAPED, gate-validated). One tab strip per plane; SBOM/SARIF live ONLY under
      // Supply Chain so they don't clutter the other two. ----
      supplyFixes: function(){       // CVE/EOL package upgrades — the Supply Chain slice of "fixes"
        return (this.DATA.actions||[]).filter(function(a){
          return a.status==="DEPRECATED" && a.kind!=="sunset"; }).length;
      },
      shapedRepos: function(){ return ((this.ADHOC&&this.ADHOC.byRepo)||[]).length; },
      // all three planes ALWAYS render — the AI Frontier plane is present even when no shaping
      // pass has run (it then shows an honest empty-state, never a misleading clean zero).
      planeDefs: function(){
        var c=this.counts;
        return [
          {key:"supply", label:"Supply Chain", tag:"SECURITY",
           blurb:"CVEs and end-of-life software — the patches your DevOps scanners already expect.",
           n:(c.critical||0)+(c.eol||0)+this.supplyFixes},
          {key:"drift", label:"Vendor Drift", tag:"CERTIFIED",
           blurb:"Retiring vendor APIs, proven to the file:line — the drift nobody else catches.",
           n:c.sunsets||0},
          {key:"ai", label:"AI Frontier", tag:"SHAPED",
           blurb:"Found by AI in code the tool couldn't read on its own, then re-checked on the spot.",
           n:this.shapedCount}
        ];
      },
      // full tile definition, each group tagged with its plane. `tileGroups` (below) shows only
      // the ACTIVE plane's tiles; `tileCountsByKey`/knownTabs iterate the FULL set so a
      // zero-check or a deep-link tab from any plane still resolves.
      allTileGroups: function(){
        var c=this.counts;
        return [
          {plane:"supply", title:"Supply chain", tiles:[
            {key:"critical",label:"Critical",n:c.critical,sev:"crit"},
            {key:"fixes",label:"Fixes",n:this.supplyFixes},
            {key:"eol",label:"EOL",n:c.eol}]},
          {plane:"drift", title:"Vendor drift", tiles:[
            {key:"sunsets",label:"Sunsets",n:c.sunsets},
            {key:"pastdue",label:"Past-due",n:c.pastDue,sev:"warn"},
            {key:"apis",label:"APIs",n:c.apis},
            {key:"unknown",label:"Unknown",n:c.unknown},
            {key:"private",label:"Private",n:c.private},
            {key:"unaudited",label:"Unaudited",n:c.unaudited}]},
          {plane:"ai", title:"AI frontier", tiles:[
            {key:"shaped",label:"Shaped",n:this.shapedCount},
            {key:"shapedrepos",label:"Repos",n:this.shapedRepos}]}
        ];
      },
      tileGroups: function(){
        var pl=this.plane;
        return this.allTileGroups.filter(function(g){ return g.plane===pl; });
      },
      // ownership (devops/developer) is cross-cutting — who owns the fixes spans every plane,
      // so it's a compact header stat, not a plane of its own.
      ownStats: function(){
        var o=OWN, own=function(k){ var v=o[k]||{}; return (v.fixes||0)+(v.review||0); };
        return {devops:own("devops"), developer:own("developer")};
      },
      // tile key -> its count, flattened out of ALL planes' tiles. The single place heroMode (and
      // the empty-state header) look up "is this dimension zero", so the zero-check always
      // agrees with the number printed on the tab itself — no second count computed by hand.
      tileCountsByKey: function(){
        var m = {};
        this.allTileGroups.forEach(function(g){ g.tiles.forEach(function(t){ m[t.key] = t.n; }); });
        return m;
      },
      themeLabel: function(){ var m=this.theme; return (m==="dark"?"●":m==="light"?"○":"◐")+" Theme: "+m; },
      // ---- Summary table: mode dispatch + scope/query-filtered rows (ported from the
      // pre-Vue _CLIENT_JS: actionsFor/endpointsFor/privateFor/catalogFor + the render()
      // mode map). "mode" mirrors the vanilla state.mode; "rows" mirrors calling the right
      // …For() and feeding it to the right renderX().
      mode: function(){
        var f = this.tab;
        if(f==="apis" || f==="unknown") return "endpoints";
        if(f==="private") return "private";
        if(f==="unaudited") return "catalog";
        return "actions";
      },
      rows: function(){
        if(this.mode==="endpoints") return this.endpointsFor();
        if(this.mode==="private")   return this.privateFor();
        if(this.mode==="catalog")   return this.catalogFor();
        return this.actionsFor();
      },

      // ---- the AI-SHAPED tier: gate-validated this run, not yet in the catalog. Loop var is `sh`
      // (NOT a/e/p/cv/row) so check_accessor_coverage's certified-row union is not widened. ----
      hasShaped: function(){ return !!this.ADHOC; },
      shaped: function(){
        // params rp/act (NOT r/a) — a/e/p/cv/row are check_accessor_coverage's tracked accessors,
        // and reusing them here would demand the shaped-record fields on the CERTIFIED sample.
        var out = [];
        ((this.ADHOC && this.ADHOC.byRepo) || []).forEach(function(rp){
          (rp.shaped || []).forEach(function(act){
            var f = (act.files || [])[0];
            out.push({ repo: rp.repo, ref: act.ref, op: act.operation || "",
                       date: act.date || "", loc: (f && f.loc) || f || "" });
          });
        });
        return out;
      },
      shapedCount: function(){ return this.shaped.length; },

      // ---- JSON views: drift.json / CycloneDX / SPDX / SARIF, pretty-printed for the
      // read-only "view / copy" panels. Same DATA/SBOM/SPDX/SARIF the tables above render
      // from — the verified source of truth, not a re-derived summary. ----
      driftJsonText: function(){ return JSON.stringify(this.DATA, null, 2); },
      sbomJsonText: function(){ return JSON.stringify(this.SBOM, null, 2); },
      spdxJsonText: function(){ return JSON.stringify(this.SPDX, null, 2); },
      sarifJsonText: function(){ return JSON.stringify(this.SARIF, null, 2); },

      // ---- SBOM preview: components (scoped to the selected repo via drift:repo properties)
      // + per-component worst vuln severity, ported from the pre-Vue renderSbom(). ----
      sbomVulnIndex: function(){
        var worst = {}, counts = {}, rank = {critical:4, high:3, medium:2, low:1, unknown:0};
        (this.SBOM.vulnerabilities || []).forEach(function(v){
          var sev = ((v.ratings || [{}])[0] || {}).severity || "unknown";
          (v.affects || []).forEach(function(a){
            if(!(a.ref in worst) || rank[sev] > rank[worst[a.ref]]) worst[a.ref] = sev;
            counts[a.ref] = (counts[a.ref] || 0) + 1;
          });
        });
        return {worst: worst, counts: counts};
      },
      sbomComponents: function(){
        var self = this, all = this.SBOM.components || [];
        if(!this.scope) return all;
        return all.filter(function(c){ return self.componentRepos(c).indexOf(self.scope) > -1; });
      },
      sbomRows: function(){
        var self = this, idx = this.sbomVulnIndex;
        return this.sbomComponents.map(function(c){
          var ref = c["bom-ref"], n = idx.counts[ref] || 0, sev = idx.worst[ref];
          return {
            type: c.type, purl: c.purl || c["bom-ref"], version: c.version || "",
            repoCount: self.componentRepos(c).length,
            vulnCount: n, vulnSeverity: sev,
            pillClass: sev === "critical" ? "crit" : sev === "high" ? "high"
                     : sev === "medium" ? "med" : "low"
          };
        });
      },
      sbomHeaderText: function(){
        var n = this.sbomComponents.length, vulns = (this.SBOM.vulnerabilities || []).length;
        return "Components — " + n + (this.scope ? (" in " + this.repoLabelOf(this.scope)) : "")
             + "  ·  " + vulns + " vulnerabilities";
      },

      // ---- SARIF preview: results grouped by rule, scoped to the selected repo via the
      // uri prefix (results carry no repo field of their own, just file:line uris rooted at
      // the repo path) — ported from the pre-Vue renderSarif(). ----
      sarifAllResults: function(){ return ((this.SARIF.runs || [{}])[0] || {}).results || []; },
      sarifResults: function(){
        var self = this;
        if(!this.scope) return this.sarifAllResults;
        return this.sarifAllResults.filter(function(r){
          return self.sarifUri(r).indexOf(self.scope + "/") === 0; });
      },
      sarifGroups: function(){
        var byRule = {};
        this.sarifResults.forEach(function(r){ (byRule[r.ruleId] = byRule[r.ruleId] || []).push(r); });
        return Object.keys(byRule).sort().map(function(rid){
          var list = byRule[rid];
          return {
            ruleId: rid, count: list.length,
            rows: list.slice(0, 200).map(function(r){
              var pl = ((r.locations || [])[0] || {}).physicalLocation || {};
              var uri = (pl.artifactLocation || {}).uri || "";
              var line = (pl.region || {}).startLine;
              return {
                where: uri + (line ? (":" + line) : ""),
                message: (r.message || {}).text || "",
                level: r.level || "note",
                pillClass: r.level === "error" ? "crit" : r.level === "warning" ? "high" : "low"
              };
            })
          };
        });
      },
      sarifHeaderText: function(){
        return "Findings — " + this.sarifResults.length + " results"
             + (this.scope ? (" in " + this.repoLabelOf(this.scope)) : "") + ", grouped by rule";
      },

      // ---- coverage / "changed since last scan" / methodology footer — the honest
      // "how complete was this scan" context, out of the data (findings) plane. "Cannot see"
      // must never render as "clean": the rootsUnscannable block below is the load-bearing
      // one — it is the only thing standing between a repo the scanner couldn't open and a
      // report that looks green over it. ----
      rootsUnscannable: function(){ return this.DATA.rootsUnscannable || []; },
      coverageNotesSpecific: function(){
        return (this.DATA.coverageNotes || []).filter(function(n){ return !isGenericNote(n); });
      },
      methodologyNotes: function(){
        return (this.DATA.coverageNotes || []).filter(isGenericNote);
      },
      unknownShapes: function(){
        return (this.DATA.shapes || []).filter(function(s){ return s.verdict === "UNKNOWN"; });
      },
      gradedRepos: function(){
        return (this.DATA.coverageGrades || []).filter(function(g){ return g.grade !== "HIGH"; });
      },
      sdkMediated: function(){ return this.DATA.sdkMediated || []; },
      coveredDeps: function(){ return this.DATA.coveredDeps || []; },
      coverageHasContent: function(){
        return this.rootsUnscannable.length > 0 || this.coverageNotesSpecific.length > 0 ||
               this.unknownShapes.length > 0 || this.gradedRepos.length > 0 ||
               this.sdkMediated.length > 0 || this.coveredDeps.length > 0;
      },
      inventoryDrift: function(){ return this.DATA.inventoryDrift || null; },
      driftChangeRows: function(){
        var d = this.inventoryDrift; if(!d) return [];
        return (d.changes || []).map(function(c){
          var bits = [];
          (c.endpointsAdded || []).forEach(function(e){ bits.push("+ endpoint " + e); });
          (c.endpointsRemoved || []).forEach(function(e){ bits.push("− endpoint " + e); });
          (c.sdkVersionChanges || []).forEach(function(s){ bits.push(s.pkg + " " + s.from + " → " + s.to); });
          (c.sdksAdded || []).forEach(function(s){ bits.push("+ " + s.pkg + " " + s.ver); });
          (c.sdksRemoved || []).forEach(function(s){ bits.push("− " + s.pkg + " " + s.ver); });
          (c.runtimeChanges || []).forEach(function(r){ bits.push(r.product + " " + r.from + " → " + r.to); });
          return {repo: c.repo, bits: bits};
        }).filter(function(chg){ return chg.bits.length > 0; });
      },
      driftHasContent: function(){
        var d = this.inventoryDrift; if(!d) return false;
        return !!((d.reposAdded && d.reposAdded.length) || (d.reposRemoved && d.reposRemoved.length) ||
               this.driftChangeRows.length > 0);
      },

      // ---- the Retirement Timeline (Task 2 restructure of the old per-vendor SVG scatter,
      // per docs/design/2026-08-04-cockpit-mockup.html): one row per OPERATION, not one dot
      // per vendor — two sunsets on the same vendor but different operations (SP-API
      // /catalog/v0 vs /fba/inbound/v0) must render as two rows, never merge into one point.
      // Rows are grouped by vendor (`byVendor`) and positioned on a shared date axis; "today"
      // is anchored at dayOrdinal(DATA.generated) — never the live wall clock — so the SAME drift.json
      // places every point identically on any machine, on any day it's opened. NONE silently
      // dropped: a sunset is either a dated row on the axis (timeline.dated) or a chip in the
      // undated lane (timeline.undated); verify.check_timeline_lanes enforces the template
      // still references BOTH, so deleting either (hiding deprecated-no-date sunsets, say)
      // fails verify instead of only a screenshot nobody looks at. Respects the global repo
      // scope like every other view.
      timeline: function(){
        var self = this;
        var genOrd = dayOrdinal(this.generated);
        var sunsets = (this.DATA.actions || []).filter(function(a){
          return a.kind === "sunset" && self.matchesRepo(a.repo);
        });
        var datedActions = sunsets.filter(function(a){ return !!a.date; });
        var undatedActions = sunsets.filter(function(a){ return !a.date; });

        var undated = undatedActions.map(function(a){
          return {repo: a.repoLabel || a.repo, vendor: a.ref, unit: a.unit || ""};
        });

        if(!datedActions.length){
          return {dated: [], undated: undated, byVendor: [], years: [], todayPct: null};
        }

        // shared date axis: span the dated actions AND today (so "today" is never clipped
        // off the edge), padded a little so points don't sit flush on the axis border.
        var ords = datedActions.map(function(a){ return dayOrdinal(a.date); });
        var allOrds = genOrd === null ? ords.slice() : ords.concat([genOrd]);
        var minOrd = Math.min.apply(null, allOrds), maxOrd = Math.max.apply(null, allOrds);
        var span = Math.max(1, maxOrd - minOrd);
        var pad = Math.max(1, Math.round(span * 0.05));
        var lo = minOrd - pad, hi = maxOrd + pad, fullSpan = Math.max(1, hi - lo);
        var pctOf = function(o){ return ((o - lo) / fullSpan) * 100; };

        // kind: past-due (already retired) / soon (retires within ~6 months) / upcoming —
        // the three colors the legend + the hover pill both key off.
        var dated = datedActions.map(function(a){
          var ord = dayOrdinal(a.date);
          var days = genOrd === null ? null : (ord - genOrd);
          var kind = days === null ? "up" : (days < 0 ? "crit" : (days <= 183 ? "soon" : "up"));
          return {
            repo: a.repoLabel || a.repo, vendor: a.ref, unit: a.unit || "", date: a.date,
            pct: pctOf(ord), kind: kind,
            when: days === null ? "" : (days < 0 ? (Math.abs(days) + " days ago") : ("in " + days + " days")),
            statusLabel: kind === "crit" ? "past-due" : kind === "soon" ? "retires ≤ 6 months" : "upcoming",
            pillClass: kind                       // crit / soon / up — the pill tint matches the axis dot

          };
        });

        var byVendorMap = {};
        dated.forEach(function(pt){ (byVendorMap[pt.vendor] = byVendorMap[pt.vendor] || []).push(pt); });
        var byVendor = Object.keys(byVendorMap).sort().map(function(v){
          return {vendor: v, items: byVendorMap[v].slice().sort(function(x, y){ return x.pct - y.pct; })};
        });

        // year ticks along the axis — derived from the data's own date range (+ today), never
        // a hardcoded calendar window, so the axis fits whatever fleet is scanned.
        var yearSet = {};
        datedActions.forEach(function(a){ yearSet[+String(a.date).slice(0, 4)] = true; });
        if(self.generated) yearSet[+String(self.generated).slice(0, 4)] = true;
        var yearNums = Object.keys(yearSet).map(Number).sort(function(x, y){ return x - y; });
        var years = [];
        for(var y = yearNums[0]; y <= yearNums[yearNums.length - 1]; y++){
          years.push({year: y, pct: pctOf(dayOrdinal(y + "-01-01"))});
        }

        return {
          dated: dated, undated: undated, byVendor: byVendor, years: years,
          todayPct: genOrd === null ? null : pctOf(genOrd)
        };
      },

      // ---- Task 3: the hero is CONTEXTUAL to the active primary tab, per
      // docs/design/2026-08-04-cockpit-mockup.html's buildHero(). Exactly one of three
      // states, decided ONCE here so the template is a plain v-if/v-else-if/v-else chain
      // with no duplicated branching logic:
      //   'timeline' — the flagship Retirement Timeline (Task 2, unchanged): sunsets/pastdue/
      //     fixes/developer, and the null OVERVIEW default. Same always-on timeline for all
      //     of these (it was never tab-filtered — see the `timeline` computed above), so this
      //     mode is really "no bespoke hero view — show the fleet's sunset landscape".
      //   'vendors' — apis/unknown: which third-party APIs (or unclassified hosts) this code
      //     calls, per vendorBars below.
      //   'empty' — every other dimension (critical/eol/private/unaudited/devops) WHEN its
      //     tile count is 0. This is the load-bearing branch: "cannot see" must never render
      //     as "clean" (CLAUDE.md principle 1), so a genuine zero gets the honest empty-state
      //     copy instead of an empty timeline that could be mistaken for "nothing to see
      //     here, scan's fine". If one of those dimensions is NOT zero, there's still no
      //     bespoke hero for it, so it falls back to the always-on timeline (real data, just
      //     not scoped to that dimension) rather than lying with a "nothing found" empty-state
      //     over a tab that plainly has rows in the table below.
      heroMode: function(){
        // AI + Supply Chain planes get their own plane-intro hero (a headline card, no
        // timeline — the timeline is CERTIFIED-only and belongs to Vendor Drift).
        if(this.plane === "ai") return "ai";
        if(this.plane === "supply") return "supply";
        // Vendor Drift plane: the flagship timeline for sunsets/past-due/overview, the vendor
        // bars for apis/unknown, and the honest empty-state for a genuinely-zero dimension.
        var TIMELINE_TABS = {sunsets:1, pastdue:1};
        var t = this.tab;
        if(t === null || TIMELINE_TABS[t]) return "timeline";
        if(t === "apis" || t === "unknown") return "vendors";
        return (this.tileCountsByKey[t] || 0) === 0 ? "empty" : "timeline";
      },
      heroTitle: function(){
        var m = this.heroMode;
        if(m === "ai") return "AI Frontier — shaped, gate-validated";
        if(m === "supply") return "Supply-chain security";
        if(m === "vendors") return this.tab === "apis" ? "Integrations by vendor" : "Unclassified endpoints";
        if(m === "empty") return this.tabName(this.tab);
        return "Retirement timeline";
      },
      heroWhy: function(){
        var scopeSuffix = this.scope ? (" for " + this.repoLabelOf(this.scope)) : "";
        if(this.heroMode === "ai") return "call-sites an AI found in code the tool couldn't read, each re-checked on the spot" + scopeSuffix;
        if(this.heroMode === "supply") return "CVEs and end-of-life software, plus the SBOM and SARIF exports your pipeline consumes" + scopeSuffix;
        if(this.heroMode === "vendors") return "which third-party APIs this code calls" + scopeSuffix;
        if(this.heroMode === "empty") return "";
        return "every vendor API sunset, one row per operation" + scopeSuffix + " — hover a row for detail";
      },
      // ---- vendor/endpoint breakdown for the 'vendors' hero (apis/unknown tabs), grouping
      // DATA.endpoints — the mockup's `.mini`/`.bar` bars. Endpoints carry no per-operation
      // field on this projection (repo/domain/vendor/version/classified/file_count/files
      // only — see _endpoints_of in dashboard_render.py), so rather than inventing an
      // "operations" number the bars report what the data actually holds: distinct hosts +
      // the number of distinct endpoint records per vendor (apis), or call-site volume per
      // unclassified host (unknown — vendor is always the literal string "Unknown" there, so
      // grouping by vendor would collapse every unclassified host into one bar; domain is the
      // real identity for that tab). Respects the global repo scope like every other view.
      vendorBars: function(){
        var self = this, wantUnknown = this.tab === "unknown";
        var eps = (this.DATA.endpoints || []).filter(function(e){
          return self.matchesRepo(e.repo) && !!e.classified === !wantUnknown;
        });
        var byKey = {}, order = [];
        eps.forEach(function(e){
          var key = wantUnknown ? (e.domain || "Unknown host") : (e.vendor || "Unknown");
          if(!(key in byKey)){ byKey[key] = {hosts:{}, records:0, files:0}; order.push(key); }
          var g = byKey[key];
          g.hosts[e.domain || ""] = true;
          g.records += 1;
          g.files += (e.file_count || 0);
        });
        var maxRecords = Math.max.apply(null, order.map(function(k){ return byKey[k].records; }).concat([1]));
        var palette = ["var(--accent)", "var(--sun)", "var(--accent-2)", "var(--high)", "var(--low)"];
        return order.map(function(k, i){
          var g = byKey[k], hostN = Object.keys(g.hosts).filter(Boolean).length;
          var sub = wantUnknown
            ? (g.files + " call site" + (g.files === 1 ? "" : "s") + " — unclassified")
            : (hostN + " host" + (hostN === 1 ? "" : "s") + " · " + g.records + " endpoint" + (g.records === 1 ? "" : "s"));
          return {
            name: k, sub: sub,
            pct: Math.max(4, Math.round((g.records / maxRecords) * 100)),
            color: wantUnknown ? "var(--muted)" : palette[i % palette.length]
          };
        });
      }
    },
    methods: {
      // ---- toggleTab: set the active primary tab (the metric-tile dimension), or clear it
      // back to null (OVERVIEW — no scope, the full ranked action queue) if it's already
      // active. Was toggleTile/`filter` pre-restructure; same toggle semantics. ----
      toggleTab: function(k){ this.tab = (this.tab===k) ? null : k; this.sub = "summary"; },   // show the filtered rows on tab click
      // ---- switch the top-level plane: reset the tile filter (each plane has its own tiles),
      // drop back to the plane's default content view, and clear the search box.
      switchPlane: function(k){ this.plane = k; this.tab = null; this.sub = "summary"; this.q = ""; },
      cycleTheme: function(){ var m=["auto","light","dark"], i=(m.indexOf(this.theme)+1)%3; this.theme=m[i];
        document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
        try{ localStorage.setItem("drift-theme", this.theme); }catch(e){} },

      // ---- the global repo scope (the #repo-filter select, "" = all). Applies to actions,
      // endpoints AND private — the bug fixed earlier was that it only gated actions. Catalog
      // is vendor-level/fleet-wide and stays unscoped, as in the vanilla engine. ----
      matchesRepo: function(repo){ return !this.scope || repo === this.scope; },
      matchesQ: function(text){ return !this.q || String(text).toLowerCase().indexOf(this.q.toLowerCase()) > -1; },

      // Scheme allow-list for any href built from scan data: only http/https become clickable
      // links; javascript:/data:/etc. fall back to plain (already auto-escaped) text. Ports
      // the vanilla safeUrl() — the client-side XSS guard esc/escA/safeUrl provided before
      // Task 3 removed the old string-built rows. Vue's {{ }} / :attr bindings now do the
      // escaping job of esc()/escA(); safeUrl still has to do ITS job (scheme gating) because
      // auto-escaping alone does not stop a clickable javascript: URI from executing on click.
      safeUrl: function(u){ u = String(u==null ? "" : u); return /^https?:\/\//i.test(u) ? u : null; },

      copyText: function(text){ if(navigator.clipboard) navigator.clipboard.writeText(text); },

      // ---- Retirement Timeline hover tooltip: identity (vendor+operation+retires-date+
      // "N days ago/in N days"+repo), positioned off the mouse. Content is set on reactive
      // `tip` state and rendered via {{ }} bindings in the template — no raw-HTML sink — so a
      // scan-controlled vendor/operation/repo string cannot break out into markup. ----
      showTip: function(pt, evt){
        this.tip.visible = true;
        this.tip.vendor = pt.vendor; this.tip.unit = pt.unit; this.tip.repo = pt.repo;
        this.tip.date = pt.date; this.tip.when = pt.when;
        this.tip.statusLabel = pt.statusLabel; this.tip.pillClass = pt.pillClass;
        this.moveTip(evt);
      },
      moveTip: function(evt){
        var x = evt.clientX + 14, y = evt.clientY + 14;
        if(x + 300 > window.innerWidth) x = evt.clientX - 300;
        this.tip.x = x; this.tip.y = y;
      },
      hideTip: function(){ this.tip.visible = false; },

      // the action set for the ACTIVE plane — this is the fix-queue split the three-plane
      // layout is built on: Supply Chain owns CVE/EOL package upgrades (kind !== "sunset"),
      // Vendor Drift owns the vendor-migration queue (kind === "sunset"), AI owns none (it
      // renders the shaped table, not the action queue). actionsFor filters this, not the raw
      // DATA.actions, so the same "Fixes" tile means different things in different planes.
      planeActionBase: function(){
        var self = this;
        if(this.plane === "ai") return [];
        return (this.DATA.actions || []).filter(function(a){
          return self.plane === "supply" ? a.kind !== "sunset" : a.kind === "sunset";
        });
      },
      actionsFor: function(){
        var f = this.tab, self = this;
        return this.planeActionBase().filter(function(a){
          if(!self.matchesRepo(a.repo)) return false;                 // global repo scope
          // the retiring operation is part of the identity, so it must be searchable too —
          // a PM filtering for "GetCategoryFeatures" has to land on its row
          var label = a.ref + (a.unit ? " " + a.unit : "");
          if(!self.matchesQ((a.repoLabel || a.repo || "") + " " + label)) return false;
          if(f==="critical")  return a.worst==="CRITICAL";
          if(f==="fixes")     return a.status==="DEPRECATED";
          if(f==="eol")       return a.kind==="eol";
          if(f==="devops")    return a.owner==="devops";               // the two delivery streams
          if(f==="developer") return a.owner==="developer";
          if(f==="sunsets")   return a.kind==="sunset";
          // "Past-due" = a sunset already retired (DEPRECATED with a passed date) — an
          // integration broken NOW, distinct from an upcoming deadline or a CVE fix.
          if(f==="pastdue")   return a.kind==="sunset" && a.status==="DEPRECATED" && a.date;
          return true;
        });
      },
      endpointsFor: function(){
        var f = this.tab, self = this;
        return (this.DATA.endpoints || []).filter(function(e){
          if(!self.matchesRepo(e.repo)) return false;                  // global repo scope
          if(!self.matchesQ((e.repo || "") + " " + (e.domain || "") + " " + (e.vendor || ""))) return false;
          if(f==="unknown") return !e.classified;
          if(f==="apis")    return e.classified;
          return true;
        });
      },
      privateFor: function(){
        var self = this;
        return (this.DATA.private || []).filter(function(p){
          // Private tile honours the repo scope too
          return self.matchesRepo(p.repo) && self.matchesQ((p.repo || "") + " " + (p.source || ""));
        });
      },
      catalogFor: function(){
        var self = this;
        return (this.DATA.catalog || []).filter(function(cv){
          return cv.verdict !== "CURRENT" && self.matchesQ((cv.vendor || "") + " " + (cv.verdict || ""));
        });
      },

      actionLabel: function(a){ return a.ref + (a.unit ? " " + a.unit : ""); },
      targetText: function(a){
        return a.fix_version ? (a.current_version + " → " + a.fix_version) : (a.recommendation || "review");
      },
      catalogWhy: function(cv){
        if(cv.verdict==="UNAUDITED"){
          return cv.catalogEntries
            ? cv.catalogEntries + " catalog entr(y/ies), but the vendor's page has never been reconciled"
            : "no catalog entries at all";
        }
        return "last checked " + (cv.checked || "?") + " — re-check the vendor's page";
      },

      // ---- row drill-down: inline-accordion, one flag per row (keyed by its position in
      // the current `rows`). Only actions/endpoints rows expand — private/catalog rows never
      // had a click handler in the vanilla engine either. ----
      onRowClick: function(idx){ if(this.mode==="actions" || this.mode==="endpoints") this.toggleRow(idx); },
      toggleRow: function(idx){ this.expanded[idx] = !this.expanded[idx]; },

      // ---- SBOM/SARIF repo-scope helpers ----
      componentRepos: function(c){
        return (c.properties || []).filter(function(pr){ return pr.name === "drift:repo"; })
                                    .map(function(pr){ return pr.value; });
      },
      sarifUri: function(r){
        var l = (r.locations || [])[0];
        return ((l && l.physicalLocation || {}).artifactLocation || {}).uri || "";
      },
      repoLabelOf: function(k){
        var opt = this.repoOptions.filter(function(o){ return o.key === k; })[0];
        return opt ? opt.label : k;
      },

      // ---- Task 3: display name for a primary-tab key in the empty-state hero header.
      // Ported from the mockup's tabName() (docs/design/2026-08-04-cockpit-mockup.html) —
      // only the dimensions that can actually reach heroMode === 'empty' need an entry;
      // an unlisted key falls back to the raw key rather than throwing.
      tabName: function(k){
        var m = {devops:"DevOps queue", developer:"Developer queue", critical:"Critical",
                 eol:"End-of-life", private:"Private / uncrawlable", unaudited:"Unaudited vendors"};
        return m[k] || k;
      },

      // ---- JSON view/copy panels (drift.json / CycloneDX / SPDX / SARIF): copy-to-clipboard
      // with a brief "Copied" acknowledgement, keyed per view so the four panels' buttons
      // don't share state. ----
      copyJson: function(key, text){
        var self = this;
        var done = function(){ self.copyState[key] = "Copied";
          setTimeout(function(){ self.copyState[key] = "Copy"; }, 1200); };
        if(navigator.clipboard) navigator.clipboard.writeText(text).then(done, done);
        else done();
      },
      copyLabel: function(key){ return this.copyState[key] || "Copy"; },

      // ---- Task 4/7: deep-linkable state — scope ("repo"), the active primary tab ("tab")
      // and the active sub-tab ("sub") round-trip through the URL query string so a
      // delivered issue (e.g. "APIs, scoped to repo X, SBOM view") can link straight to that
      // view. `q` (the free-text search box) is deliberately NOT written here: it's transient
      // per-session input, not a "view" worth bookmarking, and syncing it would rewrite the
      // address bar on every keystroke. Only non-default values are written (sub's default is
      // "summary"), so the clean/default view keeps a clean URL, and history.replaceState
      // (not pushState) is used so every tab click doesn't spam Back.
      syncUrl: function(){
        try{
          var params = new URLSearchParams();
          if(this.scope) params.set("repo", this.scope);
          if(this.plane && this.plane !== "drift") params.set("plane", this.plane);
          if(this.tab) params.set("tab", this.tab);
          if(this.sub && this.sub !== "summary") params.set("sub", this.sub);
          var qs = params.toString();
          var url = location.pathname + (qs ? "?" + qs : "") + location.hash;
          history.replaceState(null, "", url);
        }catch(e){}
      }
    },
    watch: {
      // any change to WHAT is shown (primary tab, repo scope, search text) closes every open
      // detail row — mirrors the vanilla render(), which rebuilt the whole <tbody> (and so
      // discarded every row's open/closed state) on every tile click / scope change / keystroke.
      // It also (tab/scope only) re-syncs the URL — see the Task 4/7 note on syncUrl above.
      tab: function(){ this.expanded = {}; this.syncUrl(); },
      plane: function(){ this.expanded = {}; this.syncUrl(); },
      scope: function(){ this.expanded = {}; this.syncUrl(); },
      // sub (Summary/SBOM/SARIF) doesn't scope `rows`/`expanded` — only the primary tab and
      // repo scope do — so switching it just re-syncs the URL, no accordion reset needed.
      sub: function(){ this.syncUrl(); },
      q: function(){ this.expanded = {}; }
    },
    mounted: function(){
      try{ var s=localStorage.getItem("drift-theme"); if(s) this.theme=s; }catch(e){}
      document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
      document.title = "Drift Detector — DevSecOps Cockpit · " + this.generated;

      // ---- Task 4/7: seed scope/tab/sub from the URL on load. Every value is validated
      // against the known-good option lists (repoOptions / tile keys / the fixed sub-tab set)
      // before being assigned — an unknown or stale param (a repo that no longer exists, a
      // typo'd tab=bogus, a sub=bogus) is silently ignored and the default view renders,
      // never a throw.
      try{
        var params = new URLSearchParams(location.search);
        var repo = params.get("repo");
        if(repo && this.repoOptions.some(function(o){ return o.key === repo; })) this.scope = repo;
        // plane first (an explicit ?plane=), then tab — a valid ?tab= also snaps the plane to
        // the one that owns it, so a deep-link to a tile always lands on the right plane.
        var plane = params.get("plane");
        if(plane && ["supply", "drift", "ai"].indexOf(plane) > -1) this.plane = plane;
        var tab = params.get("tab"), tabPlane = {};
        this.allTileGroups.forEach(function(g){ g.tiles.forEach(function(t){ tabPlane[t.key] = g.plane; }); });
        if(tab && (tab in tabPlane)){ this.tab = tab; this.plane = tabPlane[tab]; }
        var sub = params.get("sub");
        if(sub && ["summary", "sbom", "sarif"].indexOf(sub) > -1) this.sub = sub;
      }catch(e){}
      this.syncUrl();
    }
  }).mount("#app");
})();
