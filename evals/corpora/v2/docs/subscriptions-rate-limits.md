# Subscriptions: Rate limits

The Subscriptions API enforces a rate limit of 600 requests per minute per client application. Requests above the limit receive HTTP 429 with a Retry-After header. Burst traffic is smoothed by a spike arrest policy at the gateway.
