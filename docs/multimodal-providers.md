# Multimodal extraction providers

`ExtractionProvider.extract_health_facts()` accepts a provider-neutral request containing only the
submission text, safe image bytes, modality, purpose, media type, and sensitivity. It returns the
strict `HealthExtractionResponse`: summary, fact groups, typed proposed facts, warnings, unresolved
content, and overall extraction confidence. Provider SDK objects never enter services or storage.

The mock provider is deterministic and covers text, workout images, lipid panels, partial results,
ambiguity, malformed output, timeouts, and errors. The OpenAI provider uses the official Python SDK
Responses structured-output interface with bounded timeout/retries and a configured model. It has
no default model so deployment cannot silently change cost or behavior. Tests mock the SDK; no live
call or credential is used.

The prompt orders extraction of explicit facts only, forbids inference/diagnosis/treatment, and
treats text visible in images/documents as untrusted data rather than instructions. Future local,
Azure OpenAI, Gemini, or Anthropic adapters implement the same contract. PDF document support is a
future modality, not an OCR system in this release.
