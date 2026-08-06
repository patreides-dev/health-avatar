# AI privacy and consent

Before processing, the interface discloses the configured provider, purpose, that health-related
content may be transmitted, and that all facts require review. Affirmative consent creates an
`AIProcessingConsent` record containing the user, intake/artifact, provider, model, purpose,
timestamp, and policy version.

Cloud AI is globally disabled by default. Provider sensitivity policy can reject submissions above
the configured maximum. Requests omit person name, email, birth date, existing health history, and
unrelated records. API keys, raw source bytes, and model payloads are not logged. The original model
response is retained for audit but omitted from ordinary API/UI responses.

Local deterministic mock processing is for synthetic development and tests. Enabling OpenAI
requires `HEALTH_AVATAR_CLOUD_AI_ENABLED=true`, an API key, and an explicit model. Production use
also requires a provider retention/data-use review, network controls, secrets management, and the
project's broader deployment security gate. Consent is not a compliance certification.
