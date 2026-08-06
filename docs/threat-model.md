# Version 0.2A threat model

| Threat | 0.2A control | Residual/deferred risk |
|---|---|---|
| Unauthorized family-member access / IDOR | Per-request service-layer grants; hidden-resource 404 policy | Grant administration mistakes require audit review |
| Account takeover / session theft | Google authentication; opaque expiring HTTP-only Secure cookies; logout invalidation | Device security and Google account recovery are external |
| Forged identity token | Official `google-auth` signature, issuer, audience, expiry validation plus OIDC state/nonce | Google client configuration requires manual verification |
| CSRF | SameSite cookies and session-bound double-submit token on mutations | Browser/XSS compromise can defeat in-origin controls |
| Privilege escalation | Separate system admin/grants; role matrix; explicit actor; audited changes | More granular capabilities may be needed later |
| Household inference | Membership has no authorization semantics | UI wording must preserve this distinction |
| Malicious upload | Size/type/extension checks; generated path-safe keys; no execution | Malware scanning and content sandboxing are deferred |
| Path traversal | Original name stripped to metadata; storage rejects absolute/parent keys | Future storage backends need equivalent tests |
| Oversized files | Bounded read and configured maximum | Streaming multipart limits/reverse-proxy limits should be added before deployment |
| Sensitive logs / errors | No raw content logging; structured safe errors; no client stack traces | Operational log configuration still needs deployment review |
| Accidental public exposure | Production startup security checks and explicit no-public-deployment policy | TLS, firewall, secrets, monitoring, and backup operations are external |
| Adapter parser failure | Typed results, per-row issues, staged records, coherent transaction counts | Parser resource exhaustion needs adapter-specific limits |
| Source/canonical ambiguity | Immutable artifacts, locators, versioned runs, review, idempotent promotion | Source-native corrections and fuzzy duplicate detection are deferred |
| AI prompt injection / hallucination | No production AI or multimodal calls in 0.2A | Provider isolation, confidence, consent, and mandatory review belong to 0.2B+ |

The primary trust boundaries are the browser-to-application session, Google-to-callback token,
application-to-PostgreSQL connection, application-to-artifact storage, and future adapter/provider
boundary. Health data authorization is denied unless an active explicit grant exists.

## AI and image additions

- Prompt injection in image/document text is treated as data, never instruction; deterministic
  validation ignores prose commands.
- Hallucinated, conflicting, unitless, unknown, or uncertain facts cannot auto-promote. All AI facts
  require an authorized reviewer.
- Consent is recorded per intake. Global cloud disablement and maximum sensitivity prevent provider
  use outside policy.
- Provider requests minimize identity/context, use bounded timeout/retry, and omit secrets and raw
  source content from logs. Raw model responses are hidden from ordinary APIs.
- Actual-format checks, byte/pixel/dimension limits, generated storage keys, decompression-bomb
  protection, and EXIF-free provider derivatives mitigate malicious image risks. Malware scanning
  and provider retention/regional review remain deployment gates.
