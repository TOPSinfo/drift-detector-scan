# Vendored third-party runtime

- **vue** `3.5.40` — Vue 3 global production build
  - source: https://unpkg.com/vue@3.5.40/dist/vue.global.prod.js
  - sha256: 9e0039a3f6ed0e85308e24d737447f1af6af83d229d69e1267a32b29bc2a1337
  - fetched: 2026-08-04
  - why vendored: the dashboard is a single self-contained file with zero runtime fetches;
    bumping this is a re-verification event (re-run `drift-scan verify` on a real render).
