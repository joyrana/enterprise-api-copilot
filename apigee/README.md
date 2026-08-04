# Apigee Configuration

This directory contains Apigee X proxy configurations, policies, and shared flows for Enterprise API Copilot.

## Structure

```
apigee/
├── proxies/
│   └── api-copilot-proxy/     # Main API Copilot proxy bundle
│       ├── apiproxy/
│       │   ├── api-copilot-proxy.xml
│       │   ├── proxies/
│       │   ├── targets/
│       │   └── policies/
└── sharedflows/
    ├── auth-validation/        # JWT validation shared flow
    ├── rate-limiting/          # Quota enforcement shared flow
    └── error-handling/         # Standardized error responses
```

## Deployment

```bash
# TODO(#200): Add Apigee deployment scripts using apigeecli
# apigee deploy --org $APIGEE_ORG --env $APIGEE_ENV --name api-copilot-proxy
```

## Policies

| Policy | Type | Purpose |
|---|---|---|
| `verify-jwt` | VerifyJWT | Validate JWT issued by Apigee |
| `quota-enforcement` | Quota | Rate limit by client_id |
| `spike-arrest` | SpikeArrest | Protect against traffic spikes |
| `cors` | AssignMessage | Handle CORS preflight requests |
| `threat-protection` | JSONThreatProtection | Validate JSON payloads |
