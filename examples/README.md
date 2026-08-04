# Examples

This directory contains example requests, integration demos, and usage patterns for Enterprise API Copilot.

## CLI Examples

```bash
# Health check
copilot doctor

# Natural language API discovery
copilot ask "What payment APIs are available?"

# Natural language API execution
copilot ask "Create a sandbox payment of ₹500 for customer cust_abc123"

# Execute by method + path
copilot api run --method GET --path /v1/payments

# List all APIs
copilot api list

# Search API catalog
copilot api search "payment"
```

## REST API Examples

### Health Check

```bash
curl http://localhost:8080/api/v1/health
```

### Ask (Natural Language — coming Phase 2)

```bash
curl -X POST http://localhost:8080/api/v1/copilot/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Create a sandbox payment of ₹500",
    "conversationId": null
  }'
```

### List Executions

```bash
curl http://localhost:8080/api/v1/executions \
  -H "Authorization: Bearer <token>"
```
