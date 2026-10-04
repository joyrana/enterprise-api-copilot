"""Gateway adapter for runtime API calls (Apigee runtime proxies or the local sandbox).

* The base URL per environment comes **only** from configuration — never from a spec's
  ``servers`` block or from model output (threat model T2/T5).
* Management-plane integrations (deploying proxies, reading analytics) are a different
  concern and are deliberately not part of this adapter.
* Access tokens are obtained with OAuth client credentials, cached per scope set until
  shortly before expiry, and never returned to callers or written to logs.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ai.telemetry import outbound_traceparent
from skills.runtime.errors import SkillError, SkillErrorCode
from skills.runtime.http_safety import SafeHttpClient, SafeResponse


class GatewayEnvironment(BaseModel):
    """Runtime gateway settings for one environment (e.g. ``sandbox``)."""

    model_config = ConfigDict(frozen=True)

    name: str
    base_url: str = Field(
        description="Runtime proxy base URL, e.g. https://api-sandbox.example.com"
    )
    token_url: str
    client_id: str
    client_secret: SecretStr
    kind: str = Field(default="apigee-runtime", description="apigee-runtime | sandbox")


class TokenProvider:
    def __init__(
        self,
        env: GatewayEnvironment,
        http: SafeHttpClient,
        *,
        clock: Callable[[], float] = time.time,
        refresh_margin_s: float = 30.0,
    ) -> None:
        self._env = env
        self._http = http
        self._clock = clock
        self._margin = refresh_margin_s
        self._cache: dict[frozenset[str], tuple[str, float]] = {}

    async def token(self, scopes: frozenset[str]) -> str:
        cached = self._cache.get(scopes)
        if cached and cached[1] - self._margin > self._clock():
            return cached[0]
        response = await self._http.request(
            "POST",
            self._env.token_url,
            form={
                "grant_type": "client_credentials",
                "client_id": self._env.client_id,
                "client_secret": self._env.client_secret.get_secret_value(),
                "scope": " ".join(sorted(scopes)),
            },
        )
        if response.status_code != 200 or not isinstance(response.body, dict):
            raise SkillError(
                SkillErrorCode.UPSTREAM_ERROR,
                f"token endpoint returned HTTP {response.status_code}",
                details={"status_code": response.status_code},
            )
        access = response.body.get("access_token")
        expires_in = response.body.get("expires_in", 300)
        if not isinstance(access, str) or not isinstance(expires_in, int | float):
            raise SkillError(
                SkillErrorCode.UPSTREAM_ERROR, "token endpoint returned an invalid payload"
            )
        self._cache[scopes] = (access, self._clock() + float(expires_in))
        return access


def expand_path(template: str, path_params: Mapping[str, str]) -> str:
    """Fill ``{name}`` placeholders, percent-encoding each value as a single segment."""
    out = template
    for name, value in path_params.items():
        placeholder = "{" + name + "}"
        if placeholder not in out:
            raise SkillError(SkillErrorCode.INVALID_INPUT, f"unknown path parameter '{name}'")
        if value in {".", ".."} or not value:
            raise SkillError(
                SkillErrorCode.INVALID_INPUT, f"invalid value for path parameter '{name}'"
            )
        out = out.replace(placeholder, quote(value, safe=""))
    if "{" in out:
        raise SkillError(SkillErrorCode.INVALID_INPUT, "missing required path parameters")
    return out


class ApiGateway:
    def __init__(
        self, environments: Mapping[str, GatewayEnvironment], http: SafeHttpClient
    ) -> None:
        self._envs = dict(environments)
        self._http = http
        self._tokens = {name: TokenProvider(env, http) for name, env in self._envs.items()}

    def base_url(self, environment: str) -> str:
        env = self._envs.get(environment)
        if env is None:
            raise SkillError(
                SkillErrorCode.NOT_CONFIGURED,
                f"no gateway configured for environment '{environment}'",
            )
        return env.base_url.rstrip("/")

    async def call(
        self,
        *,
        environment: str,
        method: str,
        path: str,
        scopes: frozenset[str],
        query: Mapping[str, str] | None = None,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        correlation_id: str,
    ) -> SafeResponse:
        url = self.base_url(environment) + path
        token = await self._tokens[environment].token(scopes)
        request_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Correlation-Id": correlation_id,
            **dict(headers or {}),
        }
        traceparent = outbound_traceparent()
        if traceparent:
            request_headers["traceparent"] = traceparent
        return await self._http.request(
            method, url, headers=request_headers, params=query, json_body=body
        )
