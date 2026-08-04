# Security policy

Health Avatar may process highly sensitive health information. Treat every non-synthetic record,
export, backup, log, and credential accordingly.

- Never commit real health exports, uploaded medical documents, `.env`, local secrets, private keys,
  or database dumps.
- Protect and encrypt database backups; restrict their access and test restoration securely.
- Production deployments require HTTPS and secrets supplied outside source control.
- Logs must contain operational metadata only, never complete health records or raw import rows.
- All tracked sample data must be synthetic.
- Authentication and authorization are intentionally incomplete in Version 0.1. AccessGrant records
  express the future policy model but are not yet enforced.
- Version 0.1 must not be exposed to the public internet.

If sensitive data is committed or exposed, stop access, rotate affected credentials, preserve the
incident timeline, and remove the data from the full Git history—not only the latest commit.

