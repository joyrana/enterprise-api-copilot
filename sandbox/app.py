"""Synthetic sandbox gateway implementing ``specs/payments-v1.yaml`` and ``specs/orders-v1.yaml``.

What it simulates (for tests, demos and evaluation — never real money or data):

* OAuth 2.0 client-credentials token endpoint with per-client tenants and scopes;
* scope enforcement (401 vs 403), per-tenant data partitioning;
* ``Idempotency-Key`` semantics (replay vs 409 conflict);
* request validation (422), rate limiting (429 + Retry-After);
* ``X-Correlation-Id`` on every response;
* fault injection via ``X-Sandbox-Fault: 500|503|429|slow`` when enabled.

Client secrets are generated at start-up unless supplied, so none are committed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

TOKEN_TTL_S = 900
_CUSTOMER_RE = re.compile(r"^cust_[a-z0-9]{6,}$")
_PAYMENT_RE = re.compile(r"^pay_[A-Za-z0-9]{8,}$")


@dataclass
class SandboxClient:
    client_id: str
    client_secret: str
    tenant_id: str
    scopes: frozenset[str]


@dataclass
class SandboxConfig:
    clients: dict[str, SandboxClient] = field(default_factory=dict)
    rate_limit_per_minute: int = 60
    fault_injection: bool = True
    slow_fault_s: float = 2.0

    @classmethod
    def default(cls) -> SandboxConfig:
        full = frozenset(
            {
                "payments:read",
                "payments:write",
                "refunds:write",
                "customers:read",
                "orders:read",
                "orders:write",
            }
        )
        clients = [
            SandboxClient("acme-sandbox-app", secrets.token_urlsafe(24), "acme", full),
            SandboxClient(
                "acme-readonly-app",
                secrets.token_urlsafe(24),
                "acme",
                frozenset({"payments:read", "customers:read", "orders:read"}),
            ),
            SandboxClient("globex-sandbox-app", secrets.token_urlsafe(24), "globex", full),
        ]
        return cls(clients={c.client_id: c for c in clients})


@dataclass
class _Token:
    tenant_id: str
    client_id: str
    scopes: frozenset[str]
    expires_at: float


@dataclass
class _TenantData:
    payments: dict[str, dict[str, Any]] = field(default_factory=dict)
    customers: dict[str, dict[str, Any]] = field(default_factory=dict)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency: dict[str, tuple[str, int, dict[str, Any]]] = field(default_factory=dict)


def _seed(tenant: str) -> _TenantData:
    data = _TenantData()
    for i, name in enumerate(["Asha Rao", "Ben Ortiz", "Chen Wei"], start=1):
        cid = f"cust_{tenant[:3]}{i:04d}"
        data.customers[cid] = {
            "id": cid,
            "name": f"{name} ({tenant})",
            "email": f"user{i}@{tenant}.example.invalid",
        }
    for i, (amount, status) in enumerate(
        [(50000, "authorized"), (125000, "captured"), (9900, "refunded")], start=1
    ):
        pid = f"pay_{tenant[:3]}{i:08d}"
        data.payments[pid] = {
            "id": pid,
            "amount": amount,
            "currency": "INR",
            "customer_id": f"cust_{tenant[:3]}{i:04d}",
            "status": status,
            "refunds": [],
            "created_at": 1_700_000_000 + i,
        }
    data.orders["ord_1001"] = {
        "id": "ord_1001",
        "customer_id": f"cust_{tenant[:3]}0001",
        "items": [{"sku": "SKU-1", "quantity": 2}],
        "fulfilment_status": "shipped",
    }
    return data


class SandboxState:
    def __init__(self, config: SandboxConfig) -> None:
        self.config = config
        self.tokens: dict[str, _Token] = {}
        self.tenants: dict[str, _TenantData] = {}
        self.requests: dict[str, list[float]] = {}

    def tenant(self, tenant_id: str) -> _TenantData:
        if tenant_id not in self.tenants:
            self.tenants[tenant_id] = _seed(tenant_id)
        return self.tenants[tenant_id]


def _error(status: int, code: str, message: str, cid: str, **extra: Any) -> JSONResponse:
    headers = {"X-Correlation-Id": cid, **extra.pop("headers", {})}
    return JSONResponse(
        {"error": {"code": code, "message": message, **extra}}, status_code=status, headers=headers
    )


_Handler = Callable[[Request, _Token, str], Awaitable[Response]]


def create_app(config: SandboxConfig | None = None) -> Starlette:
    state = SandboxState(config or SandboxConfig.default())

    def protected(scope: str) -> Callable[[_Handler], Callable[[Request], Awaitable[Response]]]:
        def decorator(fn: _Handler) -> Callable[[Request], Awaitable[Response]]:
            async def endpoint(request: Request) -> Response:
                cid = request.headers.get("x-correlation-id") or f"corr_{uuid.uuid4().hex[:16]}"
                fault = (
                    request.headers.get("x-sandbox-fault") if state.config.fault_injection else None
                )
                if fault == "slow":
                    await asyncio.sleep(state.config.slow_fault_s)
                elif fault in {"500", "503"}:
                    return _error(int(fault), "INJECTED_FAULT", "injected fault", cid)
                auth = request.headers.get("authorization", "")
                if not auth.lower().startswith("bearer "):
                    return _error(
                        401,
                        "UNAUTHENTICATED",
                        "missing bearer token",
                        cid,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                token = state.tokens.get(auth[7:].strip())
                if token is None or token.expires_at <= time.time():
                    return _error(
                        401,
                        "UNAUTHENTICATED",
                        "invalid or expired token",
                        cid,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                window = [
                    t for t in state.requests.get(token.client_id, []) if t > time.time() - 60
                ]
                if fault == "429" or len(window) >= state.config.rate_limit_per_minute:
                    return _error(
                        429,
                        "RATE_LIMITED",
                        "rate limit exceeded",
                        cid,
                        headers={"Retry-After": "30"},
                    )
                window.append(time.time())
                state.requests[token.client_id] = window
                if scope not in token.scopes:
                    return _error(
                        403,
                        "INSUFFICIENT_SCOPE",
                        f"token lacks required scope {scope}",
                        cid,
                        required_scope=scope,
                    )
                response = await fn(request, token, cid)
                response.headers["X-Correlation-Id"] = cid
                return response

            return endpoint

        return decorator

    async def idempotent(
        request: Request,
        token: _Token,
        cid: str,
        create: Callable[[dict[str, Any]], tuple[int, dict[str, Any]]],
        body: dict[str, Any],
    ) -> Response:
        key = request.headers.get("idempotency-key")
        if not key:
            return _error(
                400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required", cid
            )
        data = state.tenant(token.tenant_id)
        fingerprint = hashlib.sha256(
            (request.url.path + json.dumps(body, sort_keys=True)).encode()
        ).hexdigest()
        if key in data.idempotency:
            prior_hash, status, payload = data.idempotency[key]
            if prior_hash != fingerprint:
                return _error(
                    409, "IDEMPOTENCY_CONFLICT", "key reused with a different request", cid
                )
            return JSONResponse(
                payload, status_code=status, headers={"Idempotency-Replayed": "true"}
            )
        status, payload = create(body)
        if status < 500:
            data.idempotency[key] = (fingerprint, status, payload)
        return JSONResponse(payload, status_code=status)

    async def token_endpoint(request: Request) -> Response:
        cid = f"corr_{uuid.uuid4().hex[:16]}"
        form = await request.form()
        if form.get("grant_type") != "client_credentials":
            return _error(
                400, "unsupported_grant_type", "only client_credentials is supported", cid
            )
        client = state.config.clients.get(str(form.get("client_id", "")))
        if client is None or not secrets.compare_digest(
            client.client_secret, str(form.get("client_secret", ""))
        ):
            return _error(401, "invalid_client", "client authentication failed", cid)
        requested = frozenset(str(form.get("scope", "")).split()) or client.scopes
        if not requested <= client.scopes:
            return _error(400, "invalid_scope", "requested scope not allowed for this client", cid)
        access = secrets.token_urlsafe(32)
        state.tokens[access] = _Token(
            client.tenant_id, client.client_id, requested, time.time() + TOKEN_TTL_S
        )
        return JSONResponse(
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": TOKEN_TTL_S,
                "scope": " ".join(sorted(requested)),
            },
            headers={"X-Correlation-Id": cid, "Cache-Control": "no-store"},
        )

    def _limit(request: Request) -> int | None:
        try:
            limit = int(request.query_params.get("limit", "20"))
        except ValueError:
            return None
        return limit if 1 <= limit <= 100 else None

    @protected("payments:read")
    async def list_payments(request: Request, token: _Token, cid: str) -> Response:
        limit = _limit(request)
        if limit is None:
            return _error(422, "VALIDATION_ERROR", "limit must be between 1 and 100", cid)
        items = sorted(
            state.tenant(token.tenant_id).payments.values(), key=lambda p: -p["created_at"]
        )
        if status := request.query_params.get("status"):
            items = [p for p in items if p["status"] == status]
        if customer := request.query_params.get("customer_id"):
            items = [p for p in items if p["customer_id"] == customer]
        return JSONResponse({"data": items[:limit], "count": min(len(items), limit)})

    def _validate_payment(body: Any) -> list[str]:
        errors: list[str] = []
        if not isinstance(body, dict):
            return ["body must be a JSON object"]
        unknown = set(body) - {"amount", "currency", "customer_id", "description"}
        if unknown:
            errors.append(f"unknown fields: {sorted(unknown)}")
        amount = body.get("amount")
        if (
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or not 100 <= amount <= 10_000_000
        ):
            errors.append("amount must be an integer between 100 and 10000000")
        if body.get("currency") not in {"INR", "USD", "EUR"}:
            errors.append("currency must be one of INR, USD, EUR")
        if not isinstance(body.get("customer_id"), str) or not _CUSTOMER_RE.match(
            body["customer_id"]
        ):
            errors.append("customer_id must match ^cust_[a-z0-9]{6,}$")
        return errors

    @protected("payments:write")
    async def create_payment(request: Request, token: _Token, cid: str) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return _error(422, "VALIDATION_ERROR", "body must be valid JSON", cid)
        errors = _validate_payment(body)
        if errors:
            return _error(422, "VALIDATION_ERROR", "request validation failed", cid, details=errors)

        def create(b: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            pid = f"pay_{secrets.token_hex(6)}"
            payment = {
                **b,
                "id": pid,
                "status": "authorized",
                "refunds": [],
                "created_at": int(time.time()),
            }
            state.tenant(token.tenant_id).payments[pid] = payment
            return 201, payment

        return await idempotent(request, token, cid, create, body)

    @protected("payments:read")
    async def get_payment(request: Request, token: _Token, cid: str) -> Response:
        pid = request.path_params["payment_id"]
        payment = (
            state.tenant(token.tenant_id).payments.get(pid) if _PAYMENT_RE.match(pid) else None
        )
        if payment is None:
            return _error(404, "NOT_FOUND", "payment not found", cid)
        return JSONResponse(payment)

    @protected("payments:write")
    async def cancel_payment(request: Request, token: _Token, cid: str) -> Response:
        pid = request.path_params["payment_id"]
        payments = state.tenant(token.tenant_id).payments

        def cancel(_: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            payment = payments.get(pid)
            if payment is None:
                return 404, {"error": {"code": "NOT_FOUND", "message": "payment not found"}}
            if payment["status"] != "authorized":
                return 409, {
                    "error": {"code": "INVALID_STATE", "message": f"payment is {payment['status']}"}
                }
            payment["status"] = "cancelled"
            return 200, payment

        return await idempotent(request, token, cid, cancel, {"cancel": pid})

    @protected("refunds:write")
    async def refund_payment(request: Request, token: _Token, cid: str) -> Response:
        pid = request.path_params["payment_id"]
        try:
            body = await request.json()
        except ValueError:
            return _error(422, "VALIDATION_ERROR", "body must be valid JSON", cid)
        payments = state.tenant(token.tenant_id).payments

        def refund(b: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            payment = payments.get(pid)
            if payment is None:
                return 404, {"error": {"code": "NOT_FOUND", "message": "payment not found"}}
            amount = b.get("amount")
            refunded = sum(r["amount"] for r in payment["refunds"])
            if not isinstance(amount, int) or amount < 1 or amount + refunded > payment["amount"]:
                return 422, {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "refund exceeds refundable balance",
                    }
                }
            refund_record = {
                "id": f"rfnd_{secrets.token_hex(6)}",
                "amount": amount,
                "reason": b.get("reason"),
            }
            payment["refunds"].append(refund_record)
            if amount + refunded == payment["amount"]:
                payment["status"] = "refunded"
            return 201, {**refund_record, "payment_id": pid}

        return await idempotent(request, token, cid, refund, body if isinstance(body, dict) else {})

    @protected("customers:read")
    async def list_customers(request: Request, token: _Token, cid: str) -> Response:
        limit = _limit(request) or 20
        return JSONResponse(
            {"data": list(state.tenant(token.tenant_id).customers.values())[:limit]}
        )

    @protected("customers:read")
    async def get_customer(request: Request, token: _Token, cid: str) -> Response:
        customer = state.tenant(token.tenant_id).customers.get(request.path_params["customer_id"])
        if customer is None:
            return _error(404, "NOT_FOUND", "customer not found", cid)
        return JSONResponse(customer)

    @protected("orders:read")
    async def list_orders(request: Request, token: _Token, cid: str) -> Response:
        orders = list(state.tenant(token.tenant_id).orders.values())
        if status := request.query_params.get("fulfilment_status"):
            orders = [o for o in orders if o["fulfilment_status"] == status]
        return JSONResponse({"data": orders})

    @protected("orders:write")
    async def create_order(request: Request, token: _Token, cid: str) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return _error(422, "VALIDATION_ERROR", "body must be valid JSON", cid)
        if not isinstance(body, dict) or not body.get("items") or not body.get("customer_id"):
            return _error(
                422, "VALIDATION_ERROR", "customer_id and at least one item are required", cid
            )

        def create(b: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            oid = f"ord_{secrets.token_hex(4)}"
            order = {**b, "id": oid, "fulfilment_status": "pending"}
            state.tenant(token.tenant_id).orders[oid] = order
            return 201, order

        return await idempotent(request, token, cid, create, body)

    @protected("orders:read")
    async def get_order(request: Request, token: _Token, cid: str) -> Response:
        order = state.tenant(token.tenant_id).orders.get(request.path_params["order_id"])
        if order is None:
            return _error(404, "NOT_FOUND", "order not found", cid)
        return JSONResponse(order)

    @protected("orders:read")
    async def get_shipment(request: Request, token: _Token, cid: str) -> Response:
        order = state.tenant(token.tenant_id).orders.get(request.path_params["order_id"])
        if order is None or order["fulfilment_status"] == "pending":
            return _error(404, "NOT_FOUND", "no shipment for this order", cid)
        return JSONResponse(
            {
                "order_id": order["id"],
                "carrier": "SyntheticExpress",
                "tracking_number": f"SX{order['id'][-4:]}",
                "events": [{"status": "shipped"}],
            }
        )

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "UP", "service": "sandbox-gateway"})

    app = Starlette(
        routes=[
            Route("/healthz", health),
            Route("/oauth/token", token_endpoint, methods=["POST"]),
            Route("/v1/payments", list_payments, methods=["GET"]),
            Route("/v1/payments", create_payment, methods=["POST"]),
            Route("/v1/payments/{payment_id}", get_payment, methods=["GET"]),
            Route("/v1/payments/{payment_id}", cancel_payment, methods=["DELETE"]),
            Route("/v1/payments/{payment_id}/refunds", refund_payment, methods=["POST"]),
            Route("/v1/customers", list_customers, methods=["GET"]),
            Route("/v1/customers/{customer_id}", get_customer, methods=["GET"]),
            Route("/v2/orders", list_orders, methods=["GET"]),
            Route("/v2/orders", create_order, methods=["POST"]),
            Route("/v2/orders/{order_id}", get_order, methods=["GET"]),
            Route("/v2/orders/{order_id}/shipment", get_shipment, methods=["GET"]),
        ]
    )
    app.state.sandbox = state
    return app
