// Evidence for the `js-baseurl-concat` idiom instance (agent/idioms.yaml).
//
// The shape: a client stores its host on the instance, then builds each request URL by
// concatenating a path onto it. The host never appears in the same string literal as the
// path, so a URL-literal scan sees only "/v1/charges" — a versioned path with no vendor.
//
// This file is the idiom's evidence, kept in-tree so the claim is checkable. It is a
// reduced form of the pattern, not a copy of any client's source.

class BillingClient {
  constructor(baseURL) {
    this.baseURL = baseURL;              // e.g. "https://api.example-vendor.io"
  }

  charges() {
    const url = this.baseURL + '/v1/charges';
    return fetch(url);
  }

  refund(id) {
    return fetch(this.baseURL + '/v1/refunds/' + id);
  }
}

module.exports = { BillingClient };
