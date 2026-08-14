"""Negative controls for `py-httpx-client`. Nothing here may match the shipped pattern.

A rule firing on any of these would mark unrelated files as URL-assembling, and
endpoints.py would then attribute their bare path literals to whatever host the file
mentions. Manufacturing attributions is worse than the gap being closed.
"""
import httpx
import requests


# requests.Session has no base_url at all — the path below is genuinely unresolvable.
s = requests.Session()
s.get("/v1/charges")

# Module-level call, not a client factory: the full URL is already a literal here.
httpx.get("https://api.stripe.com/v1/charges")


# A local class that happens to share the name and the kwarg.
class Client:
    def __init__(self, base_url):
        self.base_url = base_url


local = Client(base_url="https://api.stripe.com")

# A real httpx client with NO base_url: it holds no host, so a path in this file cannot be
# attributed from it. A strict pattern must not match this.
bare = httpx.Client()
