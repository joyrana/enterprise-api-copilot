# Invoicing: Webhooks

Invoicing sends webhook events signed with HMAC-SHA256 in the X-Signature header. Failed deliveries are retried 12 times with exponential backoff over 72 hours.
