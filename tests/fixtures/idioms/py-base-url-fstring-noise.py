"""Negative controls for the Python f-string rule. Nothing here may match it.

A rule firing on any ordinary f-string would mark most Python files as URL-assembling,
and endpoints.py would then attribute their bare path literals to whatever host each file
mentions. That manufactures attributions, which is worse than the gap being closed.
"""
import httpx


def greet(name, count):
    a = f"hello {name}"
    b = f"{count} items"
    return a + b


class Client:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url

    def signed(self):
        return f"{self.api_key}/v1/x"        # a different attribute entirely


# Already covered by the client-base family.
shared = httpx.Client(base_url="https://api.stripe.com")
