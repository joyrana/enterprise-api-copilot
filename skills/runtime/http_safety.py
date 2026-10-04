"""Outbound HTTP with SSRF defences, timeouts and response-size limits.

Rules (threat model T8):

* Only ``https``, or ``http`` for hosts explicitly listed in ``insecure_http_hosts``.
* No userinfo in URLs; host must be on the allowlist; port must be allowed.
* Every resolved address must be globally routable unless the host is explicitly
  listed in ``private_network_hosts`` (e.g. a local sandbox). Cloud metadata addresses
  are blocked unconditionally.
* Redirects are never followed; responses are streamed and capped.

Residual risk: the address is validated before httpx resolves it again (DNS rebinding
window). Production deployments should also restrict egress at the network layer.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from skills.runtime.errors import SkillError, SkillErrorCode

Resolver = Callable[[str, int], Awaitable[list[str]]]

_METADATA_ADDRESSES = frozenset(
    {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}
)

RESPONSE_HEADER_ALLOWLIST = frozenset(
    {
        "content-type",
        "location",
        "retry-after",
        "x-correlation-id",
        "x-request-id",
        "idempotency-replayed",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
        "www-authenticate",
    }
)


class OutboundPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed_hosts: frozenset[str]
    allowed_ports: frozenset[int] = frozenset({443})
    insecure_http_hosts: frozenset[str] = frozenset()
    private_network_hosts: frozenset[str] = frozenset()
    max_response_bytes: int = Field(default=1_000_000, gt=0)
    timeout_s: float = Field(default=10.0, gt=0)
    use_env_proxy: bool = False


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def _blocked(message: str) -> SkillError:
    return SkillError(SkillErrorCode.DESTINATION_BLOCKED, message)


async def validate_destination(
    url: str, policy: OutboundPolicy, resolver: Resolver = system_resolver
) -> httpx.URL:
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, ValueError) as exc:
        raise _blocked("invalid URL") from exc
    host = (parsed.host or "").lower().rstrip(".")
    if not host:
        raise _blocked("URL has no host")
    if parsed.userinfo:
        raise _blocked("credentials in URL are not allowed")
    if parsed.scheme == "http":
        if host not in policy.insecure_http_hosts:
            raise _blocked("plain HTTP is only allowed for explicitly configured local hosts")
    elif parsed.scheme != "https":
        raise _blocked(f"scheme '{parsed.scheme}' is not allowed")
    if host not in policy.allowed_hosts:
        raise _blocked(f"host '{host}' is not on the outbound allowlist")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in policy.allowed_ports:
        raise _blocked(f"port {port} is not allowed")

    try:
        addresses = await resolver(host, port)
    except OSError as exc:
        raise SkillError(SkillErrorCode.UPSTREAM_UNAVAILABLE, f"cannot resolve '{host}'") from exc
    if not addresses:
        raise SkillError(SkillErrorCode.UPSTREAM_UNAVAILABLE, f"cannot resolve '{host}'")
    for raw in addresses:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
        if ip in _METADATA_ADDRESSES:
            raise _blocked("cloud metadata endpoints are never reachable")
        if not ip.is_global and host not in policy.private_network_hosts:
            raise _blocked(f"host '{host}' resolves to a non-public address")
    return parsed


class SafeResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    body: Any
    body_bytes: int
    elapsed_ms: float

    @property
    def correlation_id(self) -> str | None:
        return self.headers.get("x-correlation-id") or self.headers.get("x-request-id")


class SafeHttpClient:
    def __init__(
        self,
        policy: OutboundPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
    ) -> None:
        self._policy = policy
        self._transport = transport
        self._resolver = resolver

    @property
    def policy(self) -> OutboundPolicy:
        return self._policy

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        json_body: Any = None,
        form: Mapping[str, str] | None = None,
    ) -> SafeResponse:
        target = await validate_destination(url, self._policy, self._resolver)
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._policy.timeout_s,
                follow_redirects=False,
                trust_env=self._policy.use_env_proxy,
            ) as client:
                async with client.stream(
                    method.upper(),
                    target,
                    headers=dict(headers or {}),
                    params=dict(params or {}),
                    json=json_body,
                    data=dict(form) if form is not None else None,
                ) as response:
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self._policy.max_response_bytes:
                            raise SkillError(
                                SkillErrorCode.RESPONSE_TOO_LARGE,
                                f"response exceeded {self._policy.max_response_bytes} bytes",
                            )
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    status = response.status_code
                    resp_headers = {
                        k.lower(): v
                        for k, v in response.headers.items()
                        if k.lower() in RESPONSE_HEADER_ALLOWLIST
                    }
        except httpx.TimeoutException as exc:
            raise SkillError(SkillErrorCode.TIMEOUT, "upstream request timed out") from exc
        except httpx.TransportError as exc:
            raise SkillError(SkillErrorCode.UPSTREAM_UNAVAILABLE, "upstream unreachable") from exc

        body: Any
        if "json" in resp_headers.get("content-type", ""):
            try:
                body = json.loads(raw)
            except ValueError:
                body = raw.decode("utf-8", errors="replace")
        else:
            body = raw.decode("utf-8", errors="replace")
        return SafeResponse(
            status_code=status,
            headers=resp_headers,
            body=body,
            body_bytes=len(raw),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
