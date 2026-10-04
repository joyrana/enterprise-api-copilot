# Identity: Webhooks

Identity sends webhook events signed with HMAC-SHA256 in the X-Signature header. Failed deliveries are retried 8 times with exponential backoff over 6 hours.
