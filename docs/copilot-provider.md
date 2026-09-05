# Copilot provider configuration

`copilot/provider.py` is the single source of configuration for the Copilot
provider. It currently names the Gemini Developer API and `gemini-3.8-flash`.
It uses the `v1beta` API endpoint. A `COPILOT_MODEL` override is
explicitly unsupported so an unreviewed model cannot silently become usable.

| Setting | Value |
| --- | --- |
| Provider | Google Gemini Developer API |
| Model ID | `gemini-3.8-flash` |
| API version | `v1beta` |
| Request timeout | 30 seconds |
| Automatic retries | None (`MAX_RETRIES=0`) |

## Verification status

On 2026-09-05, the configured Gemini Developer API key successfully resolved
`models/gemini-3.8-flash` and completed a minimal interaction using
`gemini-3.8-flash`. This is the required authorized developer-API verification.

Set the key as `GEMINI_API_KEY=<key>` in `.env` (no `export`). The current
`gemini-api-key` name is not read by this configuration; rename only the key
name, not its value. Never commit `.env`.

Use this no-secret capability check in an authorized environment:

```powershell
curl.exe -sS -H "x-goog-api-key: $env:GEMINI_API_KEY" "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash"
```

Keep API keys, request headers, and request/response bodies out of logs and
Git. Record only the date, model ID, command outcome, and non-secret error
class if a future check fails.

## Unavailable and error behavior

Use `availability()` before a request and map provider results as follows:

| Condition | State | Code |
| --- | --- | --- |
| Missing `GEMINI_API_KEY` | `unavailable` | `missing_credentials` |
| Any model other than `gemini-3.8-flash` | `unavailable` | `unsupported_model` |
| Quota or rate-limit response | `unavailable` | `quota_exhausted` |
| Other provider/network response | `error` | `provider_error` |

Do not substitute a model or manufacture an answer after any unavailable/error
state. Surface the code to the caller and let it decide when to retry.
