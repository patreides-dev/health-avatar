# Security policy

Health Avatar may process highly sensitive information. Version 0.2A is for reviewed private
development/household use and must not be publicly deployed without a separate security review. It
makes no HIPAA or regulatory-certification claim.

- Google OIDC proves identity; only active `AccessGrant` records authorize a person. Provider
  subject, not email, is the durable external key.
- Sessions are opaque, hashed server-side, expiring, invalidatable, HTTP-only, SameSite protected,
  and Secure in production. Browser mutations require a session-bound CSRF token.
- Development auth is synthetic, visibly labeled, disabled by default, and forbidden by production
  configuration validation.
- Uploads are bounded by configured bytes and restricted by kind, media type, and extension. Names
  are metadata only; storage keys are generated and path-safe. Malware scanning is required before
  broader file support or deployment.
- Sensitivity classification is routing/policy metadata, not an encryption or compliance guarantee.
- Artifact bytes require protected storage permissions. Encrypted object storage, key management,
  retention, and restoration testing are production requirements.
- Logs may contain identifiers, status, and safe error codes, never raw rows, artifact contents,
  tokens, complete observations, filesystem keys, or stack traces in client responses.
- Administrative changes are auditable. Administrators receive no implicit health-record access.
- No production cloud-AI processing is enabled. Future provider use requires consent, minimization,
  retention, regional, and prompt-injection review.
- Never commit real health data, exports, documents, `.env`, credentials, secrets, private keys,
  dumps, backups, or generated artifact storage. All tracked fixtures must remain synthetic.
- Production secrets must come from a secret manager/environment. Backups must be encrypted,
  access-controlled, monitored, and restoration-tested.

If sensitive material is exposed, stop access, preserve an incident timeline, rotate credentials,
invalidate sessions, assess artifact/database/backups, and remove leaked content from full Git
history where applicable. See [`docs/threat-model.md`](docs/threat-model.md).
