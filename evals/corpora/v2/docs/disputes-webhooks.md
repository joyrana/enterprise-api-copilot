# Disputes: Webhooks

Disputes sends webhook events signed with HMAC-SHA256 in the X-Signature header. Failed deliveries are retried 3 times with exponential backoff over 6 hours.
