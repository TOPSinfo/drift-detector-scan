"""Negative controls for `py-base-url-concat`. Nothing here may match the shipped pattern.

Matching any of these would mark an unrelated file as URL-assembling, and endpoints.py
would then attribute its bare path literals to whatever host the file mentions.

`+` negatives only. The f-string shape moved to py-base-url-fstring.py once it stopped
being a miss — leaving it here would make this file a false negative control, since the
f-string rule is SUPPOSED to match it.
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



# Already covered by the client-base family — concat must not also require this shape.
shared = httpx.Client(base_url="https://api.stripe.com")
