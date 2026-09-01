"""Issue + draft-MR delivery. The planner is pure (payload + what's already on GitLab -> a
create/update/close plan), so idempotency is unit-testable without a network."""
from agent.lib import delivery


def _cve(repo="web", ref="composer/aws/aws-sdk-php"):
    return {"repo": repo, "ref": ref, "kind": "cve", "unit": None, "owner": "devops",
            "status": "DEPRECATED", "date": None, "recommendation": "upgrade to >= 3.283",
            "command": "composer require aws/aws-sdk-php:^3.283", "worst": "HIGH",
            "files": [{"loc": "composer.json:1", "href": "https://git.x/web/-/blob/a/composer.json#L1"}],
            "sources": ["https://osv.dev/x"]}


def _sunset(repo="ebayapi", unit="GetCategories"):
    return {"repo": repo, "ref": "eBay", "kind": "sunset", "unit": unit, "owner": "developer",
            "status": "DEPRECATED", "date": "2025-01-01", "recommendation": "migrate to Taxonomy API",
            "files": [{"loc": "src/Ebay.php:9", "href": "https://git.x/g/ebayapi/-/blob/a/src/Ebay.php#L9"}],
            "sources": ["https://developer.ebay.com/x"]}


_META = {"web": {"project": "root/web"}, "ebayapi": {"project": "g/ebayapi"}}


def _payload(actions):
    return {"actions": actions}


def _act(*, repo="r", owner="developer", kind="sunset", ref="eBay", unit="A",
         status="DEPRECATED", date="2025-01-01", worst="SUNSET", recommendation="migrate",
         files=None, sources=None):
    return {"repo": repo, "owner": owner, "kind": kind, "ref": ref, "unit": unit,
            "status": status, "date": date, "worst": worst, "recommendation": recommendation,
            "files": files if files is not None else
                     [{"loc": "src/A.php:1", "href": "https://git.x/g/r/-/blob/a/src/A.php#L1"}],
            "sources": sources if sources is not None else ["https://vendor.example/x"]}


# --------------------------------------------------------------- identity + parsing
def test_action_fingerprint_is_version_independent():
    a1 = {"repo": "r", "kind": "cve", "ref": "npm/x", "unit": None}
    a2 = dict(a1)                                    # a version bump doesn't change the ref/unit
    assert delivery.action_fingerprint(a1) == delivery.action_fingerprint(a2)
    b = {"repo": "r", "kind": "sunset", "ref": "eBay", "unit": "GetItem"}
    assert delivery.action_fingerprint(a1) != delivery.action_fingerprint(b)


def test_project_path_from_remote():
    assert delivery.project_path("https://git.x/group/repo.git") == "group/repo"
    assert delivery.project_path("https://git.x/a/b/c") == "a/b/c"
    assert delivery.project_path("not-a-url") is None


# --------------------------------------------------------------- the plan (pure)
def test_new_findings_create_one_devops_and_one_developer_issue_in_repo():
    """The new model: each audience gets ONE comprehensive issue per repo, filed IN that
    repo's own project (not a central devops_project) — no MRs are ever planned."""
    plan = delivery.build_plan(_payload([_cve(), _sunset()]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    assert plan["mrs"] == []                                          # the draft-MR path is retired
    devops = [i for i in plan["issues"] if i.get("stream") == "devops"]
    dev = [i for i in plan["issues"] if i.get("stream") == "developer"]
    assert len(devops) == 1 and devops[0]["op"] == "create"
    assert devops[0]["project"] == "root/web"                         # in the repo, not central
    assert len(dev) == 1 and dev[0]["op"] == "create"
    assert dev[0]["project"] == "g/ebayapi"                           # in the repo, not central
    assert dev[0]["title"] == "🚨 [drift] API migrations for g/ebayapi"   # past-due sunset -> 🚨


def test_existing_issue_with_same_body_is_skipped_not_duplicated():
    a = _cve()
    project = _META["web"]["project"]
    body = delivery.devops_repo_body(project, [a])           # the per-repo DevOps body
    existing = {"issues": [{"iid": 7, "state": "opened", "description": body,
                            "title": f"[drift] platform upkeep for {project}"}], "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, existing, "root/drift-detector")
    devops = [i for i in plan["issues"] if i.get("stream") == "devops"]
    assert devops[0]["op"] == "skip" and devops[0]["iid"] == 7


def test_crlf_only_difference_skips_not_updates():
    """SHIPPED BUG: a live re-run reported '2 updated' for unchanged issues — GitLab returns
    the description with CRLF, so the raw compare always looked changed and rewrote the issue
    (noise) every run. Normalised compare must treat CRLF/trailing-space as identical → skip."""
    a = _cve()
    project = _META["web"]["project"]
    body = delivery.devops_repo_body(project, [a])
    gitlab_returned = body.replace("\n", "\r\n") + "   \r\n"   # CRLF + trailing whitespace
    existing = {"issues": [{"iid": 7, "state": "opened", "description": gitlab_returned,
                            "title": f"[drift] platform upkeep for {project}"}], "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, existing, "root/drift-detector")
    devops = [i for i in plan["issues"] if i.get("stream") == "devops"]
    assert devops[0]["op"] == "skip"


def test_changed_finding_updates_the_same_issue():
    a = _cve()
    project = _META["web"]["project"]
    fp = delivery.repo_fingerprint(project, "devops")
    stale = {"issues": [{"iid": 7, "state": "opened",
                         "description": delivery.marker(fp) + "\nOLD BODY", "title": "old"}],
             "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, stale, "root/drift-detector")
    devops = [i for i in plan["issues"] if i.get("stream") == "devops"]
    assert devops[0]["op"] == "update" and devops[0]["iid"] == 7


def test_closed_issue_for_a_still_present_finding_is_reopened():
    a = _cve()
    project = _META["web"]["project"]
    fp = delivery.repo_fingerprint(project, "devops")
    existing = {"issues": [{"iid": 7, "state": "closed", "description": delivery.marker(fp),
                            "title": "t"}], "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, existing, "root/drift-detector")
    devops = [i for i in plan["issues"] if i.get("stream") == "devops"]
    assert devops[0]["op"] == "update" and devops[0]["reopen"] is True


def test_resolved_finding_closes_its_issue():
    # an issue we filed whose fingerprint is no longer in the findings -> close
    ghost = {"issues": [{"iid": 9, "state": "opened",
                         "description": delivery.marker("deadbeefdeadbeef"), "title": "gone"}],
             "mrs": {}}
    plan = delivery.build_plan(_payload([_cve()]), _META, ghost, "root/drift-detector")
    ops = {i["op"] for i in plan["issues"]}
    assert "close" in ops
    assert next(i for i in plan["issues"] if i["op"] == "close")["iid"] == 9


def test_stale_in_repo_issue_closes_at_its_own_project():
    """DEFECT: _finish was hardcoding devops_project for all closes. When a repo's issue
    moved to its own project (Task 3), closing a stale in-repo finding would target
    devops_project with an iid that lives in a different project — wrong close or error.
    Proof: a stale developer issue for repo r_old with project_id="g/web" must close at
    "g/web", not at devops_project "g/ops"."""
    # Payload has actions for r_new only -> r_old's issue is stale
    payload = _payload([_sunset(repo="r_new")])

    # Existing issue for r_old:
    # - has a developer fingerprint marker (so it's tracked)
    # - iid=42, state=opened (not yet closed)
    # - project_id="g/web" (the repo's own project after Task 3)
    r_old_fp = delivery.repo_fingerprint("g/ebayapi", "developer")
    existing = {"issues": [
        {"iid": 42, "state": "opened",
         "description": delivery.marker(r_old_fp),
         "title": "[drift] API migrations for g/ebayapi",
         "project_id": "g/web"}  # issue lives in its own project
    ], "mrs": {}}

    plan = delivery.build_plan(payload, _META, existing, "g/ops",
                               assignees={"devops": None, "developer": {}})

    # Find the close op for the stale r_old issue
    closes = [i for i in plan["issues"] if i["op"] == "close" and i["iid"] == 42]
    assert len(closes) == 1, "Must have one close op for the stale issue"

    # BEFORE FIX: ["project"] would be "g/ops" (devops_project hardcoded)
    # AFTER FIX: ["project"] must be "g/web" (the issue's own project)
    assert closes[0]["project"] == "g/web", (
        f"Stale issue must close at its own project 'g/web', not devops_project 'g/ops'"
    )


def test_developer_stream_is_always_issues_never_mrs():
    """The draft-MR path is retired: developer findings are always ONE issue per repo, filed
    IN that repo (not a central devops project). `dev_as_issues` is accepted for back-compat
    but no longer forks behavior — passing it (or not) makes no difference."""
    for kwargs in ({}, {"dev_as_issues": True}, {"dev_as_issues": False}):
        plan = delivery.build_plan(_payload([_cve(), _sunset()]), _META,
                                   {"issues": [], "mrs": {}}, "root/drift-detector", **kwargs)
        assert plan["mrs"] == []                                  # no MRs, ever
        dev_issues = [i for i in plan["issues"] if i.get("stream") == "developer"]
        assert len(dev_issues) == 1                               # one per repo
        dev_issue = dev_issues[0]
        assert dev_issue["title"] == "🚨 [drift] API migrations for g/ebayapi"   # past-due sunset -> 🚨
        assert dev_issue["project"] == "g/ebayapi"                # in the repo, not central
        # idempotent: the per-repo issue carries the repo+audience marker
        assert delivery.repo_fingerprint("g/ebayapi", "developer") in dev_issue["body"]


def test_dev_as_issues_is_idempotent_across_reruns():
    """REGRESSION (task 2): build_plan's dev_as_issues branch was computing the OLD unnamespaced
    fingerprint while migrations_md embeds the NEW namespaced marker, breaking idempotency.
    Proof: run 1 creates a developer issue; run 2 with that same body must skip (not close + create).
    Before fix: creates + closes (duplicate every re-scan). After fix: skip (idempotent)."""
    a = _sunset()                                           # one developer action

    # RUN 1: no existing issues -> creates
    plan1 = delivery.build_plan(_payload([a]), _META, {"issues": [], "mrs": {}},
                                "root/drift-detector", dev_as_issues=True)
    assert len(plan1["issues"]) == 1
    dev_issue_1 = plan1["issues"][0]
    assert dev_issue_1["op"] == "create"
    captured_body = dev_issue_1["body"]

    # RUN 2: same payload, but now the issue exists with the captured body
    existing = {"issues": [{"iid": 1, "state": "opened",
                           "description": captured_body,
                           "title": dev_issue_1["title"]}], "mrs": {}}
    plan2 = delivery.build_plan(_payload([a]), _META, existing,
                                "root/drift-detector", dev_as_issues=True)

    # Must be idempotent: skip the issue, don't close it
    assert len(plan2["issues"]) == 1
    assert plan2["issues"][0]["op"] == "skip" and plan2["issues"][0]["iid"] == 1
    # Ensure there's no close op for this fingerprint
    closes = [i for i in plan2["issues"] if i["op"] == "close"]
    assert len(closes) == 0, f"Bug: re-run is closing the developer issue instead of skipping it"


def test_issue_bodies_link_back_to_the_run_and_report():
    """Provenance + hand-off: every issue footer links the scan run + the public Cockpit
    (`report` is now the GitHub Pages cockpit, relabelled from the old 'full report' readme).

    The mr_description half of this test went with the draft-MR path it covered."""
    links = {"run": "https://gh/run/1", "report": "https://TOPSinfo.github.io/drift-detector-scan/"}
    ib = delivery.issue_body(_cve(), "root/web", links)
    assert "[scan run](https://gh/run/1)" in ib
    assert "📊 [open the cockpit](https://TOPSinfo.github.io/drift-detector-scan/)" in ib


def test_developer_finding_with_no_known_project_falls_back_to_repo_name():
    """No more MR 'unroutable' path — the developer branch now always files an in-repo issue;
    lacking repo_meta it falls back to the raw repo identifier as the project, so a finding is
    never silently dropped."""
    plan = delivery.build_plan(_payload([_sunset(repo="mystery")]), {},  # no repo_meta
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    dev = [i for i in plan["issues"] if i.get("stream") == "developer"]
    assert len(dev) == 1 and dev[0]["project"] == "mystery"
    assert plan["mrs"] == []


def test_no_mrs_are_ever_planned_for_findings_even_with_a_pending_mr():
    """The draft-MR path is retired: even if a legacy MR already exists on the old
    drift/migrations branch, build_plan never plans against it — plan["mrs"] stays empty.

    Worth keeping after the MR code itself was deleted, because this is the property that made
    the deletion safe. If someone reintroduces MR planning, this fails and they have to argue
    for it deliberately rather than have it reappear as a side effect."""
    existing = {"issues": [], "mrs": {"g/ebayapi": [
        {"iid": 4, "source_branch": "drift/migrations", "state": "opened"}]}}
    plan = delivery.build_plan(_payload([_sunset()]), _META, existing, "root/drift-detector")
    assert plan["mrs"] == []


def test_issue_and_mr_bodies_carry_a_discovery_marker():
    a = _cve()
    assert delivery.action_fingerprint(a) in "".join(delivery.markers_in(delivery.issue_body(a)))
    md = delivery.migrations_md("ebayapi", [_sunset()])
    assert delivery.repo_fingerprint("ebayapi", "developer") in "".join(delivery.markers_in(md))


# --------------------------------------------------------------- execute (fake GitLab)
class _FakeGL:
    def __init__(self, default="main"):
        self.calls = []
        self._default = default
        self._branches = set()
        self._files = {}

    def project(self, p):
        return {"default_branch": self._default}

    def create_issue(self, p, **k):
        self.calls.append(("create_issue", p, k["title"]))

    def update_issue(self, p, iid, **k):
        self.calls.append(("update_issue", p, iid, k.get("state_event")))

    def branch(self, p, b):
        return {"name": b} if (p, b) in self._branches else None

    def create_branch(self, p, b, ref):
        self._branches.add((p, b))
        self.calls.append(("create_branch", p, b, ref))

    def get_file(self, p, path, ref):
        return self._files.get((p, path, ref))

    def set_file(self, p, path, *, branch, content, message, exists):
        self._files[(p, path, branch)] = content
        self.calls.append(("set_file", p, path, exists))

    def create_mr(self, p, **k):
        self.calls.append(("create_mr", p, k["title"], k["source_branch"]))

    def update_mr(self, p, iid, **k):
        self.calls.append(("update_mr", p, iid))


def test_execute_creates_devops_and_developer_issues_no_mrs():
    """The draft-MR path is retired: execute_plan on the new two-per-repo plan files only
    issues — no branch, file, or MR is ever created."""
    plan = delivery.build_plan(_payload([_cve(), _sunset()]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    gl = _FakeGL()
    done = delivery.execute_plan(gl, plan)
    kinds = [c[0] for c in gl.calls]
    assert kinds.count("create_issue") == 2           # one DevOps + one Developer issue
    assert "create_branch" not in kinds and "set_file" not in kinds and "create_mr" not in kinds
    assert done["created"] == 2


def test_cli_dry_run_produces_a_plan_and_writes_nothing(tmp_path, monkeypatch, capsys):
    import json
    from agent import cli
    from agent.lib import gitlab_api
    (tmp_path / "drift.json").write_text(json.dumps(
        _payload([_cve(repo="web"), _sunset(repo="ebayapi")])))
    (tmp_path / "inventory.json").write_text(json.dumps({"repos": [
        {"path": "web", "remote_url": "https://git.x/root/web"},
        {"path": "ebayapi", "remote_url": "https://git.x/g/ebayapi"}]}))

    class FakeGL:                                      # nothing filed yet
        def __init__(self, *a, **k): pass
        def list_issues(self, *a, **k): return []
        def list_mrs(self, *a, **k): return []
    monkeypatch.setattr(gitlab_api, "GitLab", FakeGL)
    rc = cli.main(["deliver", "--state", str(tmp_path), "--gitlab-host", "git.x",
                   "--devops-project", "root/drift-detector", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "create" in out
    assert "root/web" in out                          # DevOps issue filed IN the repo
    assert "g/ebayapi" in out                          # Developer issue filed IN the repo
    assert "dry run" in out


def test_cli_reads_host_project_and_mode_from_config(tmp_path, monkeypatch, capsys):
    import json
    from agent import cli
    from agent.lib import gitlab_api
    (tmp_path / "drift.json").write_text(json.dumps(_payload([_sunset(repo="ebayapi")])))
    (tmp_path / "inventory.json").write_text(json.dumps({"repos": [
        {"path": "ebayapi", "remote_url": "https://git.x/g/ebayapi"}]}))
    (tmp_path / "drift.yml").write_text(
        "fleet: [https://git.x/g/ebayapi]\n"
        "delivery:\n  mode: dry-run\n  devops_project: root/ops\n  dev_as_issues: true\n")

    class FakeGL:
        def __init__(self, host, *a, **k): FakeGL.host = host
        def list_issues(self, *a, **k): return []
        def list_mrs(self, *a, **k): return []
    monkeypatch.setattr(gitlab_api, "GitLab", FakeGL)
    rc = cli.main(["deliver", "--config", str(tmp_path / "drift.yml"),
                   "--state", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert FakeGL.host == "git.x"                    # host derived from the fleet in config
    assert "delivery mode: dry-run" in out and "dry run" in out
    assert "g/ebayapi" in out                        # developer issue filed IN the repo, not devops_project
    assert "Developer issues" in out                 # grouped under the developer stream header
    assert "draft MR" not in out                     # findings are always issues now, never MRs


def test_cli_config_mode_off_skips_delivery(tmp_path, capsys):
    import json
    from agent import cli
    (tmp_path / "drift.json").write_text(json.dumps(_payload([])))
    (tmp_path / "inventory.json").write_text(json.dumps({"repos": []}))
    (tmp_path / "drift.yml").write_text(
        "fleet: [https://git.x/g/a]\ndelivery:\n  mode: off\n  devops_project: root/ops\n")
    rc = cli.main(["deliver", "--config", str(tmp_path / "drift.yml"), "--state", str(tmp_path)])
    assert rc == 0 and "off — skipping" in capsys.readouterr().out


# --------------------------------------------------------------- shape stream (absorption flags)
def _shape(repo, verdict="UNKNOWN", reasons=("config-driven-url",), fp="deadbeef00000000"):
    return {"repo": repo, "verdict": verdict, "reasons": list(reasons),
            "attributed": 3, "unattributedPaths": 5, "unresolvedSinks": 2,
            "languages": {"php": 40}, "residueFingerprint": fp}


def _pl_shapes(shapes, samples=None):
    return {"actions": [], "shapes": shapes, "residueSamples": samples or []}


def test_shape_stream_is_off_by_default():
    plan = delivery.build_plan(_pl_shapes([_shape("svc")]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    assert plan["issues"] == []                              # no flag unless the stream is on


def test_shape_stream_flags_each_unknown_repo_at_the_maintainer():
    shapes = [_shape("svc-a"), _shape("svc-b"), _shape("svc-c", verdict="KNOWN")]
    plan = delivery.build_plan(_pl_shapes(shapes), _META, {"issues": [], "mrs": {}},
                               "root/drift-detector", shape_stream=True)
    creates = [i for i in plan["issues"] if i["op"] == "create"]
    assert len(creates) == 2                                 # only the two UNKNOWN
    assert all(o["project"] == "root/drift-detector" for o in creates)   # aimed at us
    assert all(o.get("stream") == "shape" for o in creates)
    assert "absorption needed" in creates[0]["title"]


def test_shape_issue_body_carries_blindspots_fingerprint_and_bootstrap():
    samples = [{"repo": "svc", "loc": "src/A.php:12", "sample": "/v2/orders"}]
    plan = delivery.build_plan(_pl_shapes([_shape("svc")], samples), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector", shape_stream=True)
    body = plan["issues"][0]["body"]
    assert "deadbeef00000000" in body and "src/A.php:12" in body and "config-driven-url" in body
    assert "drift-absorb" in body and "DRIFT_OPS_DIR" in body     # the absorb bootstrap


def test_shape_flag_is_idempotent():
    sh = _shape("svc")
    first = delivery.build_plan(_pl_shapes([sh]), _META, {"issues": [], "mrs": {}},
                                "root/drift-detector", shape_stream=True)["issues"][0]
    existing = {"issues": [{"iid": 9, "state": "opened",
                            "description": first["body"], "title": first["title"]}], "mrs": {}}
    again = delivery.build_plan(_pl_shapes([sh]), _META, existing,
                                "root/drift-detector", shape_stream=True)
    assert again["issues"][0]["op"] == "skip"               # unchanged shape -> no rewrite


def test_shape_flag_closes_itself_when_the_repo_goes_known():
    fp = delivery.shape_fingerprint("svc")
    existing = {"issues": [{"iid": 9, "state": "opened", "description": delivery.marker(fp),
                            "title": "[drift] absorption needed: svc"}], "mrs": {}}
    plan = delivery.build_plan(_pl_shapes([_shape("svc", verdict="KNOWN")]), _META, existing,
                               "root/drift-detector", shape_stream=True)
    closes = [i for i in plan["issues"] if i["op"] == "close"]
    assert len(closes) == 1 and closes[0]["iid"] == 9       # KNOWN now -> flag closes


def test_shape_fingerprint_is_repo_keyed_and_distinct():
    assert delivery.shape_fingerprint("svc") == delivery.shape_fingerprint("svc")
    assert delivery.shape_fingerprint("svc") != delivery.repo_fingerprint("svc")


# ------------------------------------------------- freshness stream (catalog work-order)
def _cat(vendor, verdict="UNAUDITED", sites=4, checked=None):
    return {"vendor": vendor, "verdict": verdict, "callSites": sites, "checked": checked}


def _pl_catalog(records):
    return {"actions": [], "catalog": records, "generated": "2026-07-29"}


def test_freshness_stream_is_off_by_default():
    plan = delivery.build_plan(_pl_catalog([_cat("MyDeal")]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    assert plan["issues"] == []                       # no work-order unless the stream is on


def test_freshness_stream_files_one_work_order_for_the_due_vendors():
    """WIRING GAP (found in review): drift:freshness had a label and an execute_plan branch
    but NO producer — build_plan never set stream='freshness', so the maintainer's due-list
    lived only in a CLI nobody was required to run. With the stream on, the due vendors are
    filed as ONE maintainer work-order issue (the work-order is one queue, not one issue per
    vendor), auto-lane vendors (catalog-check re-fetches those) and CURRENT vendors excluded."""
    records = [_cat("MyDeal"),                          # portal-gated -> due
               _cat("Kogan", verdict="STALE", checked="2026-03-01"),
               _cat("Stripe", verdict="CURRENT", checked="2026-07-20"),   # fresh -> not due
               _cat("eBay", verdict="STALE")]           # auto lane -> catalog-check's job
    plan = delivery.build_plan(_pl_catalog(records), _META, {"issues": [], "mrs": {}},
                               "root/drift-detector", freshness_stream=True)
    creates = [i for i in plan["issues"] if i["op"] == "create"]
    assert len(creates) == 1                            # ONE work-order, not one per vendor
    op = creates[0]
    assert op.get("stream") == "freshness" and op["project"] == "root/drift-detector"
    assert "catalog freshness" in op["title"] and "2 vendor(s)" in op["title"]
    assert delivery.marker(delivery.freshness_fingerprint()) in op["body"]
    assert "MyDeal" in op["body"] and "Kogan" in op["body"]
    assert "Stripe" not in op["body"] and "eBay" not in op["body"]


def test_freshness_work_order_is_idempotent():
    records = [_cat("MyDeal")]
    first = delivery.build_plan(_pl_catalog(records), _META, {"issues": [], "mrs": {}},
                                "root/drift-detector", freshness_stream=True)["issues"][0]
    existing = {"issues": [{"iid": 7, "state": "opened",
                            "description": first["body"], "title": first["title"]}], "mrs": {}}
    again = delivery.build_plan(_pl_catalog(records), _META, existing,
                                "root/drift-detector", freshness_stream=True)
    assert again["issues"][0]["op"] == "skip"           # unchanged due-list -> no rewrite


def test_freshness_work_order_closes_itself_when_nothing_is_due():
    fp = delivery.freshness_fingerprint()
    existing = {"issues": [{"iid": 7, "state": "opened", "description": delivery.marker(fp),
                            "title": "[drift] catalog freshness: 1 vendor(s) due a re-check"}],
                "mrs": {}}
    plan = delivery.build_plan(_pl_catalog([_cat("MyDeal", verdict="CURRENT",
                                                 checked="2026-07-29")]), _META, existing,
                               "root/drift-detector", freshness_stream=True)
    closes = [i for i in plan["issues"] if i["op"] == "close"]
    assert len(closes) == 1 and closes[0]["iid"] == 7   # all CURRENT -> work-order closes


# --------------------------------------------------------- assignees (per-repo, in-repo issues)
def test_devops_is_one_issue_per_repo_in_repo_assigned():
    payload = _payload([
        {"owner": "devops", "repo": "r1", "kind": "eol", "ref": "php", "status": "DEPRECATED"},
        {"owner": "devops", "repo": "r1", "kind": "cve", "ref": "guzzle", "status": "DEPRECATED"}])
    repo_meta = {"r1": {"project": "g/r1"}}
    plan = delivery.build_plan(payload, repo_meta, {"issues": {}, "mrs": {}}, "g/ops",
                               dev_as_issues=True, assignees={"devops": 5, "developer": {}})
    devops_issues = [i for i in plan["issues"] if i.get("stream") == "devops"]
    assert len(devops_issues) == 1                      # ONE per repo, not per action
    it = devops_issues[0]
    assert it["project"] == "g/r1" and it["assignee"] == 5    # in-repo + assigned to DevOps acct
    assert "php" in it["body"] and "guzzle" in it["body"]     # comprehensive


def test_developer_issue_in_repo_assigned_to_owner_no_mrs():
    payload = _payload([{"owner": "developer", "repo": "r1", "kind": "sunset", "ref": "Catch",
                         "status": "DEPRECATED"}])
    repo_meta = {"r1": {"project": "g/r1"}}
    plan = delivery.build_plan(payload, repo_meta, {"issues": {}, "mrs": {}}, "g/ops",
                               dev_as_issues=True, assignees={"devops": 5, "developer": {"r1": 7}})
    dev = [i for i in plan["issues"] if i.get("stream") == "developer"]
    assert len(dev) == 1 and dev[0]["project"] == "g/r1" and dev[0]["assignee"] == 7
    assert plan["mrs"] == []                            # no finding MRs


def test_devops_and_developer_for_one_repo_have_distinct_fingerprints():
    payload = _payload([
        {"owner": "devops", "repo": "r1", "kind": "cve", "ref": "guzzle", "status": "DEPRECATED"},
        {"owner": "developer", "repo": "r1", "kind": "sunset", "ref": "Catch", "status": "DEPRECATED"}])
    plan = delivery.build_plan(payload, {"r1": {"project": "g/r1"}}, {"issues": {}, "mrs": {}}, "g/ops",
                               dev_as_issues=True, assignees={"devops": 5, "developer": {"r1": 7}})
    fps = {i["fp"] for i in plan["issues"] if i.get("stream") in ("devops", "developer")}
    assert len(fps) == 2                                # no collision between the two audiences


def test_assignee_defaults_to_none_when_no_assignees_given():
    """assignees is optional — omitting it entirely must not raise, and each op carries an
    explicit assignee=None rather than the key being missing."""
    plan = delivery.build_plan(_payload([_cve(), _sunset()]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    for it in plan["issues"]:
        assert it["assignee"] is None


def test_maintainer_streams_carry_the_shared_audience_tag():
    """Absorption (shape) and freshness both go to the maintainer, so both carry drift:maintainer
    AND their own stream tag; the DevOps finding stream stays separate."""
    from agent.lib.delivery import _issue_labels
    assert _issue_labels("shape") == "drift-detector,drift:maintainer,drift:shape"
    assert _issue_labels("freshness") == "drift-detector,drift:maintainer,drift:freshness"
    assert _issue_labels(None) == "drift-detector,drift:devops"        # DevOps default, no maintainer tag


def test_developer_stream_carries_its_own_label_not_maintainer():
    from agent.lib.delivery import _issue_labels
    assert _issue_labels("developer") == "drift-detector,drift:developer"


# --------------------------------------------------------------- pure helpers (new)
def test_resolve_owner_prefers_owner_then_maintainer_then_fallback():
    members = [{"id": 6, "username": "bo", "access_level": 40},   # Maintainer
               {"id": 5, "username": "ann", "access_level": 50}]  # Owner
    assert delivery.resolve_owner(members, 99) == 5                        # Owner (50) wins
    assert delivery.resolve_owner([{"id": 6, "access_level": 40}], 99) == 6   # Maintainer (40)
    assert delivery.resolve_owner([{"id": 7, "access_level": 30}], 99) == 99  # Developer -> fallback
    assert delivery.resolve_owner([], None) is None                       # nothing -> unassigned


def test_resolve_owner_is_deterministic_across_equal_access():
    members = [{"id": 8, "access_level": 50}, {"id": 3, "access_level": 50}]
    assert delivery.resolve_owner(members, None) == 3                      # lowest id among equal Owners


def test_repo_fingerprint_namespaced_by_stream_and_backcompat():
    assert delivery.repo_fingerprint("g/r") == delivery.repo_fingerprint("g/r", "")   # back-compat
    assert delivery.repo_fingerprint("g/r", "devops") != delivery.repo_fingerprint("g/r", "developer")


def test_devops_repo_body_bundles_actions_with_marker():
    acts = [{"kind": "eol", "ref": "php", "status": "DEPRECATED", "recommendation": "upgrade php"},
            {"kind": "cve", "ref": "guzzle", "status": "DEPRECATED"}]
    body = delivery.devops_repo_body("g/r", acts)
    assert "php" in body and "guzzle" in body
    assert delivery.marker(delivery.repo_fingerprint("g/r", "devops")) in body                  # idempotency marker present


# --------------------------------------------------------------- I/O: per-repo fetch + assignee on write
class _FakeAssigneeGL:
    """A distinct fake from the MR-era `_FakeGL` above (which tracks branch/file/MR calls) —
    this one models list_issues per-project + assignee_ids on create, for the in-repo delivery I/O."""
    def __init__(self, issues_by_project=None):
        self._issues = issues_by_project or {}
        self.created = []

    def list_issues(self, project, *, labels):
        return self._issues.get(project, [])

    def list_mrs(self, project, *, labels):
        return []

    def create_issue(self, project, *, title, description, labels, assignee_ids=None):
        self.created.append({"project": project, "assignee_ids": assignee_ids, "labels": labels})
        return {"iid": 1}

    def update_issue(self, project, iid, **fields):
        pass


def test_execute_plan_sends_assignee_ids():
    gl = _FakeAssigneeGL()
    delivery.execute_plan(gl, {"issues": [{"op": "create", "project": "g/r1", "title": "T", "body": "B",
                                           "assignee": 7, "stream": "developer"}], "mrs": []})
    assert gl.created[0]["assignee_ids"] == [7]
    assert "drift:developer" in gl.created[0]["labels"]


def test_fetch_existing_reads_each_repo_tracker():
    gl = _FakeAssigneeGL({"g/r1": [{"iid": 9, "description": "x"}], "g/ops": []})
    got = delivery.fetch_existing(gl, "g/ops", ["g/r1"])
    assert any(i["iid"] == 9 for i in got["issues"])         # the repo's own issue is seen


def test_execute_plan_reports_a_failed_file_without_aborting():
    """'Cannot see' != 'clean': a create that raises for one repo must land in done["failed"]
    and must NOT stop the remaining ops from being attempted."""
    class _Boom(_FakeAssigneeGL):
        def create_issue(self, project, **k):
            if project == "g/bad":
                raise RuntimeError("403")
            return super().create_issue(project, **k)
    gl = _Boom()
    done = delivery.execute_plan(gl, {"issues": [
        {"op": "create", "project": "g/bad", "title": "T", "body": "B", "stream": "devops"},
        {"op": "create", "project": "g/ok", "title": "T", "body": "B", "stream": "devops"}], "mrs": []})
    assert done["failed"] and done["failed"][0][0] == "g/bad"
    assert done["created"] == 1                       # g/ok still filed


def test_fetch_existing_keeps_project_id_on_raw_issue_dicts():
    """INTEGRATION: `_finish` reads iss.get("project_id") to close an in-repo issue at its own
    project (Task 3's fix) — fetch_existing must return the RAW issue dicts, not a stripped copy."""
    gl = _FakeAssigneeGL({"g/r1": [{"iid": 9, "description": "x", "project_id": "g/r1"}]})
    got = delivery.fetch_existing(gl, "g/ops", ["g/r1"])
    iss = next(i for i in got["issues"] if i["iid"] == 9)
    assert iss["project_id"] == "g/r1"


# ------------------------------------------------------------- Task 6: executor wiring (CLI)
def test_resolve_assignees_maps_devops_and_repo_owner():
    """A thin unit over the resolution the `deliver` executor performs before build_plan."""
    devops_id = 5
    members = [{"id": 7, "access_level": 50}]
    assignees = {"devops": devops_id, "developer": {"r1": delivery.resolve_owner(members, 99)}}
    assert assignees["devops"] == 5 and assignees["developer"]["r1"] == 7


class _FakeDeliverGL:
    """Models the pieces `_cmd_deliver` calls end-to-end: member/user lookups for assignee
    resolution, plus issue create — nothing pre-filed, so every op is a `create`. `_cmd_deliver`
    constructs its own instance internally, so tests recover it via `_last` (the class tracks
    the most recently constructed instance) rather than threading one in."""
    FAIL_PROJECT = None                                # set per-test to exercise done["failed"]
    _last = None

    def __init__(self, host, token=None, **k):
        self.host = host
        self.created = []
        type(self)._last = self

    def list_issues(self, *a, **k):
        return []

    def list_mrs(self, *a, **k):
        return []

    def members(self, project):
        return {"g/r1": [{"id": 7, "access_level": 50}]}.get(project, [])

    def user_id(self, username):
        return {"devopsuser": 5, "fallbackuser": 99}.get(username)

    def create_issue(self, project, *, title, description, labels, assignee_ids=None):
        if project == self.FAIL_PROJECT:
            raise RuntimeError("403 forbidden")
        self.created.append({"project": project, "assignee_ids": assignee_ids, "labels": labels})
        return {"iid": 1}


def _deliver_cfg(tmp_path, *, mode="live"):
    p = tmp_path / "drift.yml"
    p.write_text(
        "fleet: [https://git.x/g/r1]\n"
        f"delivery:\n  mode: {mode}\n"
        "  devops: { project: root/ops, assignee: devopsuser }\n"
        "  developer: { fallbackAssignee: fallbackuser }\n")
    return str(p)


def _deliver_state(tmp_path):
    import json
    (tmp_path / "drift.json").write_text(json.dumps(
        _payload([_cve(repo="r1"), _sunset(repo="r1")])))
    (tmp_path / "inventory.json").write_text(json.dumps({"repos": [
        {"path": "r1", "remote_url": "https://git.x/g/r1"}]}))


def test_cli_deliver_resolves_and_threads_devops_and_developer_assignees(tmp_path, monkeypatch):
    """A devops action -> the issue is assigned to the resolved DevOps account id; a developer
    action -> the issue is assigned to the resolved repo-owner id (Maintainer+ access), not the
    fallback (a real member exists)."""
    from agent import cli
    from agent.lib import gitlab_api
    _deliver_state(tmp_path)
    monkeypatch.setattr(gitlab_api, "GitLab", _FakeDeliverGL)

    rc = cli.main(["deliver", "--config", _deliver_cfg(tmp_path), "--state", str(tmp_path)])

    assert rc == 0
    created = _FakeDeliverGL._last.created
    devops_call = next(c for c in created if "drift:devops" in c["labels"])
    developer_call = next(c for c in created if "drift:developer" in c["labels"])
    assert devops_call["assignee_ids"] == [5]
    assert developer_call["assignee_ids"] == [7]


def test_cli_deliver_nonzero_exit_when_an_issue_fails_to_file(tmp_path, monkeypatch, capsys):
    """`done["failed"]` non-empty (a repo's issue couldn't be filed) must fail the command —
    the now-dead `plan["mrs"]` unroutable gate is retired; this replaces it."""
    from agent import cli
    from agent.lib import gitlab_api

    class _FailingGL(_FakeDeliverGL):
        FAIL_PROJECT = "g/r1"

    _deliver_state(tmp_path)
    monkeypatch.setattr(gitlab_api, "GitLab", _FailingGL)

    rc = cli.main(["deliver", "--config", _deliver_cfg(tmp_path), "--state", str(tmp_path)])
    err = capsys.readouterr().err

    assert rc == 3
    assert "g/r1" in err


# ── hygiene: dry-run output grouped by audience/stream; no dead MR fetch ──────────────
def test_plan_detail_groups_issues_by_stream_not_all_under_devops():
    plan = {"issues": [
        {"op": "create", "project": "g/r1", "title": "platform upkeep for g/r1", "stream": "devops"},
        {"op": "create", "project": "g/r1", "title": "API migrations for g/r1", "stream": "developer"},
    ], "mrs": []}
    out = delivery.plan_detail(plan)
    assert "DevOps issues" in out and "Developer issues" in out
    # the developer line must sit under the Developer header, not the DevOps one
    dev_hdr = out.index("Developer issues")
    assert out.index("API migrations for g/r1") > dev_hdr
    assert out.index("platform upkeep for g/r1") < dev_hdr        # devops line is above it
    assert "draft MR" not in out                                  # dead MR section gone


def test_plan_summary_breaks_down_by_stream():
    plan = {"issues": [{"op": "create", "stream": "devops"},
                       {"op": "skip", "stream": "developer"}], "mrs": []}
    s = delivery.plan_summary(plan)
    assert "devops" in s and "developer" in s


def test_per_problem_files_one_issue_per_action():
    # 3 developer actions in one repo -> 3 issues (not 1 comprehensive)
    payload = {"actions": [
        _act(repo="ebayapi", owner="developer", kind="sunset", ref="eBay", unit="GetCategories",
             status="DEPRECATED", date="2025-01-01", worst="SUNSET"),
        _act(repo="ebayapi", owner="developer", kind="sunset", ref="eBay", unit="GetCharities",
             status="DEPRECATED", date="2023-09-18", worst="SUNSET"),
        _act(repo="ebayapi", owner="developer", kind="sunset", ref="eBay", unit="AddDispute",
             status="DEPRECATED", date="2023-01-31", worst="SUNSET")]}
    plan = delivery.build_plan(payload, {"ebayapi": {"project": "r/ebayapi"}},
                               {"issues": []}, "g/ops", granularity="per-problem")
    creates = [o for o in plan["issues"] if o["op"] == "create"]
    assert len(creates) == 3
    # each keyed by its own action_fingerprint (idempotent per problem)
    fps = {delivery.markers_in(o["body"]).pop() for o in creates}
    assert len(fps) == 3
    # emoji title — a past-due sunset leads with the siren
    assert all(o["title"].startswith("🚨") for o in creates)


def test_per_problem_is_idempotent_and_updates_in_place():
    payload = {"actions": [_act(repo="ebayapi", owner="developer", kind="sunset", ref="eBay",
                 unit="GetCategories", status="DEPRECATED", date="2025-01-01", worst="SUNSET")]}
    fp = delivery.action_fingerprint(payload["actions"][0])
    existing = {"issues": [{"iid": 7, "project_id": "r/ebayapi", "state": "opened",
                            "description": delivery.marker(fp)}]}
    plan = delivery.build_plan(payload, {"ebayapi": {"project": "r/ebayapi"}}, existing,
                               "g/ops", granularity="per-problem")
    ops = [o["op"] for o in plan["issues"]]
    assert "update" in ops and "create" not in ops        # matched by marker -> update


def test_per_vendor_groups_by_vendor():
    payload = {"actions": [
        _act(repo="r", owner="developer", kind="sunset", ref="eBay", unit="A", status="DEPRECATED",
             date="2025-01-01", worst="SUNSET"),
        _act(repo="r", owner="developer", kind="sunset", ref="eBay", unit="B", status="DEPRECATED",
             date="2025-01-01", worst="SUNSET"),
        _act(repo="r", owner="developer", kind="sunset", ref="Amazon SP-API", unit="/c/v0",
             status="DEPRECATED", date="2025-01-01", worst="SUNSET")]}
    plan = delivery.build_plan(payload, {"r": {"project": "g/r"}}, {"issues": []}, "g/ops",
                               granularity="per-vendor")
    creates = [o for o in plan["issues"] if o["op"] == "create"]
    assert len(creates) == 2                               # eBay + Amazon, one each


def test_comprehensive_is_unchanged_default():
    payload = {"actions": [_act(repo="r", owner="developer", kind="sunset", ref="eBay", unit="A",
                 status="DEPRECATED", date="2025-01-01", worst="SUNSET"),
               _act(repo="r", owner="developer", kind="sunset", ref="eBay", unit="B",
                 status="DEPRECATED", date="2025-01-01", worst="SUNSET")]}
    plan = delivery.build_plan(payload, {"r": {"project": "g/r"}}, {"issues": []}, "g/ops")
    creates = [o for o in plan["issues"] if o["op"] == "create"]
    assert len(creates) == 1                               # one comprehensive developer issue
    assert creates[0]["title"].startswith("🚨")            # emoji now on comprehensive titles too


def test_fetch_existing_does_not_fetch_dead_mrs():
    class _GL:
        def __init__(self): self.mr_calls = 0
        def list_issues(self, p, *, labels): return []
        def list_mrs(self, p, *, labels): self.mr_calls += 1; return []
    gl = _GL()
    got = delivery.fetch_existing(gl, "g/ops", ["g/r1", "g/r2"])
    assert got["mrs"] == {} and gl.mr_calls == 0                  # no wasted list_mrs I/O


# --------------------------------------------- "Open in Claude" + Cockpit footer (issue hand-off)
import urllib.parse as _uparse


def test_issue_body_carries_claude_cockpit_and_scanrun_links():
    a = _act(ref="eBay", unit="GetCategoryFeatures", status="DEPRECATED", date="2026-06-04",
             recommendation="migrate to the Taxonomy API",
             files=[{"loc": "src/Ebay/Cat.php:72", "href": "https://git.x/g/r/-/blob/a/src/Ebay/Cat.php#L72"}],
             sources=["https://developer.ebay.com/x"])
    links = {"report": "https://TOPSinfo.github.io/drift-detector-scan/",
             "run": "https://github.com/TOPSinfo/drift-detector-scan/actions/runs/1"}
    body = delivery.issue_body(a, "example-org/ebayapi", links)
    # all three hand-off links present, cockpit relabelled (no 'full report'/readme wording)
    assert "🤖 [Open in Claude](https://claude.ai/code?prompt=" in body
    assert "📊 [open the cockpit](https://TOPSinfo.github.io/drift-detector-scan/)" in body
    assert "[scan run](https://github.com/TOPSinfo/drift-detector-scan/actions/runs/1)" in body
    assert "full report" not in body


def test_claude_url_prefills_the_finding_context():
    a = _act(ref="eBay", unit="GetCategoryFeatures", status="DEPRECATED", date="2026-06-04",
             recommendation="migrate to the Taxonomy API",
             files=[{"loc": "src/Ebay/Cat.php:72", "href": "h"}],
             sources=["https://developer.ebay.com/x"])
    url = delivery._claude_url(a, "example-org/ebayapi")
    assert url.startswith("https://claude.ai/code?prompt=")
    prompt = _uparse.unquote(url.split("prompt=", 1)[1])
    # the whole picture is in the prompt: api + status/date + repo + call-site + recommendation + source
    assert "eBay GetCategoryFeatures" in prompt
    assert "2026-06-04" in prompt and "DEPRECATED" in prompt
    assert "example-org/ebayapi" in prompt
    assert "src/Ebay/Cat.php:72" in prompt
    assert "Taxonomy API" in prompt and "developer.ebay.com" in prompt
    assert "migration plan" in prompt.lower()


def test_footer_omits_claude_when_no_action_context():
    # aggregate/maintainer bodies without a per-action url still render cleanly (no empty link)
    foot = delivery._footer({"report": "https://x.github.io/y/", "run": "https://ci/1"})
    assert "Open in Claude" not in foot
    assert "📊 [open the cockpit](https://x.github.io/y/)" in foot


def test_claude_link_does_not_change_the_fingerprint():
    # the hand-off link is body chrome — it must NOT perturb the idempotency marker
    a = _act()
    before = delivery.action_fingerprint(a)
    body = delivery.issue_body(a, "g/r", {"report": "https://x/y", "run": "https://ci/1"})
    assert before in body                                  # same marker as before the link existed
    assert delivery.markers_in(body) == {before}


# ── the vendor-queue stream: a detected host nobody has named ─────────────────────
# The scanner extracts EVERY url and surfaces the ones it cannot name as "unresolved".
# That queue was computed on every run and thrown away: it lived only in `drift-scan
# resolve`, a CLI nobody was required to run, and never reached an issue tracker. It went
# 28 hosts deep before anyone looked — among them a repo whose entire purpose was a
# marketplace integration, and a dead marketplace the catalog already held a closure for.
#
# Same shape as the freshness work-order: ONE issue for the whole queue, updating in place,
# closing itself when the queue empties. One issue per host would be a dozen tickets on
# first run and would train people to mute the label.

def _ep(domain, *, repo="svc", classified=False, host_class="api-lead", n=1):
    return {"domain": domain, "repo": repo, "classified": classified,
            "hostClass": host_class, "file_count": n,
            "files": [f"src/Client.php:{n}"], "vendor": None if not classified else "X"}


def _pl_eps(eps):
    return {"actions": [], "endpoints": eps, "generated": "2026-08-21"}


def test_vendor_queue_files_one_maintainer_issue_for_the_whole_queue():
    eps = [_ep("openapi-b-global.temu.com"), _ep("api.addressify.com.au"),
           _ep("c.dotwms.com", host_class="unclassified")]
    plan = delivery.build_plan(_pl_eps(eps), _META, {"issues": [], "mrs": {}},
                               "root/drift-detector", resolve_stream=True)
    creates = [i for i in plan["issues"] if i["op"] == "create"]
    assert len(creates) == 1, "one work-order, not one ticket per host"
    op = creates[0]
    assert op["project"] == "root/drift-detector"        # maintainer, never a client repo
    assert op.get("stream") == "resolve"
    assert "3" in op["title"]                            # the count is the headline
    for host in ("temu.com", "addressify", "dotwms"):
        assert host in op["body"], f"{host} must be named in the work-order"


def test_vendor_queue_ignores_hosts_that_are_not_candidate_integrations():
    """own-infra, CDNs and vendored libraries are already triaged away by hostClass. Listing
    them would bury the real leads — the queue's value is that every line is actionable."""
    eps = [_ep("api.addressify.com.au"),
           _ep("app.internal.example.com", host_class="own-infra"),
           _ep("cdn.example.com", host_class="asset-cdn"),
           _ep("api.stripe.com", classified=True)]
    plan = delivery.build_plan(_pl_eps(eps), _META, {"issues": [], "mrs": {}},
                               "root/drift-detector", resolve_stream=True)
    op = [i for i in plan["issues"] if i["op"] == "create"][0]
    assert "addressify" in op["body"]
    for absent in ("internal.example.com", "cdn.example.com", "api.stripe.com"):
        assert absent not in op["body"], f"{absent} is not a queued integration"


def test_an_empty_vendor_queue_files_nothing():
    plan = delivery.build_plan(_pl_eps([_ep("api.stripe.com", classified=True)]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector",
                               resolve_stream=True)
    assert [i for i in plan["issues"] if i["op"] == "create"] == []


def test_the_stream_is_off_unless_asked_for():
    """Existing deployments must not sprout a new issue stream on upgrade."""
    plan = delivery.build_plan(_pl_eps([_ep("openapi-b-global.temu.com")]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    assert plan["issues"] == []


def _blocked(vendor, sites, why):
    return {"vendor": vendor, "verdict": "BLOCKED", "callSites": sites,
            "checked": "2026-08-21", "blocked": why}


def test_blocked_stream_is_off_by_default():
    plan = delivery.build_plan(_pl_catalog([_blocked("Mirakl", 25, "portal is account-gated")]),
                               _META, {"issues": [], "mrs": {}}, "root/drift-detector")
    assert plan["issues"] == []


def test_blocked_stream_files_one_access_work_order():
    """BLOCKED is dropped by freshness.due_for_refresh on purpose — re-reading a gated page
    cannot clear it. That left the one verdict needing an OUTSIDE actor with no surface at all.
    This stream is that surface: ONE issue, its own label, aimed at whoever can supply access."""
    records = [_blocked("Mirakl", 25, "portal is account-gated"),
               _blocked("Temu", 1, "Seller Center requires an account"),
               _cat("UPS", sites=35),                                   # UNAUDITED -> freshness
               _cat("Stripe", verdict="CURRENT", checked="2026-07-20")]
    plan = delivery.build_plan(_pl_catalog(records), _META, {"issues": [], "mrs": {}},
                               "root/drift-detector", blocked_stream=True)
    creates = [i for i in plan["issues"] if i["op"] == "create"]
    assert len(creates) == 1
    op = creates[0]
    assert op.get("stream") == "blocked" and op["project"] == "root/drift-detector"
    assert "2 vendor(s)" in op["title"]
    assert "Mirakl" in op["body"] and "Temu" in op["body"]
    assert "UPS" not in op["body"]        # unaudited is research work, a different queue


def test_the_blocked_work_order_is_not_filed_when_nothing_is_blocked():
    """So the stream closes itself, like the others."""
    plan = delivery.build_plan(_pl_catalog([_cat("UPS", sites=35)]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector",
                               blocked_stream=True)
    assert [i for i in plan["issues"] if i["op"] == "create"] == []


def test_blocked_carries_its_own_label_beside_the_maintainer_tag():
    """Filters as maintainer work, but distinguishable — an admin chasing credentials should not
    have to read through repo-shape and research tasks to find theirs."""
    labels = delivery._issue_labels("blocked")
    assert delivery.MAINTAINER_LABEL in labels and delivery.BLOCKED_LABEL in labels


def test_the_blocked_work_order_appears_in_the_dry_run_view():
    """FOUND IN A LIVE RUN: build_plan emitted the access work-order and plan_detail dropped it
    on the floor. `_by_stream` buckets by the op's stream, but the printer iterates _STREAM_ORDER
    and silently skips any key missing from it — so a stream could be planned, labelled and
    FILED while being invisible in the dry-run review, which is the last checkpoint before
    delivery goes live. Silent omission is the worst possible failure for a review surface."""
    records = [_blocked("Mirakl", 25, "portal is account-gated")]
    plan = delivery.build_plan(_pl_catalog(records), _META, {"issues": [], "mrs": {}},
                               "root/drift-detector", blocked_stream=True)
    detail = delivery.plan_detail(plan)
    assert "access needed" in detail
    assert "Mirakl" in detail or "1 vendor(s)" in detail
    assert "blocked" in delivery.plan_summary(plan)


def test_every_stream_build_plan_can_emit_has_a_dry_run_heading():
    """The invariant behind the bug above, so the next stream cannot repeat it. Any stream name
    build_plan sets must be renderable; a missing heading is a KeyError at best and a silent
    disappearance at worst."""
    emitted = {"devops", "developer", "shape", "freshness", "resolve", "blocked", "closing"}
    assert emitted <= set(delivery._STREAM_ORDER), (
        f"streams with no dry-run ordering: {sorted(emitted - set(delivery._STREAM_ORDER))}")
    assert emitted <= set(delivery._STREAM_HEAD), (
        f"streams with no dry-run heading: {sorted(emitted - set(delivery._STREAM_HEAD))}")
