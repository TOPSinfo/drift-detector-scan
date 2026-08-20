"""The Markdown view is agent-readable AND pipe-safe — the two properties that make it
trustworthy where HTML was not."""
from agent.lib import md_render as md


def _payload(**over):
    base = {
        "generated": "2026-07-21",
        "counts": {"fixes": 6, "sunsets": 8, "eol": 0, "critical": 0, "unaudited": 0,
                   "reposAffected": 1, "reposScanned": 1},
        "actions": [
            {"kind": "sunset", "ref": "Amazon SP-API", "unit": "/fba/inbound/v0",
             "status": "DEPRECATED", "date": "2025-01-21", "finding_count": 6,
             "files": [{"loc": "src/Api/FbaShipment.php:25"}]},
            {"kind": "sunset", "ref": "Amazon SP-API", "unit": "/orders/v0",
             "status": "REVIEW", "date": "2027-03-27", "finding_count": 6,
             "files": [{"loc": "src/Api/OrdersApi.php:38"}]},
        ],
        "coverageGrades": [{"repo": "amazonspapi", "grade": "HIGH", "attributed": 46,
                            "unattributedPaths": 0, "unresolvedSinks": 7}],
        "catalog": [{"vendor": "Amazon SP-API", "verdict": "CURRENT", "callSites": 272,
                     "catalogEntries": 8, "checked": "2026-07-20"}],
        "coverageNotes": ["Vendor API sunsets: curated catalog."],
    }
    base.update(over)
    return base


def test_own_infra_claims_are_named_not_silent():
    """F1: drift.md must say how many hosts were claimed as own-infra and by which signal — never
    a silent subtraction. Token and domain claims are counted separately since only the domain
    claim removed the host from the audit backlog."""
    p = _payload(endpoints=[
        {"domain": "api.hubspot.com", "hostClass": "own-infra", "classified": False,
         "ownInfraReason": "repo token 'hubspot'"},
        {"domain": "anything.devhost.io", "hostClass": "own-infra", "classified": False,
         "ownInfraReason": "git remote org domain 'devhost.io'"},
    ])
    out = md.render_markdown(p, "2026-07-21")
    assert "2 host(s) claimed as a repo's own infrastructure" in out
    assert "1 by git-remote org domain" in out
    assert "1 by repo-name token" in out


def test_no_own_infra_line_when_nothing_claimed():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "own infrastructure" not in out


def test_headline_names_the_past_due_alarm():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "1 of 2 retiring API surface(s) are already past" in out


def test_operation_appears_in_a_row_not_a_bare_vendor():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "Amazon SP-API /fba/inbound/v0" in out
    assert "Amazon SP-API /orders/v0" in out


def test_findings_split_into_the_two_owner_queues():
    """A mixed payload routes package/runtime work to the DevOps queue and API/framework
    work to the Developer queue — the split DevOps asked for."""
    p = _payload(actions=[
        {"kind": "cve", "ref": "composer/aws/aws-sdk-php", "unit": None, "owner": "devops",
         "status": "DEPRECATED", "date": None, "fix_version": "3.283",
         "finding_count": 4, "files": [{"loc": "composer.json:1"}]},
        {"kind": "eol", "ref": "php", "refKind": "runtime", "owner": "devops",
         "status": "DEPRECATED", "date": "2022-11-28", "finding_count": 1,
         "files": [{"loc": "composer.json:5"}]},
        {"kind": "eol", "ref": "laravel", "refKind": "framework", "owner": "developer",
         "status": "REVIEW", "date": "2025-02-01", "finding_count": 1,
         "files": [{"loc": "composer.json:6"}]},
        {"kind": "sunset", "ref": "eBay", "unit": "GetCategories", "owner": "developer",
         "status": "DEPRECATED", "date": "2025-01-01", "finding_count": 1,
         "files": [{"loc": "src/Ebay.php:9"}]},
    ], counts={"fixes": 3, "sunsets": 1, "pastDue": 1, "eol": 2, "critical": 0,
               "unaudited": 0, "reposAffected": 1, "reposScanned": 1})
    out = md.render_markdown(p, "2026-07-21")
    devops, dev = out.index("## DevOps queue"), out.index("## Developer queue")
    assert devops < dev                                          # DevOps queue first
    # package + runtime land under DevOps; sunset + framework under Developer
    assert out.index("composer/aws/aws-sdk-php") < dev
    assert out.index("### Runtime end-of-life") < dev
    assert out.index("### Vendor API sunsets") > dev
    assert out.index("### Framework end-of-life") > dev
    assert out.rindex("eBay GetCategories") > dev              # the row, under Developer


def test_every_finding_has_its_own_date_column():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "2025-01-21" in out and "2027-03-27" in out


def test_pipe_in_a_cell_is_escaped_not_column_breaking():
    """The bug class: an unescaped | silently truncates a GitHub table row. A version
    constraint like `~5.6.0|7.0.2` must not add phantom columns."""
    p = _payload(actions=[{"kind": "cve", "ref": "composer/acme/x", "unit": None,
                           "status": "DEPRECATED", "date": None, "fix_version": "~5.6.0|7.0.2",
                           "finding_count": 1, "files": [{"loc": "composer.json:1"}]}],
                 counts={"fixes": 1, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                         "reposAffected": 1, "reposScanned": 1})
    out = md.render_markdown(p, "2026-07-21")
    # the raw pipe must be backslash-escaped so the cell stays one column
    assert "~5.6.0\\|7.0.2" in out
    assert "~5.6.0|7.0.2" not in out.replace("\\|", "")   # no unescaped pipe survived


def test_timeline_section_comes_after_the_report():
    out = md.render_markdown(_payload(), "2026-07-21")
    ti = out.index("## Retirement timeline")
    assert ti > out.index("## Summary")                        # AFTER the report, not before
    assert "gantt" in out[ti:]
    from agent.lib.verify import check_mermaid_wellformed
    check_mermaid_wellformed(out)                              # stays mermaid-wellformed


def test_coverage_verdicts_render():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "CURRENT" in out and "HIGH" in out
    assert "have we checked the retirement list?" in out


def test_clean_repo_says_no_action_required_not_a_false_alarm():
    p = _payload(actions=[], counts={"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0,
                                     "unaudited": 0, "reposAffected": 0, "reposScanned": 2})
    out = md.render_markdown(p, "2026-07-21")
    assert "No action-required findings across 2 repo(s)" in out


def test_deterministic():
    assert md.render_markdown(_payload(), "2026-07-21") == md.render_markdown(_payload(), "2026-07-21")


def test_front_matter_self_identifies_the_source():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert out.startswith("---\n")
    assert "schemaVersion: drift/v1" in out
    assert "generatedFrom: drift.json" in out


# ------------------------------------------------- the parity check (the trust mechanism)
def test_parity_holds_on_the_real_render():
    from agent.lib.verify import check_md_matches_payload
    out = md.render_markdown(_payload(), "2026-07-21")
    check_md_matches_payload(out, _payload())          # must not raise


def test_parity_catches_a_summary_number_that_drifts():
    """If the Markdown's summary disagrees with the payload counts, it must fail —
    this is bug #1's class (a tile/number contradicting the data) in the MD."""
    import pytest
    from agent.lib.verify import check_md_matches_payload, Violation
    out = md.render_markdown(_payload(), "2026-07-21")
    tampered = out.replace("| Vendor API sunsets | 8 |", "| Vendor API sunsets | 1 |")
    with pytest.raises(Violation) as e:
        check_md_matches_payload(tampered, _payload())
    assert e.value.check == "md-summary-parity"


def test_parity_catches_an_unescaped_pipe_truncation():
    """A raw | injected into a cell adds a phantom column — the exact GitHub
    silent-truncation bug — and must fail column integrity."""
    import pytest
    from agent.lib.verify import check_md_matches_payload, Violation
    out = md.render_markdown(_payload(), "2026-07-21")
    # forge a broken row: an unescaped pipe inside the findings-TABLE cell. Anchor on the
    # cell delimiters (`| … |`) so we corrupt the table row, not the identical vendor/unit
    # string that also appears in the prose "Most urgent" callout (which parity ignores).
    broken = out.replace("| Amazon SP-API /fba/inbound/v0 |",
                         "| Amazon SP-API /fba|inbound/v0 |", 1)
    assert broken != out                                   # the anchor must have matched
    with pytest.raises(Violation):
        check_md_matches_payload(broken, _payload())


def test_parity_catches_two_identical_findings_rows():
    import pytest
    from agent.lib.verify import check_md_matches_payload, Violation
    # two sunset actions with the SAME label + date + everything = indistinguishable rows
    dup = {"kind": "sunset", "ref": "eBay", "unit": None, "status": "DEPRECATED",
           "date": "2022-04-30", "finding_count": 1, "files": [{"loc": "a.php:1"}]}
    p = _payload(actions=[dict(dup), dict(dup)],
                 counts={"fixes": 2, "sunsets": 2, "eol": 0, "critical": 0, "unaudited": 0,
                         "reposAffected": 1, "reposScanned": 1})
    out = md.render_markdown(p, "2026-07-21")
    with pytest.raises(Violation) as e:
        check_md_matches_payload(out, p)
    assert e.value.check == "md-row-identity"


# ------------------------------------------------- the mermaid exposure graph
def test_retirement_timeline_gantt_is_emitted_and_marks_overdue():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "```mermaid" in out and "gantt" in out
    # a past-due surface is a crit milestone, a future one is active
    assert "/fba/inbound/v0 :crit, milestone, 2025-01-21" in out
    assert "/orders/v0 :active, milestone, 2027-03-27" in out


def test_graph_labels_are_sanitized_against_grammar_breakers():
    """A family with grammar-breaking chars must not produce a raw label — that would
    render a Mermaid error box that looks fine in source."""
    p = _payload(actions=[{"kind": "sunset", "ref": "Vendor", "unit": '/a/{id}/"x"',
                           "status": "DEPRECATED", "date": "2024-01-01", "finding_count": 1,
                           "files": [{"loc": "a.php:1"}]}],
                 counts={"fixes": 1, "sunsets": 1, "eol": 0, "critical": 0, "unaudited": 0,
                         "reposAffected": 1, "reposScanned": 1})
    out = md.render_markdown(p, "2026-07-21")
    # the gantt label strips grammar-breakers (':' would split the milestone spec; a raw
    # '"'/'{' would draw an error box that looks fine in source)
    line = next(ln for ln in out.splitlines() if "milestone, 2024-01-01" in ln)
    assert '"' not in line and "{" not in line and "}" not in line


def test_mermaid_wellformed_passes_on_the_real_render():
    from agent.lib.verify import check_mermaid_wellformed
    check_mermaid_wellformed(md.render_markdown(_payload(), "2026-07-21"))


def test_mermaid_check_catches_an_edge_to_an_undeclared_node():
    import pytest
    from agent.lib.verify import check_mermaid_wellformed, Violation
    broken = '```mermaid\nflowchart LR\n  r0["repo"]\n  r0 --> n9\n```\n'
    with pytest.raises(Violation) as e:
        check_mermaid_wellformed(broken)
    assert e.value.check == "mermaid-undeclared-node"


def test_no_graph_when_nothing_is_retiring():
    p = _payload(actions=[], counts={"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0,
                                     "unaudited": 0, "reposAffected": 0, "reposScanned": 1})
    assert "```mermaid" not in md.render_markdown(p, "2026-07-21")


def test_same_finding_in_two_repos_renders_distinct_rows_by_repo():
    """A vendored SDK (or shared runtime) appears in several repos with an IDENTICAL
    repo-relative call-site. Without the Repo column those rows render byte-identical and
    md-row-identity rejects the report; with it, each repo's exposure is its own row."""
    from agent.lib.verify import check_md_matches_payload
    dup = dict(kind="sunset", ref="Amazon SP-API", unit="/catalog/v0", status="DEPRECATED",
               date="2026-06-30", finding_count=1, files=[{"loc": "src/Api/Catalog.php:1"}])
    p = _payload(actions=[{**dup, "repo": "repoA"}, {**dup, "repo": "repoB"}],
                 counts={"fixes": 2, "sunsets": 2, "eol": 0, "critical": 0, "unaudited": 0,
                         "reposAffected": 2, "reposScanned": 2})
    out = md.render_markdown(p, "2026-07-21")
    check_md_matches_payload(out, p)                       # must NOT raise now
    # two TABLE rows (lines starting with |), identical but for the Repo column
    rows = [ln for ln in out.splitlines() if ln.startswith("| ") and "/catalog/v0" in ln]
    assert len(rows) == 2 and rows[0] != rows[1]
    assert "| repoA |" in out and "| repoB |" in out


def test_findings_tables_lead_with_repo():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "| Repo | API | Status | Retires | Call-sites | First call-site |" in out


def test_unscannable_roots_are_surfaced_high_in_the_report():
    """A source requested but unreadable must appear in the report — 'cannot see' is not
    'clean'. The bug: inventory recorded it, drift.md dropped it, the report looked green."""
    p = _payload(rootsUnscannable=[{"root": "https://git.x/team/ghost",
                                    "reason": "GitLab group '…/ghost' has no active projects"}],
                 counts={**_payload()["counts"], "unscannable": 1})
    out = md.render_markdown(p, "2026-07-21")
    assert "Couldn't scan" in out
    assert "https://git.x/team/ghost" in out
    # it sits BEFORE the findings queues, not buried at the end
    assert out.index("Couldn't scan") < out.index("## Summary")


def test_no_couldnt_scan_section_when_everything_was_read():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "Couldn't scan" not in out


def test_a_pipe_in_an_unscannable_reason_is_escaped():
    p = _payload(rootsUnscannable=[{"root": "https://git.x/a", "reason": "bad | reason"}],
                 counts={**_payload()["counts"], "unscannable": 1})
    out = md.render_markdown(p, "2026-07-21")
    assert "bad \\| reason" in out


# ------------------------------------------------- the coverage tree
def test_markdown_carries_the_coverage_tree():
    """The tree is a projection like every other surface: rendered from the payload here (not
    the browser) so `verify` can check it against drift.json. This file has no dedicated
    counts.coverage fixture, so build one inline mirroring a real scan's shape."""
    p = _payload(counts={**_payload()["counts"],
                         "detected": 73, "integrations": 30, "excluded": 43, "apis": 21,
                         "coverage": {"tracked": 27, "queued": 3, "needs-human": 0,
                                     "blocked": 0, "na": 43}})
    out = md.render_markdown(p, "2026-07-21")
    assert "## Coverage tree" in out
    assert "detected" in out and "├─" in out
    # sits after the Summary table, before the coverage-verdicts section
    assert out.index("## Summary") < out.index("## Coverage tree") < out.index("## Coverage — what the scan is sure of")


def test_coverage_tree_labels_cannot_break_out_of_the_fence():
    """Reviewer repro: a hostile hostClass label (`own-infra```\\n\\n# INJECTED`) breaks out of
    the fenced code block and injects arbitrary Markdown into drift.md. Not reachable through
    classify() today — host_class.classify() only returns closed-VOCAB values — but that
    guarantee lives one layer away, and the tree is the thing writing the file, so it must
    render honestly even for a payload it should never see."""
    hostile = "own-infra```\n\n# INJECTED"
    p = _payload(counts={**_payload()["counts"],
                         "detected": 4, "integrations": 1, "excluded": 3, "apis": 1,
                         "coverage": {"tracked": 1, "queued": 0, "needs-human": 0,
                                     "blocked": 0, "na": 3}},
                 endpoints=[{"domain": "h.example.test", "hostClass": hostile, "coverage": "na"}
                            for _ in range(3)])
    out = md.render_markdown(p, "2026-07-21")
    start = out.index("## Coverage tree")
    end = out.index("## Coverage — what the scan is sure of")
    section = out[start:end]
    # exactly the tree's own opening and closing fence — never a third from the hostile label
    assert section.count("```") == 2
    # the label's own text may still appear (rendering is honest), but never as an injected
    # heading on its own line — that's what "broke out of the fence" means
    assert "\n# INJECTED" not in section
    assert "\n\n# INJECTED" not in out


def test_call_sites_column_reports_the_true_total_not_the_capped_list_length():
    """REGRESSION (2026-08-20): the column is headed "Call-sites", and it was computed as
    len(files) — a list deliberately capped at 6. A repo with 22 call-sites on a retired
    Shopify version therefore rendered "6". The number a reader uses to size the work must
    come from file_count, not from however many locs we chose to print."""
    p = _payload(actions=[{"kind": "sunset", "ref": "Shopify", "unit": "2023-10",
                           "status": "RETIRED", "date": "2024-10-16", "finding_count": 1,
                           "file_count": 22,
                           "files": [{"loc": f"app/S{i}.php:{i}"} for i in range(6)]}])
    rows = [l for l in md.render_markdown(p, "2026-08-20").splitlines()
            if l.startswith("|") and "Shopify" in l and "2024-10-16" in l]
    row = rows[0]
    cells = [c.strip() for c in row.split("|")]
    assert "22" in cells, f"Call-sites column showed the capped length, not the total: {row}"


def test_call_sites_column_falls_back_when_file_count_is_absent():
    """Older payloads (and CVE actions built before this field existed) carry no file_count.
    They must keep rendering their previous number rather than a blank or a zero."""
    p = _payload()
    out = md.render_markdown(p, "2026-08-20")
    row = [l for l in out.splitlines()
           if l.startswith("|") and "/fba/inbound/v0" in l][0]
    assert "1" in [c.strip() for c in row.split("|")]


def test_parity_catches_a_call_sites_cell_that_understates_the_payload():
    """REGRESSION (2026-08-20): the Call-sites column was rendered from len(files) — a list
    capped at 6 — so a 22-call-site retirement published as "6" and verify said the report
    was self-consistent. It WAS consistent with the capped list; it disagreed with the data.
    A column that sizes a reader's work must be pinned to the payload, not to how many
    sample locs the renderer chose to print."""
    import pytest
    from agent.lib.verify import check_md_matches_payload, Violation
    p = _payload(actions=[{"kind": "sunset", "ref": "Shopify", "unit": "2023-10",
                           "repo": "example-org/inventory-app", "status": "RETIRED",
                           "date": "2024-10-16", "finding_count": 1, "file_count": 22,
                           "files": [{"loc": f"app/S{i}.php:{i}"} for i in range(6)]}])
    out = md.render_markdown(p, "2026-08-20")
    assert "| 22 |" in out
    tampered = out.replace("| 22 |", "| 6 |")          # exactly what the bug shipped
    with pytest.raises(Violation) as e:
        check_md_matches_payload(tampered, p)
    assert e.value.check == "md-call-site-parity"
