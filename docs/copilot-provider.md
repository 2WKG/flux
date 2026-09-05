# Copilot provider configuration

`copilot/provider.py` is the single source of configuration for the Copilot
provider. It currently names Anthropic and `claude-opus-5`; no API-version
header is required by this configuration. A `COPILOT_MODEL` override is
explicitly unsupported so an unreviewed model cannot silently become usable.

| Setting | Value |
| --- | --- |
| Provider | Anthropic |
| Model ID | `claude-opus-5` |
| API version | Provider default (no configured version header) |
| Request timeout | 30 seconds |
| Automatic retries | None (`MAX_RETRIES=0`) |

## Verification status

This candidate is **not verified** in this checkout. On 2026-09-05,
`ANTHROPIC_API_KEY` was unavailable and the Anthropic Python SDK was not
installed, so no request was made. Do not mark the provider available or claim
the model is usable until an authorized developer environment passes both:

```powershell
python -c "from anthropic import Anthropic; import os; print(Anthropic().models.retrieve(os.environ.get('COPILOT_MODEL', 'claude-opus-5')).id)"
```

and a minimal streamed request using the same model. Keep API keys, request
headers, and request/response bodies out of logs and Git. Record only the date,
model ID, command outcome, and non-secret error class if it fails.

## Unavailable and error behavior

Use `availability()` before a request and map provider results as follows:

| Condition | State | Code |
| --- | --- | --- |
| Missing `ANTHROPIC_API_KEY` | `unavailable` | `missing_credentials` |
| Any model other than `claude-opus-5` | `unavailable` | `unsupported_model` |
| Quota or rate-limit response | `unavailable` | `quota_exhausted` |
| Other provider/network response | `error` | `provider_error` |

Do not substitute a model or manufacture an answer after any unavailable/error
state. Surface the code to the caller and let it decide when to retry.
