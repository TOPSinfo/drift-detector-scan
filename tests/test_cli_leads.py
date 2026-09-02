import json
from agent import cli


def _state(tmp_path):
    drift = {"endpoints": [{"repo": "r1", "vendor": "eBay", "classified": True,
                            "domain": "api.ebay.com", "files": ["a.php:1"]}]}
    (tmp_path / "drift.json").write_text(json.dumps(drift))
    ai = {"meta": {"reposRead": 1, "tokens": 5}, "repos": [{"repo": "r1", "summary": "s",
          "integrations": [{"vendor": "Kogan", "host": "api.kgn.io", "endpoint": "x",
                            "file": "k.php", "line": "9", "retired": "unknown"}]}]}
    (tmp_path / "ai.json").write_text(json.dumps(ai))
    return str(tmp_path / "ai.json")


def test_leads_writes_a_versioned_document(tmp_path):
    ai = _state(tmp_path)
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai, "--now", "2026-08-12"])
    assert rc == 0
    doc = json.loads((tmp_path / "leads.json").read_text())
    assert doc["schema"] == "drift-leads/v1"
    assert doc["checked"] == "2026-08-12"
    assert doc["repos"][0]["integrations"][0]["vendor"] == "Kogan"
    assert set(doc["tally"]) == {"agree", "aiOnly", "toolOnly"}


def test_leads_writes_no_side_car_html(tmp_path):
    """The whole point of the change: one surface. A second dashboard must not reappear."""
    ai = _state(tmp_path)
    cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai, "--now", "2026-08-12"])
    assert not (tmp_path / "probabilistic.html").exists()


def test_leads_refuses_a_date_in_a_lead(tmp_path):
    """A date is a CERTIFIED-tier claim. A lead may only say WHETHER something is retired —
    `retired` is the tri-state yes/no/unknown. Letting a date through here would route an
    ungated model-produced date into the same document the certified data lives in."""
    _state(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "2026-01-01"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2
    assert not (tmp_path / "leads.json").exists()


def test_leads_refuses_a_date_hidden_in_another_field(tmp_path):
    """F2: the date guard used to apply _DATEISH only to `retired`, but `retired` is already a
    strict tri-state (yes/no/unknown) — a date could never legally live there anyway. The real
    leak was a free-text field like `note`: {"retired":"yes","note":"Sunset on 2026-03-01 per the
    changelog"} sailed straight through and rendered in the dashboard's Evidence column. The
    guard must inspect every string value of the record, not just one field."""
    _state(tmp_path)
    bad = tmp_path / "bad3.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "yes",
         "note": "Sunset on 2026-03-01 per the changelog"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2
    assert not (tmp_path / "leads.json").exists()


def test_leads_refuses_a_month_name_date_hidden_in_a_note(tmp_path):
    """M2: `_DATEISH` matched only YYYY-MM-DD / YYYY/MM/DD, so a model that spells the date out
    in prose sailed straight through as an ungated date rendered in the Evidence column."""
    _state(tmp_path)
    for note in ("Sunset on March 1, 2026", "Sunset on 1 March 2026",
                 "Sunset on Mar 1, 2026", "Sunset on 1 Mar 2026"):
        bad = tmp_path / "bad_month.json"
        bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
            {"vendor": "Kogan", "host": "api.kgn.io", "retired": "yes", "note": note}]}]}))
        rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                       "--now", "2026-08-12"])
        assert rc == 2, f"{note!r} was not refused"
        assert not (tmp_path / "leads.json").exists()


def test_leads_refuses_a_ddmm_or_mmdd_date_hidden_in_a_note(tmp_path):
    """M2: `01/03/2026` (DD/MM/YYYY or MM/DD/YYYY) is a date just as much as `2026/01/03` is,
    but the old pattern anchored the 4-digit year to the FRONT only."""
    _state(tmp_path)
    bad = tmp_path / "bad_slash.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "yes",
         "note": "Sunset 01/03/2026"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2
    assert not (tmp_path / "leads.json").exists()


def test_leads_does_not_over_refuse_ordinary_notes_with_bare_years(tmp_path):
    """The date gate must not become so broad it rejects a legitimate lead — a bare year (no
    day/month attached) or a spec/RFC number is not a date claim and must still pass."""
    ai = _state(tmp_path)
    for note in ("v3 has been current since the 2019 rewrite", "see RFC 2606"):
        raw = json.loads(open(ai, encoding="utf-8").read())
        raw["repos"][0]["integrations"][0]["note"] = note
        bad = tmp_path / "ok_note.json"
        bad.write_text(json.dumps(raw))
        rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                       "--now", "2026-08-12"])
        assert rc == 0, f"{note!r} was wrongly refused"


def test_leads_refuses_a_non_tristate_retired(tmp_path):
    _state(tmp_path)
    bad = tmp_path / "bad2.json"
    bad.write_text(json.dumps({"meta": {}, "repos": [{"repo": "r1", "integrations": [
        {"vendor": "Kogan", "host": "api.kgn.io", "retired": "probably"}]}]}))
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(bad),
                   "--now", "2026-08-12"])
    assert rc == 2


def test_leads_keeps_the_existing_refusals(tmp_path):
    _state(tmp_path)
    (tmp_path / "malformed.json").write_text('{"not": "the shape"}')
    assert cli.main(["leads", "--state", str(tmp_path),
                     "--ai-results", str(tmp_path / "malformed.json"), "--now", "2026-08-12"]) == 2
    (tmp_path / "norepo.json").write_text(json.dumps({"meta": {}, "repos": [{"integrations": []}]}))
    assert cli.main(["leads", "--state", str(tmp_path),
                     "--ai-results", str(tmp_path / "norepo.json"), "--now", "2026-08-12"]) == 2


def test_leads_needs_a_prior_scan(tmp_path):
    ai = tmp_path / "ai.json"
    ai.write_text('{"meta":{},"repos":[]}')
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", str(ai),
                     "--now", "2026-08-12"]) == 2


def _ai_with(tmp_path, **fields):
    """One integration record with `fields` merged in, plus the drift.json it needs."""
    drift = {"endpoints": [{"repo": "r1", "vendor": "eBay", "classified": True,
                            "domain": "api.ebay.com", "files": ["a.php:1"]}]}
    (tmp_path / "drift.json").write_text(json.dumps(drift))
    rec = {"vendor": "Acme SP", "host": "api.acme.test", "file": "k.php",
           "line": "9", "retired": "unknown"}
    rec.update(fields)
    ai = {"meta": {"reposRead": 1, "tokens": 5},
          "repos": [{"repo": "r1", "summary": "s", "integrations": [rec]}]}
    p = tmp_path / "ai.json"
    p.write_text(json.dumps(ai))
    return str(p)


def test_a_dated_api_version_is_an_identifier_not_a_claim(tmp_path):
    """Amazon SP-API versions its endpoints BY DATE, so `2020-09-04` is the version's NAME. It
    exists in the source at the cited line and asserts nothing about the future. Refusing it made
    the gate unable to express a true lead about the product's flagship vendor — and the observed
    consequence was a model that rewrote the evidence until the gate accepted it."""
    ai = _ai_with(tmp_path, version="2020-09-04")
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai,
                     "--now", "2026-09-02"]) == 0


def test_an_endpoint_identifier_exemption_was_withdrawn_deliberately(tmp_path, capsys):
    """`endpoint` used to get the same identifier exemption as `version` — this exact path was
    accepted once. It was WITHDRAWN, not overlooked: no lexical rule can tell a real dated path
    segment apart from a claim written to look like one (`/2027-03-01/sunset-per-the-vendor-
    changelog` is the same shape and must also be refused, see the smuggling tests below). The
    fix is corroborating against the scanner's own observations, specced separately. A future
    reader must not "restore" this exemption as a bug fix — it is not one."""
    ai = _ai_with(tmp_path, endpoint="/feeds/2020-09-04/feeds/{feedId}")
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai,
                     "--now", "2026-09-02"]) == 2
    assert "carries a date" in capsys.readouterr().err


def test_a_v_prefixed_dated_version_is_an_identifier(tmp_path):
    ai = _ai_with(tmp_path, version="v2020-09-04")
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai,
                     "--now", "2026-09-02"]) == 0


def test_a_version_with_a_trailing_newline_is_not_an_exact_token(tmp_path, capsys):
    """`_VERSION_TOKEN` used to be `^...$` checked with `.match()`, and `$` matches just before a
    trailing newline — so `"2020-09-04\\n"` slipped through as though it were the bare token. The
    exemption must be for an EXACT identifier, not "starts and ends with one, modulo a newline"."""
    ai = _ai_with(tmp_path, version="2020-09-04\n")
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai,
                     "--now", "2026-09-02"]) == 2
    assert "carries a date" in capsys.readouterr().err


def test_prose_in_an_identifier_field_is_still_a_claim(tmp_path, capsys):
    """The exemption is a BARE TOKEN, not the field name. A sentence is an assertion wherever it
    sits, and this is the smuggling route the exemption must not open."""
    ai = _ai_with(tmp_path, version="retires 2027-03-01")
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai,
                     "--now", "2026-09-02"]) == 2
    assert "carries a date" in capsys.readouterr().err


def test_prose_in_an_endpoint_is_still_a_claim(tmp_path, capsys):
    ai = _ai_with(tmp_path, endpoint="sunsets 2026-03-01")
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai,
                     "--now", "2026-09-02"]) == 2
    assert "carries a date" in capsys.readouterr().err


def test_a_bare_date_in_a_note_is_still_refused(tmp_path, capsys):
    """`note` is prose by definition. A bare date there is a claim with the sentence omitted."""
    ai = _ai_with(tmp_path, note="2020-09-04")
    assert cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai,
                     "--now", "2026-09-02"]) == 2
    assert "carries a date" in capsys.readouterr().err


def test_a_date_wrapped_in_slashes_inside_an_endpoint_sentence_is_still_a_claim(tmp_path, capsys):
    """`_PATH_SEGMENT_DATE.sub` used to strip EVERY slash-bounded date out of the value before the
    remainder was checked for a date shape. Wrap the claim's date in a leading/trailing slash
    anywhere in a sentence and the substitution erases it, leaving no date behind to catch — the
    whole sentence then passed as though it were a bare identifier."""
    for endpoint in (
        "notice: /2027-03-01/ this API is retiring soon and will stop working",
        "sunset scheduled — /2027-03-01/ — please migrate before then",
    ):
        ai = _ai_with(tmp_path, endpoint=endpoint)
        rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai,
                       "--now", "2026-09-02"])
        assert rc == 2, f"{endpoint!r} was wrongly accepted"
        assert "carries a date" in capsys.readouterr().err


def test_a_second_dated_segment_appended_to_a_real_path_is_still_a_claim(tmp_path, capsys):
    """A real versioned path has exactly one dated segment. A second one tacked on is a claim
    riding along with the identifier, not part of it."""
    ai = _ai_with(tmp_path, endpoint="/feeds/2020-09-04/feeds/{feedId}/2026-03-01")
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai, "--now", "2026-09-02"])
    assert rc == 2
    assert "carries a date" in capsys.readouterr().err


def test_zero_width_space_cannot_stand_in_for_the_ascii_space_the_gate_looks_for(tmp_path, capsys):
    """A whitespace DENYLIST (`re.search(r"\\s", value)`) is not the same guard as an ALLOWLIST
    of real-path characters: `\\s` does not match the zero-width space (U+200B), so a sentence
    that substitutes U+200B for every ASCII space reads as "no whitespace" while still being
    prose to a reader. The gate must reject any character outside printable ASCII, not just the
    ones `\\s` happens to know about."""
    zwsp = "​"
    endpoint = zwsp.join(["notice:", "/2027-03-01/", "this", "API", "is", "retiring", "soon"])
    ai = _ai_with(tmp_path, endpoint=endpoint)
    rc = cli.main(["leads", "--state", str(tmp_path), "--ai-results", ai, "--now", "2026-09-02"])
    assert rc == 2
    assert "carries a date" in capsys.readouterr().err
