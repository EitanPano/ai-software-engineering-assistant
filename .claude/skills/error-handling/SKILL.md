---
name: error-handling
description: Design or review how errors are detected, classified, logged, and returned. Use when adding an API error response, choosing an HTTP status code for a failure, shaping an error payload, writing retry logic, adding error logging, or surfacing a failure in the UI. Covers the error envelope, the status-code table, what gets logged, retry policy and failure-path tests.
---

# Error Handling

The error type, the envelope builder, the logger and the frontend result type are the
package's; their names and files are in `backend/AGENTS.md › Errors` and `frontend/AGENTS.md
› Errors`. This skill holds the rules.

## Principles

- Fail fast on invalid input, at the edge, with a message that names the field.
- One error type in the backend, one envelope in every non-2xx response, one place that
  maps errors to HTTP. The one exception is a health endpoint: nothing in the request
  failed, so the readiness endpoint answers 503 with its own body (the `dependencies` map),
  registered as such in the contract. No other endpoint does this.
- Internal detail goes to the log under the request id, never to the client.

## Backend

Controllers (and the service) raise the package's error type with a code, a message and
optional details. Validation, declared from the module's schema (the router's `validate`
middleware in Express, the handler's typed parameters in FastAPI), raises
`validation_failed` with the failing fields; a controller propagates a callee's error
unchanged and may raise one for a composition rule; nothing but the error handler builds
an error response. The handler maps
the package's error to its status, a validation error that escaped anyway to 400,
body parsing failures (malformed JSON, too large, unsupported charset or encoding) to 400,
413 or 415, and everything else to a bare `internal` envelope after logging it. An unknown
error is a generic 500 with the stack logged and never sent.

| Code | Status | Use for |
| --- | --- | --- |
| `validation_failed` | 400 | Malformed or out-of-range input; `details` lists `{ path, message }` |
| `unauthenticated` | 401 | Missing, invalid, expired or replayed token; wrong credentials (one message for an unknown email and a wrong password); wrong or expired OTP |
| `forbidden` | 403 | Authenticated but not allowed: role mismatch, blocked account, another user's target (including another tenant's data) |
| `not_found` | 404 | Missing resource, or a resource the caller may not know exists |
| `conflict` | 409 | State conflict, duplicate key |
| `payload_too_large` | 413 | Body over the parser limit (mapped from the body parser) |
| `unsupported_media_type` | 415 | Body encoding or charset the parser rejects |
| `rate_limited` | 429 | Throttling; sends `Retry-After` |
| `internal` | 500 | Unexpected; logged with stack, returned bare |
| `upstream_unavailable` | 503 | A dependency failed, or a message could not be delivered; safe to retry later |

Envelope (the package's error body type, also in the OpenAPI document):

```json
{
  "error": { "code": "validation_failed", "message": "invalid body", "details": [{ "path": "title", "message": "Too small" }] },
  "requestId": "6f0c…"
}
```

`error.details` is optional. Never include secrets, stack traces, query text or raw
provider payloads in a response.

## Logging

- Everything logs through the package's logger (`info`, `warn`, `error`; one line, then
  `key=value` fields; over the console). Nothing else writes to the console in the server.
- One line per request with method, path (without the query string), status, duration and
  `requestId`.
- Every 5xx logs the error object with its stack under the same `requestId`.
- Never log headers, bodies, tokens, passwords or cookies; the request line carries no
  query string either. A rule that must log a payload logs ids, never the payload. A
  field value is a primitive; never pass an object.
- A log field key must never match `/password|token|secret|otp|code|cookie|authorization/i`
  unless its value is a secret (the logger redacts those keys); an error code logs as
  `reason`.
- If the product adopts a logging library later, it goes behind the logger module (its
  factory is the seam); call sites do not change.

## Retry and recovery

- On the request path, retry only `upstream_unavailable`-class failures, bounded (three
  attempts, exponential backoff), on idempotent operations.
- Never retry validation, auth or domain errors.
- Connecting a store at boot is a different policy: the dependency module's retry (10
  attempts, 500 ms base, 5 s cap, 5 s per attempt), because the compose service may still
  be starting. Reconnecting after a drop is the driver's job; a query that fails because the
  store is unreachable surfaces as `upstream_unavailable` from the controller.

## Frontend

- Every route group has a `loading` and an `error` state, the root has a last-resort
  boundary, and every widget has a skeleton that matches its layout. Their messages are
  user-safe.
- `call` (`shared/api/call.ts`) is the only reader of a generated-client result. It returns
  the data or throws an `ActionError` (`shared/lib/action-error.ts`) whose message comes from
  the feature's copy table keyed by the envelope `code`, then the default copy. The server's
  `message` is never shown.
- In Next, a public cached loader lets the `ActionError` propagate and the widget renders
  `ErrorState` (`shared/ui/pattern/error-state.tsx`); in an SPA a failing loader or refetch
  reaches the group's `ErrorBoundary`. An unexpected error reaches the nearest boundary.
- In Next, an action returns the `ActionError` message as `serverError`; in an SPA the
  handler awaits `mutateAsync`, which rejects, and calls `reportFailure`. Either way field
  errors appear on their fields, the outcome in a toast, specific to the action that failed,
  with a recovery hint (retry, fix the field, sign in again). The package's `AGENTS.md › Errors` has the details.

## Tests

Per the package's `AGENTS.md › Tests`, the required failure paths by behaviour:

- Every endpoint has a test for its validation failure and its not-found path asserting the
  envelope's `code` and `requestId`, not only the status.
- Every gated endpoint tests its denial: 401 without credentials, 403 with the wrong role
  or another owner's record.
- A downstream failure (a dependency unreachable) surfaces as `upstream_unavailable`.
- Every loader has a test for the unreachable-API path.
