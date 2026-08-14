"""Negative controls for `py-base-url-concat`. Nothing here may match the shipped pattern.

Matching any of these would mark an unrelated file as URL-assembling, and endpoints.py
would then attribute its bare path literals to whatever host the file mentions.
"""
import httpx


def greet(name):
    return "hello " + name                      # a plain string concat, no base_url


class Client:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url

    def signed(self, suffix):
        return self.api_key + suffix            # a different attribute entirely

    def charges(self):
        return f"{self.base_url}/v1/charges"     # f-string: a different AST, KNOWN MISS


# Already covered by the client-base family — concat must not also require this shape.
shared = httpx.Client(base_url="https://api.stripe.com")
