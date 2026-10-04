# Loyalty: Rate limits

The Loyalty API enforces a rate limit of 240 requests per minute per client application. Requests above the limit receive HTTP 429 with a Retry-After header. Burst traffic is smoothed by a spike arrest policy at the gateway.
