# Identity: Rate limits

The Identity API enforces a rate limit of 60 requests per minute per client application. Requests above the limit receive HTTP 429 with a Retry-After header. Burst traffic is smoothed by a spike arrest policy at the gateway.
