# Gateway proxies and rate limits

## Proxy mapping

The Synthetic Payments API is exposed through the payments-v1 gateway proxy, which forwards to the payments backend service. The Synthetic Orders API is exposed through the orders-v2 proxy, which forwards to the order management service.

## Rate limits

The gateway enforces a spike arrest of 60 requests per minute per client application in the sandbox. Quota counters reset every minute.

## Management plane versus runtime

The gateway management API is used by administrators to deploy proxies and is never called by the copilot. The copilot only calls runtime proxy URLs configured for each environment.
