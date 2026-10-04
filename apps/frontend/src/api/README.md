# Platform API client

`client.ts` is a typed client for `contracts/openapi/platform-api.yaml`. It uses only
erasable TypeScript syntax, so its tests run with Node's built-in runner and type
stripping, without npm packages:

```bash
node --test src/api/client.nodetest.ts
```
