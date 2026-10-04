# Contributing to Enterprise API Copilot

Thank you for your interest in contributing to Enterprise API Copilot! This project follows enterprise engineering standards and we hold contributions to a high bar. Please read this guide thoroughly before submitting a pull request.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Branching Strategy](#branching-strategy)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Code Quality](#code-quality)
- [Testing Requirements](#testing-requirements)
- [Documentation](#documentation)

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/enterprise-api-copilot.git
   cd enterprise-api-copilot
   ```
3. **Add the upstream remote**:
   ```bash
   git remote add upstream https://github.com/joyrana/enterprise-api-copilot.git
   ```
4. Set up your [development environment](#development-setup).

---

## Development Setup

### Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Java | 21 |
| Go | 1.22 |
| Node.js | 20 |
| Python | 3.12 |
| Docker | 24+ |
| Docker Compose | 2.x |

### Backend

```bash
cd apps/backend
./mvnw clean verify
./mvnw spring-boot:run -Dspring-boot.run.profiles=local
```

### Frontend

```bash
cd apps/frontend
npm ci
npm run lint
npm run build
npm run dev
```

### CLI

```bash
cd apps/cli
go mod download
go build ./...
go test ./...
```

### AI Agents

```bash
cd agents
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Branching Strategy

We follow **GitHub Flow** with a protected `main` branch.

| Branch Pattern | Purpose |
|---|---|
| `main` | Production-ready code. Protected. |
| `feat/<issue-number>-short-description` | New features |
| `fix/<issue-number>-short-description` | Bug fixes |
| `docs/<description>` | Documentation changes |
| `chore/<description>` | Tooling, dependencies, refactoring |
| `release/v<version>` | Release preparation |

**Never push directly to `main`.** All changes must go through a pull request.

---

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

[optional body]

[optional footer(s)]
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`

**Examples**:
```
feat(backend): add Copilot chat endpoint with streaming support
fix(cli): handle token expiry gracefully in ask command
docs(adr): add ADR-0002 for vector database selection
chore(deps): upgrade Spring Boot to 3.3.2
```

---

## Pull Request Process

1. Create your branch from the latest `main`.
2. Implement your change with tests.
3. Run all checks locally before pushing:
   ```bash
   # Backend
   cd apps/backend && ./mvnw spotless:check checkstyle:check verify

   # Frontend
   cd apps/frontend && npm run lint && npm run type-check && npm test

   # CLI
   cd apps/cli && golangci-lint run && go test ./...
   ```
4. Push to your fork and open a PR against `main`.
5. Fill out the pull request template completely.
6. Request a review from at least **2 maintainers**.
7. Address all review comments before merging.

### PR Requirements Checklist

- [ ] All CI checks pass
- [ ] Unit tests added / updated
- [ ] Integration tests added (for API changes)
- [ ] Documentation updated (if behavior changes)
- [ ] CHANGELOG entry added
- [ ] No secrets or credentials committed
- [ ] No TODO/FIXME left unaddressed (unless tracked in an issue)

---

## Code Quality

Please read [docs/coding-standards.md](docs/coding-standards.md) for detailed standards.

- **Java**: Google Java Style Guide + Checkstyle + Spotless
- **Go**: `gofmt` + `golangci-lint`
- **TypeScript/React**: ESLint + Prettier
- **Python**: `ruff` + `black`

---

## Testing Requirements

| Component | Minimum Coverage | Test Types Required |
|---|---|---|
| Backend | 80% line coverage | Unit, Integration, Contract |
| CLI | 70% line coverage | Unit, E2E |
| Frontend | 70% line coverage | Unit (Vitest), Component (Testing Library) |
| Agents | 60% line coverage | Unit, Integration |

---

## Documentation

- All public APIs must have Javadoc / GoDoc / JSDoc
- New features must include a section in the relevant `docs/` file
- Architecture changes must be captured in an [ADR](docs/adr/)

---

## Maintainers

| Name | GitHub | Area |
|------|--------|------|
| Core Team | @enterprise-api-copilot/maintainers | All |

For questions, open a [Discussion](https://github.com/joyrana/enterprise-api-copilot/discussions) rather than an issue.
