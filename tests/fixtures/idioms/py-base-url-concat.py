"""Evidence for the `py-base-url-concat` idiom instance (agent/idioms.yaml).

Python's answer to js-baseurl-concat: the host lives on the instance and the path is
concatenated onto it, so the host never shares a string literal with the path and a
URL-literal scan sees only a versioned path with no vendor.

Before this instance, a Python url-assembly instance compiled to NOTHING — `_CONCAT_OP`
knew only php/javascript/typescript — which is indistinguishable from a repo with nothing
to find.
"""
import requests


class BillingClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def charges(self):
        url = self.base_url + "/v1/charges"
        return requests.get(url)
