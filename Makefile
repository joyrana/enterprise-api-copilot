# Enterprise API Copilot — Makefile
# Provides top-level targets for the most common developer tasks.

.PHONY: help build test lint clean docker-up docker-down

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ─── Help ────────────────────────────────────────────────────────────────────
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ─── Build ───────────────────────────────────────────────────────────────────
build-backend: ## Build the Spring Boot backend
	cd apps/backend && ./mvnw clean package -DskipTests

build-frontend: ## Build the React frontend
	cd apps/frontend && npm ci && npm run build

build-cli: ## Build the Go CLI binary
	cd apps/cli && go build -o bin/copilot ./cmd/copilot

build: build-backend build-frontend build-cli ## Build all components

# ─── Test ────────────────────────────────────────────────────────────────────
test-backend: ## Run backend tests
	cd apps/backend && ./mvnw verify

test-frontend: ## Run frontend tests
	cd apps/frontend && npm test

test-cli: ## Run CLI tests
	cd apps/cli && go test ./...

test-agents: ## Run agent and skill tests
	pytest agents/ skills/ -v

test: test-backend test-frontend test-cli test-agents ## Run all tests

# ─── Lint ────────────────────────────────────────────────────────────────────
lint-backend: ## Run backend linters (Spotless + Checkstyle)
	cd apps/backend && ./mvnw spotless:check checkstyle:check

lint-frontend: ## Run frontend linters (ESLint + Prettier)
	cd apps/frontend && npm run lint && npm run format:check

lint-cli: ## Run Go linter
	cd apps/cli && golangci-lint run

lint-agents: ## Run Python linters
	ruff check agents/ skills/ && black --check agents/ skills/

lint: lint-backend lint-frontend lint-cli lint-agents ## Run all linters

# ─── Format ──────────────────────────────────────────────────────────────────
fmt-backend: ## Format backend code (Spotless)
	cd apps/backend && ./mvnw spotless:apply

fmt-frontend: ## Format frontend code (Prettier)
	cd apps/frontend && npm run format

fmt-cli: ## Format Go code
	cd apps/cli && gofmt -w .

fmt-agents: ## Format Python code
	black agents/ skills/ && ruff check --fix agents/ skills/

fmt: fmt-backend fmt-frontend fmt-cli fmt-agents ## Format all code

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
	cd apps/backend && ./mvnw spring-boot:run -Dspring-boot.run.profiles=local

dev-frontend: ## Run frontend dev server
	cd apps/frontend && npm run dev

dev-cli: ## Build and install CLI locally
	cd apps/cli && go install ./cmd/copilot

# ─── Clean ───────────────────────────────────────────────────────────────────
clean: ## Clean all build artifacts
	cd apps/backend && ./mvnw clean
	cd apps/frontend && rm -rf dist node_modules
	cd apps/cli && rm -rf bin/
	find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
