// Evidence for the `js-baseurl-template` idiom instance (agent/idioms.yaml).
//
// The shape: same host-on-the-instance client as js-baseurl-concat.js, but the URL is
// built with a template literal instead of `+`. That is a different AST node
// (template_string), so the `$A.baseURL + $B` rule cannot see it — the host and the path
// still never share a plain string literal, so a URL-literal scan sees nothing at all.
//
// Concat-free on purpose: if a `+` appeared here the fixture could not prove the gap.

class BillingClient {
  constructor(baseURL) {
    this.baseURL = baseURL;              // e.g. "https://api.example-vendor.io"
  }

  charges() {
    const url = `${this.baseURL}/v1/charges`;
    return fetch(url);
  }

  refund(id) {
    return fetch(`${this.baseURL}/v1/refunds/${id}`);
  }
}

module.exports = { BillingClient };
