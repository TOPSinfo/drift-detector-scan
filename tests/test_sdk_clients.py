"""Guards the SDK-client bridge — surfacing an integration from a MANIFEST dependency when the
vendor's API is reached through an SDK (method chains / config URLs, no host literal). Closes the
`sdk-only-no-callsite` blind spot the AI plane surfaces (Twilio/SendGrid via composer.json) for the
deterministic scan. The dependency IS the read fact; attribution `sdk-client`, evidenced at the
manifest — never a fabricated call-site."""
from agent.lib import sdk_clients


def test_load_maps_packages_to_vendor_host():
    c = sdk_clients.load()
    assert c.get("composer/twilio/sdk", {}).get("vendor") == "Twilio"
    assert c["composer/twilio/sdk"]["host"] == "api.twilio.com"
    assert c.get("npm/@sendgrid/mail", {}).get("vendor") == "SendGrid"
    # Shopify SDK wrappers assemble {shop}.myshopify.com — no host literal; the package IS the
    # evidence (same pattern as twilio/sdk).
    assert c.get("composer/gnikyt/basic-shopify-api", {}).get("vendor") == "Shopify"
    assert c["composer/gnikyt/basic-shopify-api"]["host"] == "myshopify.com"
    assert c.get("composer/phpclassic/php-shopify", {}).get("vendor") == "Shopify"
    assert c.get("composer/shopifyextras/shopify-php-api-wrapper", {}).get("vendor") == "Shopify"
    assert c.get("composer/shopify/shopify-api", {}).get("vendor") == "Shopify"


def test_endpoints_for_emits_from_dependency():
    clients = {"composer/twilio/sdk": {"vendor": "Twilio", "host": "api.twilio.com"}}
    repo = {"sdks": [{"techKey": "lib:composer/twilio/sdk", "file": "composer.json"}]}
    eps = sdk_clients.endpoints_for(repo, clients)
    assert len(eps) == 1
    e = eps[0]
    assert e["vendor"] == "Twilio" and e["domain"] == "api.twilio.com"
    assert e["attribution"] == "sdk-client"
    assert e["files"] == ["composer.json"]


def test_ignores_unknown_and_nonlibrary_packages():
    clients = {"composer/twilio/sdk": {"vendor": "Twilio", "host": "api.twilio.com"}}
    repo = {"sdks": [{"techKey": "lib:composer/unknown/thing", "file": "composer.json"},
                     {"techKey": "framework:laravel"},          # not a lib: techKey
                     {"file": "composer.json"}]}                # no techKey at all
    assert sdk_clients.endpoints_for(repo, clients) == []


def test_one_endpoint_per_host_no_double_count():
    clients = {"composer/twilio/sdk": {"vendor": "Twilio", "host": "api.twilio.com"},
               "npm/twilio": {"vendor": "Twilio", "host": "api.twilio.com"}}
    repo = {"sdks": [{"techKey": "lib:composer/twilio/sdk", "file": "composer.json"},
                     {"techKey": "lib:npm/twilio", "file": "package.json"}]}
    assert len(sdk_clients.endpoints_for(repo, clients)) == 1   # two packages, one Twilio host
