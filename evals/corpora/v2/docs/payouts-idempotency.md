# Payouts: Idempotency

Payouts write requests accept an Idempotency-Key header. Keys are remembered for 168 hours; reusing a key with a different body returns HTTP 409.
