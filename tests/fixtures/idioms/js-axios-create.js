// Evidence for the `js-axios-create` idiom instance (agent/idioms.yaml).
//
// The shape: the host is handed to a client factory once, and every later call passes
// only a path. There is no `base + path` concatenation and no template literal anywhere,
// so both url-assembly rules are blind to it — the host and the path never meet in one
// expression. The file DOES contain the host as a URL literal, so a vendor is classified;
// what is missing is any signal that this file assembles URLs at all, which is what
// endpoints.py requires before it will attribute a bare path literal.

const axios = require('axios');

const api = axios.create({ baseURL: 'https://api.stripe.com' });

api.get('/v1/charges');

// Extra keys — a very common real spelling. Whether the shipped pattern reaches this is
// recorded in the idiom's note; it is not assumed.
const withTimeout = axios.create({ baseURL: 'https://api.stripe.com', timeout: 1000 });

withTimeout.get('/v1/refunds');
