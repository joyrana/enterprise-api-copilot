"""HTTP plumbing shared by both APIs: errors, request IDs, auth, body limits.

Error bodies use the platform ``ApiError`` shape (``code``, ``message``, ``requestId``,
``path``, ``timestamp``) — the same fields as the backend's ``ApiErrorResponse``.
Unexpected exceptions return a generic 500 and are logged by type only.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ai.api.auth import AuthError, TokenAuthority, bearer
from ai.api.runs import RunConflictError, RunForbiddenError, RunNotFoundError
from ai.telemetry import parse_traceparent, trace_scope
from skills.runtime.contracts import Principal

_log = logging.getLogger("copilot.api")
MAX_BODY_BYTES = 64 * 1024
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
M = TypeVar("M", bound=BaseModel)


class ApiProblemError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    return supplied if _REQUEST_ID.match(supplied) else f"req_{uuid.uuid4().hex[:16]}"


def error(request: Request, rid: str, status: int, code: str, message: str) -> JSONResponse:
    body = {
        "code": code,
        "message": message,
        "requestId": rid,
        "path": request.url.path,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return JSONResponse(body, status_code=status, headers={"X-Request-Id": rid})


async def parse_body(request: Request, model: type[M]) -> M:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise ApiProblemError(413, "PAYLOAD_TOO_LARGE", "request body too large")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise ApiProblemError(413, "PAYLOAD_TOO_LARGE", "request body too large")
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) or "(body)" for e in exc.errors()[:5])
        raise ApiProblemError(400, "VALIDATION_ERROR", f"invalid request body: {fields}") from exc


Handler = Callable[[Request, Principal | None], Awaitable[Response]]


def endpoint(
    handler: Handler, *, authority: TokenAuthority | None
) -> Callable[[Request], Awaitable[Response]]:
    """Wrap a handler with request IDs, optional bearer auth and error mapping."""

    async def wrapped(request: Request) -> Response:
        with trace_scope(parse_traceparent(request.headers.get("traceparent"))) as trace:
            response = await _handle(request)
            response.headers["traceparent"] = trace.traceparent()
            return response

    async def _handle(request: Request) -> Response:
        rid = request_id(request)
        try:
            principal = None
            if authority is not None:
                try:
                    principal = authority.verify(bearer(request.headers.get("authorization")))
                except AuthError as exc:
                    denied = error(request, rid, 401, "UNAUTHENTICATED", str(exc))
                    denied.headers["WWW-Authenticate"] = "Bearer"
                    return denied
            response = await handler(request, principal)
        except ApiProblemError as exc:
            return error(request, rid, exc.status, exc.code, exc.message)
        except RunNotFoundError:
            return error(request, rid, 404, "RESOURCE_NOT_FOUND", "run not found")
        except RunConflictError as exc:
            return error(request, rid, 409, "CONFLICT", str(exc))
        except RunForbiddenError as exc:
            return error(request, rid, 403, "ACCESS_DENIED", str(exc))
        except Exception as exc:
            _log.exception(
                "unhandled error on %s %s (%s)",
                request.method,
                request.url.path,
                type(exc).__name__,
            )
            return error(request, rid, 500, "INTERNAL_ERROR", "An unexpected error occurred.")
        response.headers["X-Request-Id"] = rid
        return response

    return wrapped


def json(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status)
