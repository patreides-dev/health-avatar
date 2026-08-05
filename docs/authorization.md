# Authorization

Google authenticates a user. Health Avatar authorizes a person operation through an active,
unrevoked, unexpired `AccessGrant`. Household membership and matching names/emails never grant access.

| Capability | Owner | Caregiver | Viewer | System administrator |
|---|---:|---:|---:|---:|
| View granted person and observations | Yes | Yes | Yes | Only with separate grant |
| View granted imports/runs | Yes | Yes | Yes | Only with separate grant |
| Submit data | Yes | Yes | No | Only with separate write grant |
| Approve/reject candidates | Yes | With `can_approve` | No | Only with separate approving grant |
| Correct manual data | Yes | With `can_approve` | No | Only with separate grant |
| Grant/revoke ordinary caregiver/viewer access | Yes | No | No | Yes |
| Create people/accounts/system sources/devices | No | No | No | Yes |
| Activate/disable accounts | No | No | No | Yes |

The `administrator` AccessGrant role is retained for Version 0.1 compatibility but does not convert a
user into a system administrator and conveys read-only person access in 0.2A. System administration
is an account property and never bypasses person authorization.

Authorization lives in shared services. API, browser, CLI, ingestion, and promotion pass an explicit
actor. Revocation and account disablement are checked on every request. Unauthorized person,
artifact, import, run, and candidate lookups return 404 when a 403 would reveal existence. Operation
denials that do not identify a hidden resource, such as system-administration requirements, use 403.

Security-sensitive administrative changes create `AuditEvent` rows. Owners cannot grant themselves
new roles, grant owner/administrator roles, or revoke privileged grants through ordinary policy.
