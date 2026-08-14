"""Evidence for the `py-httpx-client` idiom instance (agent/idioms.yaml).

The same shape as js-axios-create, in Python: the host is handed to a client factory once
and every later call passes only a path. The host and the path never share an expression,
so nothing emits path-assembly and endpoints.py leaves `/v1/charges` as residue even
though the file classifies a vendor from the host literal.

Not a copy of any client's source — a reduced form of the pattern.
"""
import httpx

client = httpx.Client(base_url="https://api.stripe.com")

client.get("/v1/charges")

# Extra kwargs — a common real spelling. Whether the shipped pattern reaches this is
# recorded in the idiom's note and pinned by a test; it is not assumed.
timed = httpx.Client(base_url="https://api.stripe.com", timeout=10.0)

timed.get("/v1/refunds")

# Async variant — counted so the one-instance-vs-two decision is made from engine output.
aclient = httpx.AsyncClient(base_url="https://api.stripe.com")
