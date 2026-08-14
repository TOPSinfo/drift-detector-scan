// Negative controls for the `js-axios-create` idiom. Nothing here may match the pattern.
//
// A rule that also fires on Object.create or on any object carrying a `baseURL` key would
// mark unrelated files as URL-assembling, and endpoints.py would then attribute bare path
// literals in those files to whatever vendor the file happens to mention. Over-matching
// here manufactures attributions, which is worse than the gap it closes.

// Same option-object shape, entirely unrelated function.
const proto = Object.create({ baseURL: 'https://api.stripe.com' });

// A plain config object — no factory call at all.
const settings = { baseURL: 'https://api.stripe.com', retries: 3 };

// A different library's factory with the same option name.
const other = myHttpLib.create({ baseURL: 'https://api.stripe.com' });

// A bare call with no create() in this file: there is no assembling client here, so this
// file must NOT be marked as assembling.
axios.get('/v1/charges');

module.exports = { proto, settings, other };
