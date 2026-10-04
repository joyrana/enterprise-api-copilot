# Authentication and OAuth scopes

All Synthetic Payments and Orders API calls go through the API gateway and require an OAuth 2.0 access token obtained with the client credentials grant.

## Getting a token

Request a token from the gateway token endpoint with your client ID, client secret and the scopes you need. Tokens expire after 15 minutes; request a new one rather than refreshing.

## Scopes

The payments:read scope allows listing and retrieving payments. The payments:write scope allows creating and cancelling payments. Refunds need the separate refunds:write scope, which is not included in payments:write. The customers:read scope allows reading customer profiles. Orders use orders:read and orders:write.

## 401 versus 403

A 401 Unauthorized response means the token is missing, malformed or expired; obtain a new token. A 403 Forbidden response means the token is valid but does not carry the scope the operation requires; request a token with the missing scope, for example refunds:write for refundPayment.

## Environments

The sandbox environment uses synthetic data and is safe for experimentation. Production writes are disabled for the copilot unless an administrator enables them explicitly.
