# Release Checklist

A release candidate is not "done" because containers start or tests pass (master prompt
§15). Every item needs evidence linked in the release notes. Items marked **(blocked)** could
not be completed in the environment that wrote this checklist; see STATUS.md.

## 1. Build and tests
- [ ] `python-ci` green on 3.12 and 3.13: ruff, `mypy --strict`, pytest incl. pgvector and CLI system test.
- [ ] `go-build` green: gofmt, vet, `go test -race`, golangci-lint, govulncheck, cross-platform binaries.
- [ ] `frontend-build` green: API-client tests, lint, type-check, Vitest, production build. **(blocked: npm)**
- [ ] `java-build` green against the platform contract tests. **(blocked: Maven Central)**
- [ ] Lockfiles committed (`uv.lock`, `package-lock.json`, Maven wrapper). **(blocked)**

## 2. Contracts
- [ ] `tests/contract/` pass against every implementation of `platform-api.yaml` (facade and Spring backend) and `agent-service.yaml`.
- [ ] Contract changes are backward compatible or versioned; CLI and web client updated.

## 3. Evaluation (artifacts attached with commit SHA and dataset hashes)
- [ ] `python -m evals run --suite full`: zero safety-gate failures; task success not below the last release's lower CI bound.
- [ ] `python -m evals.ablation --split test`: default retrieval config still at least baseline.
- [ ] Judge calibration on a live model: agreement and consistency reported, cost recorded (opt-in secret).
- [ ] Known failing examples listed with causes (docs/evaluation/README.md).

## 4. Security
- [ ] Threat-model controls marked "I" still have passing tests (authz, approvals, SSRF, redaction, tenant isolation).
- [ ] No secrets in repo, reports or fixtures (secret scan); dependency scans clean or triaged.
- [ ] Production config: `COPILOT_RUNTIME_MODE=production`, real `COPILOT_APPROVAL_KEY` and `COPILOT_SERVICE_TOKEN_KEY` from a secret store, platform PDP wired (the service refuses to start otherwise).
- [ ] `COPILOT_WRITE_ENVIRONMENTS` reviewed; production writes enabled only with sign-off.
- [ ] The local platform facade is not deployed (it refuses non-local modes).

## 5. Operations
- [ ] Load test against the release build; p95 within budget; results attached.
- [ ] Durable state on PostgreSQL (runtime schema `ai/storage/sql/V001__runtime.postgres.sql`) with backups. **(blocked: driver)**
- [ ] Traces visible end to end (`traceparent` from API to gateway); dashboards updated.
- [ ] Runbook reviewed (docs/operations/runbook.md); on-call knows the approval-queue procedures.
- [ ] Container images build, run as non-root, pass Trivy. **(blocked: no Docker daemon)**

## 6. Documentation
- [ ] README status table matches what was verified.
- [ ] STATUS.md, MASTER_PLAN.md and ADRs updated; limitations recorded.
