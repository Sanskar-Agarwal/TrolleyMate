# Authentication and request security

Implemented on Sanskar during the 30 October 2026 UAT follow-up.

## Password storage

Passwords are salted and hashed with PBKDF2-HMAC-SHA256, 600,000 iterations and a fresh
128-bit salt. The stored format includes the algorithm and work factor. Passwords are
never encrypted for later retrieval, returned by the API, or stored in plaintext.
Comparison is constant-time. Existing 120,000-iteration hashes remain readable and are
upgraded only after a successful login. Login inputs are length-bounded, and an unknown
account still performs password verification before returning the generic failure message.

## CSRF

The API uses explicit bearer headers, not ambient authentication cookies. Every write
requires `X-TrolleyMate-Request: 1`; the React client supplies it automatically. Cross-origin
HTML forms cannot set that header. Browser Origin/Referer and Fetch Metadata checks reject
untrusted sources, and non-JSON form content types are rejected. CORS uses exact configured
origins and does not allow credentialed cookies. Command-line clients must send the header too.
This is the custom-header pattern for JSON APIs, not a cookie-based synchronizer-token scheme.
If cookie authentication is introduced later, its CSRF design must be reviewed again.

## Rate limits

| Scope | Default | Setting |
|---|---:|---|
| API requests per client IP | 300 / minute | `API_REQUESTS_PER_MINUTE` |
| Authenticated writes per account | 30 / minute | `ACCOUNT_WRITES_PER_MINUTE` |
| Login and registration attempts per IP | 10 / minute | `AUTH_ATTEMPTS_PER_MINUTE` |
| Login attempts per normalised email | 10 / 15 minutes | `ACCOUNT_LOGIN_ATTEMPTS_PER_QUARTER_HOUR` |
| Registrations per IP | 5 / hour | `REGISTRATIONS_PER_HOUR` |

These are fixed windows, enforced by atomic SQLite updates in the adjacent `.db.limits`
store. Identities are keyed with HMAC rather than storing raw email/IP keys. Expired counters
are removed. `429` responses provide `Retry-After`. Health checks are exempt; sign-out is
exempt from the account-write limit but remains subject to the global IP limit. Auth limits
count successful and failed attempts, so a burst of demo-account switching can also throttle.
Raw `X-Forwarded-For` headers are not trusted by application code. Configure the ASGI server
correctly behind a trusted proxy. These controls do not raise Groq's independent quota.

## Login session limits

| Control | Default | Setting |
|---|---:|---|
| Maximum concurrent logins per account | 3; oldest revoked on next login | `MAX_ACTIVE_SESSIONS` |
| Idle expiry | 30 minutes | `SESSION_IDLE_MINUTES` |
| Absolute expiry | 8 hours | `TOKEN_TTL_HOURS` |

Tokens contain 256 bits of randomness; only SHA-256 digests are stored in the application
database. Expiry and revocation are checked server-side on authenticated requests. Activity
writes are coalesced to once a minute, so idle expiry can be up to one minute earlier.
Sign-out deletes the current session, and **Sign out everywhere** deletes all sessions for
that account. The frontend stores its token in `sessionStorage`, retiring old `localStorage`
tokens. A new independent tab therefore signs in separately. Browser storage is still accessible
to same-origin JavaScript; these controls do not make XSS harmless.

Existing signed tokens must sign in again after upgrading. Database tables are added on
startup, and existing users/households/baskets are preserved. Session limits concern login
sessions, not the number of saved shopping plans.

## Verification and limits

Automated tests exercise password salt/version/migration, malformed hashes/tokens, login
throttles, atomic concurrent rate counting, time-window reset, expiry, session eviction,
account-scoped logout, CSRF headers/origins/content types, and frontend token handling.
The browser run verifies legacy sign-out, four independent logins/oldest eviction, logout
everywhere, throttling feedback, and the ordinary shopping flow after these changes.
See [live UAT](UAT_LIVE_2026-10-30.md) for final results.

SQLite is the supported/tested deployment. Multiple hosts with separate stores do not share
limits. Use a shared store/identity service for a larger distributed deployment. TLS is required
for remote deployment; localhost HTTP remains available for development. Demo accounts are
for the prototype, not production authentication. No production-security certification is claimed.

Design references: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
and [session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
