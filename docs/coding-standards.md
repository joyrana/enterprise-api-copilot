# Coding Standards

> Enterprise API Copilot — Engineering Standards Reference

All contributors must follow these standards. Code reviews will enforce them. CI will automatically fail on violations.

---

## Table of Contents

1. [General Principles](#1-general-principles)
2. [Java (Backend)](#2-java-backend)
3. [Go (CLI)](#3-go-cli)
4. [TypeScript / React (Frontend)](#4-typescript--react-frontend)
5. [Python (Agents)](#5-python-agents)
6. [Testing Standards](#6-testing-standards)
7. [API Design Standards](#7-api-design-standards)
8. [Git Standards](#8-git-standards)

---

## 1. General Principles

- **Clarity over cleverness** — Write code that any senior engineer can understand in 30 seconds.
- **No magic numbers** — Extract constants with meaningful names.
- **Single responsibility** — Every class, function, and module does one thing well.
- **Fail fast** — Validate inputs at boundaries. Never pass invalid state deeper into the system.
- **No silent failures** — Log or propagate every error. Never swallow exceptions.
- **TODO policy** — Every `TODO` must reference a GitHub issue: `// TODO(#123): Implement pagination`.

---

## 2. Java (Backend)

### Style

- **Google Java Style Guide** enforced via Checkstyle and Spotless.
- **4-space indentation** (no tabs).
- **Line length**: 120 characters maximum.
- **Braces**: Always required, even for single-line if/else.

### Naming

| Element | Convention | Example |
|---|---|---|
| Class | `PascalCase` | `ConversationService` |
| Method | `camelCase` | `findBySessionId` |
| Constant | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Package | `lowercase.dots` | `io.enterprise.copilot.domain` |

### Architecture Rules

- Domain classes **must not** import from `infrastructure` or `adapter` packages.
- Use cases **must not** directly access repositories — only through ports.
- Controllers **must not** contain business logic — delegate to use cases.
- Never use `@Autowired` on fields — use constructor injection only.

### Exception Handling

```java
// ✅ Correct: Throw typed domain exceptions
throw new ApiNotFoundException("API with id " + apiId + " not found");

// ❌ Wrong: Throw generic RuntimeException
throw new RuntimeException("not found");

// ✅ Correct: Use global exception handler
@RestControllerAdvice
public class GlobalExceptionHandler { ... }
```

### Logging

```java
// ✅ Correct: Use structured logging with context
log.info("Executing API call: apiId={}, method={}, url={}", apiId, method, url);

// ❌ Wrong: String concatenation in log
log.info("Executing API call: " + apiId);

// ✅ Use MDC for trace context
MDC.put("traceId", traceId);
MDC.put("sessionId", sessionId);
```

---

## 3. Go (CLI)

### Style

- All code must pass `gofmt` and `golangci-lint`.
- **goimports** for import ordering.
- Follow [Effective Go](https://go.dev/doc/effective_go) and the [Go Code Review Comments](https://github.com/golang/go/wiki/CodeReviewComments).

### Naming

| Element | Convention | Example |
|---|---|---|
| Package | `lowercase` | `commands` |
| Exported | `PascalCase` | `AskCommand` |
| Unexported | `camelCase` | `buildRequest` |
| Error vars | `ErrXxx` | `ErrTokenExpired` |
| Interfaces | noun / `er` suffix | `APIClient`, `Stringer` |

### Error Handling

```go
// ✅ Correct: Wrap errors with context
if err != nil {
    return fmt.Errorf("executing ask command: %w", err)
}

// ❌ Wrong: Ignore errors
result, _ := client.Ask(ctx, query)

// ✅ Correct: Define sentinel errors
var ErrTokenExpired = errors.New("authentication token has expired")
```

### CLI UX Rules

- Every command must show a spinner for operations > 300ms.
- Every command must support `--output json` for scripting.
- Every destructive command must prompt for confirmation unless `--yes` is passed.
- Errors must be written to `stderr`, output to `stdout`.

---

## 4. TypeScript / React (Frontend)

### Style

- **ESLint** + **Prettier** enforced via CI.
- **2-space indentation**.
- `"strict": true` in `tsconfig.json`.
- No `any` types without a justification comment.

### Component Standards

```tsx
// ✅ Correct: Named exports, no default exports for components
export function ChatMessage({ message, role }: ChatMessageProps) {
  // ...
}

// ✅ Correct: Define props with TypeScript interface
interface ChatMessageProps {
  message: string;
  role: 'user' | 'assistant' | 'system';
  timestamp: Date;
}
```

### State Management

- **Local state** (`useState`) for component-specific state.
- **React Query** for server state (API calls, caching).
- **Zustand** for global UI state (theme, auth, navigation).
- Never store server data in global state — use React Query.

### File Naming

| Element | Convention | Example |
|---|---|---|
| Component | `PascalCase.tsx` | `ChatMessage.tsx` |
| Hook | `useCamelCase.ts` | `useConversation.ts` |
| Service | `camelCase.service.ts` | `copilot.service.ts` |
| Types | `camelCase.types.ts` | `conversation.types.ts` |

---

## 5. Python (Agents)

### Style

- **Black** for formatting, **Ruff** for linting.
- **4-space indentation**.
- Type hints are **required** on all public functions.

```python
# ✅ Correct: Typed, documented
async def plan_execution(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    Generate an execution plan from the current agent state.

    Args:
        state: Current LangGraph agent state.
        config: LangGraph runnable configuration.

    Returns:
        Updated state dict with 'plan' field populated.
    """
    ...
```

---

## 6. Testing Standards

### Testing Pyramid

```
         ┌──────┐
         │  E2E │  (few, slow, high confidence)
        ┌┴──────┴┐
        │Integration│  (moderate count)
       ┌┴──────────┴┐
       │    Unit     │  (many, fast, isolated)
       └─────────────┘
```

### Java Test Conventions

- Unit tests in `src/test/java` with `*Test.java` suffix.
- Integration tests with `*IT.java` suffix.
- Use `@SpringBootTest(webEnvironment = RANDOM_PORT)` for integration tests.
- Mock external dependencies with `@MockBean` or WireMock.
- Test class names mirror the class under test: `ConversationServiceTest`.

### Go Test Conventions

- Tests in `_test.go` files in the same package.
- Use `testify/assert` for assertions.
- Table-driven tests for multiple cases.

### Frontend Test Conventions

- Tests in `__tests__/` directories or `.test.tsx` colocated files.
- Use **Vitest** for unit/component tests.
- Use **Testing Library** for component interaction.
- No snapshot tests for dynamic content.

---

## 7. API Design Standards

### REST API

- **Versioning**: All APIs are versioned at `/api/v1/`.
- **Resource naming**: Plural nouns (`/conversations`, `/executions`).
- **HTTP methods**: Follow REST semantics strictly.
- **Response envelope**:

```json
{
  "data": { },
  "meta": {
    "requestId": "req_abc123",
    "timestamp": "2026-08-04T10:30:00Z"
  }
}
```

- **Error response**:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Conversation with id conv_123 not found",
    "requestId": "req_abc123",
    "timestamp": "2026-08-04T10:30:00Z"
  }
}
```

- **Pagination**: Always paginate list endpoints.

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "pageSize": 20,
    "total": 245
  }
}
```

---

## 8. Git Standards

See [CONTRIBUTING.md](../CONTRIBUTING.md) for branching and commit conventions.

Additional rules:

- **No force push** to any shared branch.
- **No merge commits** — use rebase and fast-forward merges.
- **No binary files** in the repository (use Git LFS or external storage).
- Every commit must leave the build in a passing state.
