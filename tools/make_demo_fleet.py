"""Build a fictional customer fleet for documentation screenshots.

Repo and company names are invented. The VENDOR ENDPOINTS ARE REAL — they have to be, because
the scanner matches them against agent/vendors.yaml and dates them from agent/vendor_sunsets.yaml.
A made-up vendor would simply not be detected and the screenshots would be empty. Package
versions are likewise real, chosen because OSV has genuine advisories for them.

Every sunset referenced below is a real, catalogued retirement:
  Amazon MWS         *                          retired 2023-12-31
  eBay               svcs.ebay.com              retired 2025-02-05
  eBay               open.api.ebay.com          retired 2025-02-05
  Amazon SP-API      /reports/2020-09-04        retired 2024-06-27
  Amazon SP-API      /feeds/2020-09-04          retired 2024-06-27
  Walmart            /v3/insights/items/trending        retired 2025-03-31
  Walmart            /v3/insights/prosellerbadge        retired 2025-08-13
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])

PHP_EOL = '{"require": {"php": "^7.4", %s}}'
PHP_OK = '{"require": {"php": "^8.1", %s}}'


def php(*deps):
    return ", ".join(f'"{k}": "{v}"' for k, v in deps)


REPOS = {
    # ---- storefront + checkout ----------------------------------------------------------
    "northwind/checkout-api": {
        "manifest": ("composer.json", PHP_OK % php(("guzzlehttp/guzzle", "6.2.0"),
                                                   ("firebase/php-jwt", "5.0.0"),
                                                   ("monolog/monolog", "1.25.0"))),
        "files": {
            "src/Payments/StripeGateway.php": '''<?php
namespace Northwind\\Payments;

class StripeGateway
{
    private const CHARGES = "https://api.stripe.com/v1/charges";
    private const REFUNDS = "https://api.stripe.com/v1/refunds";

    public function capture(string $token, int $amountMinor): array
    {
        $ch = curl_init(self::CHARGES);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        return json_decode(curl_exec($ch), true);
    }

    public function refund(string $chargeId): array
    {
        return json_decode(file_get_contents(self::REFUNDS), true);
    }
}
''',
            "src/Tax/AvalaraClient.php": '''<?php
namespace Northwind\\Tax;

class AvalaraClient
{
    public function quote(array $lines): array
    {
        $url = "https://rest.avatax.com/api/v2/transactions/create";
        return json_decode(file_get_contents($url), true);
    }
}
''',
        },
    },
    "northwind/storefront-web": {
        "manifest": ("package.json", json.dumps({
            "name": "storefront-web", "private": True,
            "dependencies": {"axios": "0.21.1", "lodash": "4.17.11", "node-fetch": "2.6.0"}},
            indent=2)),
        "files": {
            "src/api/shopify.js": '''import axios from "axios";

const ADMIN = "https://northwind.myshopify.com/admin/api/2023-01/orders.json";
const STOREFRONT = "https://northwind.myshopify.com/api/2023-01/graphql.json";

export async function recentOrders() {
  const { data } = await axios.get(ADMIN);
  return data.orders;
}

export async function catalogue(query) {
  return fetch(STOREFRONT, { method: "POST", body: JSON.stringify({ query }) });
}
''',
            "src/api/search.js": '''import axios from "axios";

// legacy marketplace search — scheduled for removal, still wired to the old endpoint
const FINDING = "https://svcs.ebay.com/services/search/FindingService/v1";

export const findItems = (kw) => axios.get(`${FINDING}?keywords=${kw}`);
''',
        },
    },

    # ---- marketplace integrations -------------------------------------------------------
    "northwind/order-sync": {
        "manifest": ("package.json", json.dumps({
            "name": "order-sync", "private": True,
            "dependencies": {"axios": "0.27.2", "form-data": "4.0.0", "minimist": "1.2.0"}},
            indent=2)),
        "files": {
            "src/amazon/reports.js": '''import axios from "axios";

const BASE = "https://sellingpartnerapi-na.amazon.com";

// nightly settlement pull
export const requestReport = () =>
  axios.post(`${BASE}/reports/2020-09-04/reports`, { reportType: "GET_FLAT_FILE_ORDERS" });

export const reportDocument = (id) =>
  axios.get(`${BASE}/reports/2020-09-04/documents/${id}`);

export const submitFeed = (body) =>
  axios.post(`${BASE}/feeds/2020-09-04/feeds`, body);

// migrated already
export const listOrders = () => axios.get(`${BASE}/orders/v0/orders`);
''',
            "src/ebay/trading.js": '''import axios from "axios";

const SHOPPING = "https://open.api.ebay.com/shopping";
const SELL = "https://api.ebay.com/sell/fulfillment/v1/order";

export const item = (id) => axios.get(`${SHOPPING}?callname=GetSingleItem&ItemID=${id}`);
export const orders = () => axios.get(SELL);
''',
        },
    },
    "northwind/fulfilment-bridge": {
        "manifest": ("composer.json", PHP_EOL % php(("guzzlehttp/guzzle", "6.5.0"),
                                                    ("symfony/http-client", "4.4.0"))),
        "files": {
            "src/Mws/LegacyFeedClient.php": '''<?php
namespace Northwind\\Mws;

/**
 * Inherited from the 2019 platform. Still the only path that files inventory adjustments.
 */
class LegacyFeedClient
{
    private $endpoint = "https://mws.amazonservices.com/Feeds/2009-01-01";

    public function submitInventory(string $xml): string
    {
        return file_get_contents($this->endpoint);
    }

    public function reportStatus(): string
    {
        return file_get_contents("https://mws.amazonservices.co.uk/Reports/2009-01-01");
    }
}
''',
        },
    },
    "northwind/pricing-worker": {
        "manifest": ("composer.json", PHP_OK % php(("guzzlehttp/guzzle", "7.4.0"),
                                                   ("monolog/monolog", "2.3.0"))),
        "files": {
            "src/Walmart/InsightsClient.php": '''<?php
namespace Northwind\\Walmart;

class InsightsClient
{
    private const TRENDING = "/v3/insights/items/trending";
    private const BADGE = "/v3/insights/prosellerbadge";
    private const HOST = "https://marketplace.walmartapis.com";

    public function trending(): array
    {
        return json_decode(file_get_contents(self::HOST . self::TRENDING), true);
    }

    public function badge(): array
    {
        return json_decode(file_get_contents(self::HOST . self::BADGE), true);
    }

    public function items(): array
    {
        return json_decode(file_get_contents(self::HOST . "/v3/items"), true);
    }
}
''',
        },
    },
    "northwind/marketplace-listings": {
        "manifest": ("package.json", json.dumps({
            "name": "marketplace-listings", "private": True,
            "dependencies": {"axios": "1.2.1", "lodash": "4.17.20"}}, indent=2)),
        "files": {
            "src/bigcommerce.js": '''import axios from "axios";

const V2 = "https://api.bigcommerce.com/stores/nw1/v2/orders";
const V3 = "https://api.bigcommerce.com/stores/nw1/v3/catalog/products";

export const legacyOrders = () => axios.get(V2);
export const products = () => axios.get(V3);
''',
        },
    },

    # ---- logistics ----------------------------------------------------------------------
    "northwind/shipping-rates": {
        "manifest": ("composer.json", PHP_OK % php(("guzzlehttp/guzzle", "7.5.0"))),
        "files": {
            "src/Carriers/FedexClient.php": '''<?php
namespace Northwind\\Carriers;

class FedexClient
{
    public function rate(array $shipment): array
    {
        $url = "https://apis.fedex.com/rate/v1/rates/quotes";
        return json_decode(file_get_contents($url), true);
    }

    public function track(string $number): array
    {
        return json_decode(file_get_contents("https://apis.fedex.com/track/v1/trackingnumbers"), true);
    }
}
''',
            "src/Carriers/UpsClient.php": '''<?php
namespace Northwind\\Carriers;

class UpsClient
{
    public function rate(): array
    {
        return json_decode(file_get_contents("https://onlinetools.ups.com/api/rating/v1/Rate"), true);
    }
}
''',
        },
    },
    "northwind/warehouse-events": {
        "manifest": ("package.json", json.dumps({
            "name": "warehouse-events", "private": True,
            "dependencies": {"axios": "1.6.0", "ws": "7.4.0"}}, indent=2)),
        "files": {
            "src/notify.js": '''import axios from "axios";

const SMS = "https://api.twilio.com/2010-04-01/Accounts/ACxxxx/Messages.json";
const SLACK = "https://hooks.slack.com/services/T000/B000/xxxx";

export const smsPicker = (to, body) => axios.post(SMS, { To: to, Body: body });
export const alertOps = (text) => axios.post(SLACK, { text });
''',
        },
    },

    # ---- customer-facing ----------------------------------------------------------------
    "northwind/support-desk": {
        "manifest": ("package.json", json.dumps({
            "name": "support-desk", "private": True,
            "dependencies": {"axios": "1.4.0", "openai": "4.20.0"}}, indent=2)),
        "files": {
            "src/assist.js": '''import axios from "axios";

const CHAT = "https://api.openai.com/v1/chat/completions";

export async function summarise(thread) {
  const { data } = await axios.post(CHAT, {
    model: "gpt-4-turbo-preview",
    messages: [{ role: "user", content: thread }],
  });
  return data.choices[0].message.content;
}
''',
        },
    },
    "northwind/loyalty-service": {
        "manifest": ("composer.json", PHP_OK % php(("guzzlehttp/guzzle", "7.5.0"),
                                                   ("firebase/php-jwt", "6.3.0"))),
        "files": {
            "src/Mail/MailchimpClient.php": '''<?php
namespace Northwind\\Mail;

class MailchimpClient
{
    public function upsert(string $listId, array $member): array
    {
        $url = "https://us14.api.mailchimp.com/3.0/lists/{$listId}/members";
        return json_decode(file_get_contents($url), true);
    }
}
''',
        },
    },

    # ---- acquired brand, older stack ----------------------------------------------------
    "coastline/legacy-storefront": {
        "manifest": ("composer.json", PHP_EOL % php(("guzzlehttp/guzzle", "6.2.0"),
                                                    ("monolog/monolog", "1.22.0"))),
        "files": {
            "app/Ebay/FindingService.php": '''<?php
namespace Coastline\\Ebay;

class FindingService
{
    public function search(string $kw): array
    {
        $url = "https://svcs.ebay.com/services/search/FindingService/v1?keywords=" . urlencode($kw);
        return json_decode(file_get_contents($url), true);
    }
}
''',
            "app/Amazon/MwsOrders.php": '''<?php
namespace Coastline\\Amazon;

class MwsOrders
{
    public function list(): array
    {
        return json_decode(file_get_contents("https://mws.amazonservices.com/Orders/2013-09-01"), true);
    }
}
''',
        },
    },
    "coastline/price-feed": {
        "manifest": ("package.json", json.dumps({
            "name": "price-feed", "private": True,
            "dependencies": {"axios": "0.21.1", "node-fetch": "2.6.1"}}, indent=2)),
        "files": {
            "index.js": '''const axios = require("axios");

const TRENDING = "https://marketplace.walmartapis.com/v3/insights/items/trending";

module.exports.run = async () => (await axios.get(TRENDING)).data;
''',
        },
    },

    # ---- internal, quiet repos (coverage realism: not everything is on fire) ------------
    "northwind/design-tokens": {
        "manifest": ("package.json", json.dumps({
            "name": "design-tokens", "private": True,
            "dependencies": {"chroma-js": "2.4.2"}}, indent=2)),
        "files": {"src/index.js": 'export const brand = { ink: "#16202a" };\n'},
    },
    "northwind/data-warehouse-etl": {
        "manifest": ("package.json", json.dumps({
            "name": "data-warehouse-etl", "private": True,
            "dependencies": {"axios": "1.6.7", "pg": "8.11.3"}}, indent=2)),
        "files": {
            "src/extract.js": '''import axios from "axios";

const SP = "https://sellingpartnerapi-eu.amazon.com/orders/v0/orders";
export const pull = () => axios.get(SP);
''',
        },
    },
    "northwind/ops-runbooks": {
        "manifest": ("package.json", json.dumps({"name": "ops-runbooks", "private": True}, indent=2)),
        "files": {"README.md": "# Runbooks\n\nOn-call procedures.\n"},
    },
    "northwind/identity-gateway": {
        "manifest": ("composer.json", PHP_OK % php(("firebase/php-jwt", "6.4.0"))),
        "files": {
            "src/Auth/GoogleVerifier.php": '''<?php
namespace Northwind\\Auth;

class GoogleVerifier
{
    public function certs(): array
    {
        return json_decode(file_get_contents("https://oauth2.googleapis.com/tokeninfo"), true);
    }
}
''',
        },
    },
    "northwind/returns-portal": {
        "manifest": ("composer.json", PHP_OK % php(("guzzlehttp/guzzle", "7.8.0"))),
        "files": {
            "src/Returns/SpApiReturns.php": '''<?php
namespace Northwind\\Returns;

class SpApiReturns
{
    public function feed(string $xml): string
    {
        return file_get_contents("https://sellingpartnerapi-na.amazon.com/feeds/2020-09-04/feeds");
    }
}
''',
        },
    },
    "northwind/analytics-collector": {
        "manifest": ("package.json", json.dumps({
            "name": "analytics-collector", "private": True,
            "dependencies": {"axios": "1.7.2"}}, indent=2)),
        "files": {
            "src/ship.js": '''import axios from "axios";
const GA = "https://www.google-analytics.com/mp/collect";
export const send = (e) => axios.post(GA, e);
''',
        },
    },
}


def run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


made = 0
for full, spec in REPOS.items():
    org, name = full.split("/")
    d = ROOT / name   # bare repo name: the org prefix truncated in the UI column
    d.mkdir(parents=True, exist_ok=True)
    mf, body = spec["manifest"]
    (d / mf).write_text(body + "\n")
    for rel, text in spec["files"].items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    run(["git", "init", "-q", "-b", "main"], d)
    run(["git", "-c", "user.email=eng@northwind.test", "-c", "user.name=Northwind Engineering",
         "add", "-A"], d)
    run(["git", "-c", "user.email=eng@northwind.test", "-c", "user.name=Northwind Engineering",
         "commit", "-q", "-m", "initial import"], d)
    made += 1

print(f"built {made} repos in {ROOT}")
