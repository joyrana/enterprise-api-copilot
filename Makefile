# Enterprise API Copilot — Makefile
# Provides top-level targets for the most common developer tasks.

.PHONY: help build test lint clean docker-up docker-down test-python lint-python eval-smoke eval-full sandbox platform agent load-test test-frontend-client

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ─── Help ────────────────────────────────────────────────────────────────────
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ─── Build ───────────────────────────────────────────────────────────────────
# The backend has no Maven wrapper yet; uses a locally installed `mvn` (3.9+).
build-backend: ## Build the Spring Boot backend
	cd apps/backend && mvn -B clean package -DskipTests

build-frontend: ## Build the React frontend
	cd apps/frontend && npm ci && npm run build

build-cli: ## Build the Go CLI binary
	cd apps/cli && go build -o bin/copilot ./cmd/copilot

build: build-backend build-frontend build-cli ## Build all components

# ─── Test ────────────────────────────────────────────────────────────────────
test-backend: ## Run backend tests
	cd apps/backend && mvn -B verify

test-frontend: ## Run frontend tests
	cd apps/frontend && npm test

test-cli: ## Run CLI tests (race detector)
	cd apps/cli && go vet ./... && go test -race ./...

test-python: ## Run Python AI service tests (set COPILOT_TEST_PGURL for pgvector SQL tests)
	pytest

eval-smoke: ## Run the smoke evaluation (safety gates are hard failures)
	python -m evals run --suite smoke

eval-full: ## Run the full evaluation incl. retrieval/chunking ablation
	python -m evals run --suite full

sandbox: ## Start the synthetic sandbox gateway on :8090
	python -m sandbox --port 8090

platform: ## Start the local platform API reference implementation on :8080 (local mode)
	python -m ai.api platform --port 8080

agent: ## Start the internal agent-service API on :8000
	python -m ai.api agent --port 8000

load-test: ## Load-test a running platform API (read-only workload)
	python -m evals.load --base-url http://127.0.0.1:8080

test-frontend-client: ## Test the frontend API client with Node only (no npm install)
	cd apps/frontend && node --test src/api/client.nodetest.ts

test: test-backend test-frontend test-cli test-python ## Run all tests

# ─── Lint ────────────────────────────────────────────────────────────────────
lint-backend: ## Run backend linters (Spotless + Checkstyle)
	cd apps/backend && mvn -B spotless:check checkstyle:check

lint-frontend: ## Run frontend linters (ESLint + Prettier)
	cd apps/frontend && npm run lint && npm run format:check

lint-cli: ## Run Go linters (gofmt check, vet; golangci-lint if installed)
	cd apps/cli && test -z "$$(gofmt -l .)" && go vet ./... && (command -v golangci-lint >/dev/null && golangci-lint run || true)

lint-python: ## Run Python lint, format check and strict type check
	ruff check ai skills evals sandbox tests && ruff format --check ai skills evals sandbox tests && mypy

lint: lint-backend lint-frontend lint-cli lint-python ## Run all linters

# ─── Format ──────────────────────────────────────────────────────────────────
fmt-backend: ## Format backend code (Spotless)
	cd apps/backend && mvn -B spotless:apply

fmt-frontend: ## Format frontend code (Prettier)
	cd apps/frontend && npm run format

fmt-cli: ## Format Go code
	cd apps/cli && gofmt -w .

fmt-python: ## Format Python code
	ruff format ai skills evals sandbox tests && ruff check --fix ai skills evals sandbox tests

fmt: fmt-backend fmt-frontend fmt-cli fmt-python ## Format all code

# ─── Docker ──────────────────────────────────────────────────────────────────
docker-up: ## Start all services with Docker Compose
	docker compose -f docker/docker-compose.yml up -d

docker-down: ## Stop all services
	docker compose -f docker/docker-compose.yml down

docker-logs: ## Tail logs from all services
	docker compose -f docker/docker-compose.yml logs -f

docker-build: ## Build all Docker images
	docker compose -f docker/docker-compose.yml build

# ─── Dev ─────────────────────────────────────────────────────────────────────
dev-backend: ## Run backend in dev mode
	cd apps/backend && mvn -B spring-boot:run -Dspring-boot.run.profiles=local

dev-frontend: ## Run frontend dev server
	cd apps/frontend && npm run dev

dev-cli: ## Build and install CLI locally
	cd apps/cli && go install ./cmd/copilot

# ─── Clean ───────────────────────────────────────────────────────────────────
clean: ## Clean all build artifacts
	cd apps/backend && mvn -B clean
	cd apps/frontend && rm -rf dist node_modules
	cd apps/cli && rm -rf bin/
	find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
