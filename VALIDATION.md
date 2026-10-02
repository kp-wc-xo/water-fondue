# Validation — 2026-10-02

- Python unittest: 16 passed, including parser, freshness, deduplication, quota, raw retention and backup round trip.
- Worker Node tests: 18 passed, including HMAC, token audience/expiry, server-verified ownership, non-admin restrictions, private photo ownership, quota error, bounded bodies and public config.
- Full SQL executed in PGlite PostgreSQL WASM: schema accepted; report idempotency, cross-owner duplicate denial, 3/user/day and 100/month limits, event deduplication, anonymous table/RPC denial passed.
- Wrangler 4.59.2 deployment dry-run: passed. No actual cloud deployment performed.
- Chromium + Playwright at mobile viewport 390x844: mocked LINE login, real earlier water snapshot display (18 stations), report form submission, admin listing passed; no JavaScript errors or horizontal overflow. APIs and LINE SDK were mocked; this is not a live LINE integration test.
- Thai DOCX rendered to 14 pages and visually inspected.

## Remaining deployment verification
Real LINE login/Published channel and Rich Menu, webhook Verify/reply, Supabase Storage uploads/signed URLs, second-user access isolation, scheduled collection, and Cloudflare Free CPU/usage must be checked on the operator's accounts using the guide. Local workerd could not launch in this environment (network interface enumeration); build and Node tests do not replace a deployed smoke test. No load test or guaranteed free-plan capacity is claimed.

No secrets are included. Free quotas and account conditions can change. Optional push defaults off. Reports/history have no automatic deletion; operator backup, retention and quota monitoring are required.
