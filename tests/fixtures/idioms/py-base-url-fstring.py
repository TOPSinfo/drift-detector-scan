"""Evidence-support fixture for `py-base-url-concat` (agent/idioms.yaml).

The Python mirror of js-baseurl-template.js: the same host-on-the-instance client, but the
URL is built with an f-string instead of `+`. That is a different AST node, so the concat
rule matches this file zero times — which is exactly what this fixture proves.

Concat-free on purpose: a single `+` here would destroy the proof.

No instance cites this file as `evidence:`; it is kept because it is the only thing
demonstrating that the second rule is needed at all.
"""
import requests


class BillingClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def charges(self):
        url = f"{self.base_url}/v1/charges"
        return requests.get(url)

    def refund(self, id):
        return requests.get(f"{self.base_url}/v1/refunds/{id}")
