# Workout-image ingestion

An authorized owner or enabled caregiver uploads JPEG, PNG, or WebP evidence. Health Avatar checks
byte size, declared/actual format, pixel count, and dimensions, rejects corrupt or decompression-
bomb images, and generates a re-encoded EXIF-free representation for provider processing. The
private original remains in artifact storage; neither storage keys nor bytes are exposed by normal
artifact metadata.

The provider proposes an exercise group and metrics. Low confidence is labeled in text as well as
visually. Nothing promotes automatically. An authorized reviewer may correct/remove facts, add a
missing registered metric, reject the intake, or confirm. Confirmation creates one session and its
metrics exactly once. The protected content route enforces the person's active grant and returns
`private, no-store`.

The deterministic mock provider supports synthetic workout-image tests. The OpenAI adapter is
production-capable but disabled until cloud processing, credentials, model, sensitivity policy,
and affirmative consent are configured. No live provider call is required for validation.
