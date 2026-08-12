from agent.lib import classify_url, vendors as vendors_mod


def _vendors():
    return vendors_mod.load_vendors()


# Found by the AI cross-check plane and confirmed in code on a real repo: the scanner SAW these
# hosts but could not classify them, so they sat in `queued` and never reached the catalog layer.
# Detection is the gap here, not the retirement catalog.
def test_the_three_confirmed_integrations_classify():
    v = _vendors()
    assert classify_url.classify_host("api.justcall.io", v).vendor == "JustCall"
    assert classify_url.classify_host("hooks.zapier.com", v).vendor == "Zapier"
    assert classify_url.classify_host("login.microsoftonline.com", v).vendor == "Microsoft Identity"


# A dependency's published config enumerates these. Whether a code path selects them is a separate
# question from whether the code references them — classify them, then let the attestation layer
# say (honestly) that nobody has checked their retirement lists.
def test_the_ai_provider_hosts_classify():
    v = _vendors()
    for host, vendor in [("api.deepseek.com", "DeepSeek"), ("api.groq.com", "Groq"),
                         ("api.mistral.ai", "Mistral AI"), ("api.x.ai", "xAI"),
                         ("openrouter.ai", "OpenRouter"), ("api.elevenlabs.io", "ElevenLabs"),
                         ("api.voyageai.com", "Voyage AI")]:
        got = classify_url.classify_host(host, v)
        assert got is not None and got.vendor == vendor, host


def test_new_vendors_are_unaudited_not_silently_current():
    """Classifying a vendor must NOT imply its retirements are checked. These ten have no
    attestation, so the catalog verdict stays UNAUDITED — 0 findings for them is not 'clean'."""
    from agent.lib import catalog_coverage
    att = catalog_coverage.load_attestations()
    for vendor in ("JustCall", "Zapier", "Microsoft Identity", "DeepSeek", "Groq",
                   "Mistral AI", "xAI", "OpenRouter", "ElevenLabs", "Voyage AI"):
        assert catalog_coverage.verdict_for(vendor, att, "2026-08-12")[0] == "UNAUDITED"
