# Authentication

## Google OpenID Connect

The browser uses the authorization-code OpenID Connect flow. `/auth/google` creates random state and
nonce values protected by a short-lived signed HTTP-only cookie. `/auth/callback` exchanges the code
at Google's token endpoint, then `google-auth` verifies the ID token signature, issuer, audience,
expiry, and claims; the callback separately checks nonce. Token contents are never trusted through
manual decoding. Access and refresh tokens are not stored.

Accounts are keyed by `(auth_provider, provider_subject)`, using Google's `sub`. Email, verification,
name, and picture are profile metadata. An email change updates the same account; an unverified email
is stored as untrusted metadata. Only fields required for display/administration are retained.

## Provisioning and sessions

An unknown valid Google identity creates a pending inactive account and receives no person grant.
An administrator must activate it and create explicit grants. Authentication success never implies
health access.

The browser receives a random opaque session cookie that is HTTP-only, SameSite=Lax, and Secure when
configured. Only its SHA-256 hash is stored. Sessions expire after the configured interval; logout
sets an invalidation timestamp and clears cookies. CSRF uses a separate random double-submit value
whose hash is bound to the server session. Rotating `SESSION_SECRET` invalidates outstanding OIDC
state; administrators can invalidate stored sessions independently.

## Configuration

Set `HEALTH_AVATAR_GOOGLE_CLIENT_ID`, optional client secret when required by the Google client type,
and an exact `HEALTH_AVATAR_GOOGLE_REDIRECT_URI`. In Google Cloud, create an OAuth web client, add the
redirect URI (locally `http://localhost:8000/auth/callback`), configure the consent screen, and add
test users while the app is in testing. External browser validation still requires these credentials.

Production startup fails if Google client ID, secure cookies, or a strong session secret is missing,
or if development auth is enabled. Secrets belong in a secret manager/environment, never Git.

## Development authentication

`HEALTH_AVATAR_DEVELOPMENT_AUTH_ENABLED=true` exposes a visibly labeled synthetic-login form only
when `APP_ENV` is not production. It selects deterministic seeded provider subjects; it is not an
unauthenticated wildcard identity or a production bypass. Production configuration rejects it.
