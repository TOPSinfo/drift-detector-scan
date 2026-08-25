"""Human-attested terminal dispositions: INTERNAL and ACCEPTED.

Two cases can never be settled by reading a vendor's deprecation page, and until now both
rendered as UNAUDITED forever — a permanently non-empty work-order carrying tasks that can
never succeed, which is the same defect `BLOCKED` was introduced to fix one case earlier:

    INTERNAL   the library is built and operated in-house. There is no external vendor
               lifecycle, so the risk is genuinely ABSENT, not merely unchecked.
    ACCEPTED   an external vendor that publishes no findable retirement information. A human
               accepted the residual risk. The risk is REAL and still unmeasured.

They are deliberately two verdicts, not one with a flag. Collapsing them would render a live
exposure identically to a resolved one, which is principle 1 ("cannot see" != "clean") stated
one dimension over.

Both require a NAMED approver, because the whole point is that a person took responsibility.
"""
from agent.lib import catalog_coverage as cc


def _endpoint(vendor, n=1):
    # `file_count`, not `files` — build() sums the former. Getting this wrong made both
    # accounting tests below count zero call-sites and pass on `0 == 0`, proving nothing.
    return {"vendor": vendor, "classified": True, "file_count": n}


# ── INTERNAL — in-house, so there is nothing external to audit ──

def test_an_in_house_vendor_grades_internal_rather_than_unaudited():
    att = {"AcmeBilling": {"checked": "2026-08-24", "source": "", "note": "", "by": "human",
                           "blocked": "",
                           "disposition": "internal",
                           "approver": {"name": "Priya Shah", "role": "Head of Engineering",
                                        "basis": "Built and operated in-house; no external "
                                                 "vendor lifecycle applies."},
                           "expires": "2027-02-24"}}
    verdict, reasons, checked = cc.verdict_for("AcmeBilling", att, "2026-08-25")
    assert verdict == cc.INTERNAL
    assert reasons == [cc.IN_HOUSE]
    assert checked == "2026-08-24"


def test_an_expired_disposition_lapses_back_to_unaudited():
    """The expiry is the whole reason a signed judgement is allowed to resolve a vendor at all.
    Without a lapse, one person's say-so silences a vendor permanently and nothing ever
    re-examines it — which is how a tool starts lying quietly. Mirrors the waiver semantics
    designed in the strata spec 8.1: a waiver returns to the work-list when it lapses."""
    att = {"AcmeBilling": {"checked": "2026-08-24", "source": "", "note": "", "by": "human",
                           "blocked": "",
                           "disposition": "internal",
                           "approver": {"name": "Priya Shah", "role": "Head of Engineering",
                                        "basis": "Built in-house; no vendor lifecycle."},
                           "expires": "2027-02-24"}}
    assert cc.verdict_for("AcmeBilling", att, "2027-02-24")[0] == cc.INTERNAL   # on the day: still in force
    verdict, reasons, _ = cc.verdict_for("AcmeBilling", att, "2027-02-25")      # one day later
    assert verdict == cc.UNAUDITED
    assert reasons == [cc.DISPOSITION_LAPSED]


# ── the accounting difference, which is the whole reason these are two verdicts ──

def _att(vendor, disposition, expires="2027-02-24"):
    return {vendor: {"checked": "2026-08-24", "source": "", "note": "", "by": "human",
                     "blocked": "", "disposition": disposition,
                     "approver": {"name": "Priya Shah", "role": "Head of Engineering",
                                  "basis": "A stated basis of several words."},
                     "expires": expires}}


def test_internal_call_sites_stop_counting_as_unchecked_exposure():
    """In-house code has no external vendor lifecycle, so nobody is failing to check anything.
    Counting it would inflate the backlog with work that does not exist."""
    rows = cc.build([_endpoint("AcmeBilling", 5)], [], _att("AcmeBilling", "internal"), "2026-08-25")
    assert cc.summary(rows)["unauditedCallSites"] == 0


def test_accepted_call_sites_keep_counting_as_unchecked_exposure():
    """A human accepting the risk does not measure it. The vendor still publishes nothing, so
    those call-sites remain genuinely unchecked — exactly BLOCKED's rule (principle 1: naming
    why we are blind does not make us sighted)."""
    rows = cc.build([_endpoint("SomeVendor", 5)], [], _att("SomeVendor", "accepted"), "2026-08-25")
    assert cc.summary(rows)["unauditedCallSites"] == 5


# ── the wire form, and why it is nested ──
#
# The catalog overlay ships INDEPENDENTLY of the scanner, so a disposition entry WILL be read
# by scanners older than these verdicts. Encoded flat, an older loader ignores the keys it does
# not know, sees a complete attestation, and renders the vendor CURRENT — "checked, fine" —
# from data that says a human waived it. Nested under `internal:` / `accepted:`, an older
# loader finds no top-level checked/source, skips the entry, and falls back to UNAUDITED: it
# under-claims instead of over-claiming. This is BLOCKED's rule, applied to two more verdicts.

def _write(tmp_path, text):
    p = tmp_path / "att.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_a_nested_disposition_loads(tmp_path):
    path = _write(tmp_path, """
- vendor: AcmeBilling
  internal:
    since: '2026-08-24'
    approver:
      name: Priya Shah
      role: Head of Engineering
      basis: Built and operated in-house; no external vendor lifecycle applies.
    expires: '2027-02-24'
""")
    att = cc.load_attestations(path)
    assert cc.verdict_for("AcmeBilling", att, "2026-08-25")[0] == cc.INTERNAL


def test_the_flat_form_is_refused_not_merely_ignored(tmp_path):
    """Refused, so the unsafe encoding — which would mean two scanner versions reading opposite
    verdicts off the same bytes — cannot be committed back in quietly."""
    path = _write(tmp_path, """
- vendor: AcmeBilling
  checked: '2026-08-24'
  source: https://internal.example/billing
  disposition: internal
  approver:
    name: Priya Shah
    role: Head of Engineering
    basis: Built and operated in-house; no external vendor lifecycle applies.
  expires: '2027-02-24'
""")
    att = cc.load_attestations(path)
    # NOT merely "!= INTERNAL": left alone, the flat entry loads as an ordinary attestation and
    # grades CURRENT — the strongest claim in the vocabulary, from data saying a human waived
    # the vendor. Refusal is the only safe outcome.
    assert "AcmeBilling" not in att


def test_a_disposition_carrying_top_level_checked_is_refused(tmp_path):
    """The nested key is only safe if the entry ALSO omits top-level checked/source — that
    absence is exactly what makes an older loader skip it. An entry carrying both would be read
    as a plain CURRENT attestation by the older scanner, which is the bug the nesting prevents."""
    path = _write(tmp_path, """
- vendor: AcmeBilling
  checked: '2026-08-24'
  source: https://internal.example/billing
  internal:
    since: '2026-08-24'
    approver:
      name: Priya Shah
      role: Head of Engineering
      basis: Built and operated in-house; no external vendor lifecycle applies.
    expires: '2027-02-24'
""")
    att = cc.load_attestations(path)
    assert "AcmeBilling" not in att


# ── the gate: a disposition is refused unless a named person actually stands behind it ──
#
# `load_attestations` SKIPS a malformed entry, which is safe (the vendor stays UNAUDITED) but
# silent — a typo'd approver looks identical to no disposition at all, and the person who wrote
# it gets no signal. The gate refuses with a named reason instead, matching how every other
# gate in this tree behaves (resolve.check_verdicts, absorb.check_sunsets).

def _entry(**over):
    e = {"vendor": "AcmeBilling", "internal": {
        "since": "2026-08-24",
        "approver": {"name": "Priya Shah", "role": "Head of Engineering",
                     "basis": "Built and operated in-house; no external vendor lifecycle."},
        "expires": "2027-02-24"}}
    e["internal"].update(over.pop("internal", {}))
    e["internal"]["approver"].update(over.pop("approver", {}))
    e.update(over)
    return e


def test_a_well_formed_disposition_passes_the_gate():
    assert cc.check_dispositions([_entry()], now="2026-08-25") == []


def test_a_disposition_with_no_named_approver_is_refused():
    problems = cc.check_dispositions([_entry(approver={"name": ""})], now="2026-08-25")
    assert len(problems) == 1
    assert "name" in problems[0] and "AcmeBilling" in problems[0]


def test_a_disposition_with_no_role_is_refused():
    """A bare name is not accountability — 'who signed this' has to include what standing they
    had to sign it."""
    problems = cc.check_dispositions([_entry(approver={"role": "  "})], now="2026-08-25")
    assert len(problems) == 1
    assert "role" in problems[0]


def test_a_one_word_basis_is_refused():
    """'ours' is not a reason. The basis is the part a reader six months from now needs."""
    problems = cc.check_dispositions([_entry(approver={"basis": "ours"})], now="2026-08-25")
    assert len(problems) == 1
    assert "basis" in problems[0]


def test_a_disposition_that_expires_in_the_past_is_refused():
    """Signing something already lapsed means it never takes effect, which is a mistake worth
    reporting rather than a silent no-op."""
    problems = cc.check_dispositions([_entry(internal={"expires": "2026-01-01"})], now="2026-08-25")
    assert len(problems) == 1
    assert "expires" in problems[0]


def test_a_malformed_expiry_is_refused_rather_than_treated_as_forever():
    problems = cc.check_dispositions([_entry(internal={"expires": "next year"})], now="2026-08-25")
    assert len(problems) == 1
    assert "expires" in problems[0]


def test_a_disposition_record_carries_its_approver_and_expiry():
    """The digest has to name who signed and when it lapses. A verdict alone would make the
    sign-off unauditable from the report — the reader would have to go read the YAML to find
    out who stands behind it, which defeats the point of recording a person at all."""
    rows = cc.build([_endpoint("AcmeBilling", 3)], [], _att("AcmeBilling", "internal"), "2026-08-25")
    row = rows[0]
    assert row["approver"]["name"] == "Priya Shah"
    assert row["approver"]["role"] == "Head of Engineering"
    assert row["expires"] == "2027-02-24"


def test_an_ordinary_attestation_carries_no_approver_block():
    """Only signed dispositions have one. An empty approver on every row would make the digest
    render 'approved by —' beside 60 machine-checked vendors."""
    att = {"Adyen": {"checked": "2026-08-24", "source": "https://x", "note": "", "by": "ai-research"}}
    rows = cc.build([_endpoint("Adyen", 1)], [], att, "2026-08-25")
    assert "approver" not in rows[0]
    assert "expires" not in rows[0]
