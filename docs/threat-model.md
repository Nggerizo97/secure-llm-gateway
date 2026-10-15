# Threat Model & Controls

1. **Unapproved Egress / Shadow AI:** Mitigated by `ALLOWED_PROVIDERS_BY_PROFILE`, explicit `mock` default, and hardcoded denial of `personal_api`.
2. **Silent Fallback on Auth/Policy/Quota Failures:** `AuthenticationError` (401/403), `PolicyViolationError` (403), and `QuotaExhaustedError` (402) set `retryable=False` and immediately halt routing.
3. **Credential Leakage in Prompts or Logs:** `SECRET_PATTERNS` blocks common token formats before routing; `AuditEvent` schema omits prompt and completion fields entirely.
4. **Accidental Cloud Egress in Tests:** `assert_local_emulator_url()` restricts Floci exports to `localhost` / `127.0.0.1`.