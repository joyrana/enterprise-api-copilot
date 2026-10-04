# Error handling

Every response carries an X-Correlation-Id header. Quote it when contacting support.

## 409 Conflict and idempotency

Write operations require an Idempotency-Key header. Retrying with the same key and the same body returns the original result. Reusing a key with a different body returns 409 Conflict; generate a new key for a new request.

## 422 Unprocessable Entity

A 422 response means the request body failed validation. Common causes are an amount below the minimum of 100 (one rupee in paise), an unsupported currency, or a customer_id that does not match the cust_ prefix format.

## 429 Too Many Requests

The sandbox allows 60 requests per minute per client. A 429 response includes a Retry-After header with the number of seconds to wait. Use exponential backoff and do not retry immediately.

## 500 and 503 errors

A 503 Service Unavailable response means the upstream service is temporarily unavailable and the request can be retried with backoff. A 500 Internal Server Error should not be retried blindly for write operations unless an Idempotency-Key was sent.
