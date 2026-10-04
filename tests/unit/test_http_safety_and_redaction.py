from __future__ import annotations

import httpx
import pytest

from skills.runtime.errors import SkillError, SkillErrorCode
from skills.runtime.http_safety import OutboundPolicy, SafeHttpClient, validate_destination
from skills.runtime.redaction import REDACTED, contains_secret, redact, redact_text

POLICY = OutboundPolicy(
    allowed_hosts=frozenset({"api.example.com", "sandbox.local", "evil.example.com"}),
    allowed_ports=frozenset({443, 80}),
    insecure_http_hosts=frozenset({"sandbox.local"}),
    private_network_hosts=frozenset({"sandbox.local"}),
    max_response_bytes=100,
)

DNS = {
    "api.example.com": ["93.184.216.34"],
    "sandbox.local": ["127.0.0.1"],
    "evil.example.com": ["10.1.2.3"],  # allowlisted name that resolves privately (rebinding-style)
    "meta.example.com": ["169.254.169.254"],
}


async def resolver(host: str, port: int) -> list[str]:
    return DNS.get(host, [])


async def blocked(url: str, policy: OutboundPolicy = POLICY) -> str:
    with pytest.raises(SkillError) as info:
        await validate_destination(url, policy, resolver)
    assert info.value.code in (
        SkillErrorCode.DESTINATION_BLOCKED,
        SkillErrorCode.UPSTREAM_UNAVAILABLE,
    )
    return info.value.message


async def test_allowed_destinations() -> None:
    assert (
        await validate_destination("https://api.example.com/v1/x", POLICY, resolver)
    ).host == "api.example.com"
    assert (
        await validate_destination("http://sandbox.local/v1", POLICY, resolver)
    ).host == "sandbox.local"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://api.example.com/", "plain HTTP"),
        ("ftp://api.example.com/", "scheme"),
        ("https://user:pw@api.example.com/", "credentials"),
        ("https://other.example.com/", "allowlist"),
        ("https://127.0.0.1/", "allowlist"),
        ("https://evil.example.com/", "non-public"),
        ("https://api.example.com:8443/", "port"),
        ("file:///etc/passwd", "no host"),
    ],
)
async def test_blocked_destinations(url: str, reason: str) -> None:
    assert reason in await blocked(url)


async def test_metadata_blocked_even_when_allowlisted() -> None:
    policy = POLICY.model_copy(
        update={
            "allowed_hosts": frozenset({"meta.example.com"}),
            "private_network_hosts": frozenset({"meta.example.com"}),
        }
    )
    assert "metadata" in await blocked("https://meta.example.com/latest", policy)


async def test_response_size_cap_and_no_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/big":
            return httpx.Response(200, content=b"x" * 500)
        return httpx.Response(
            302, headers={"Location": "http://169.254.169.254/", "Set-Cookie": "s=1"}
        )

    client = SafeHttpClient(POLICY, transport=httpx.MockTransport(handler), resolver=resolver)
    with pytest.raises(SkillError) as info:
        await client.request("GET", "https://api.example.com/big")
    assert info.value.code is SkillErrorCode.RESPONSE_TOO_LARGE
    redirect = await client.request("GET", "https://api.example.com/redirect")
    assert redirect.status_code == 302  # returned, not followed
    assert "set-cookie" not in redirect.headers  # response headers are allowlisted


async def test_transport_errors_are_classified() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = SafeHttpClient(POLICY, transport=httpx.MockTransport(boom), resolver=resolver)
    with pytest.raises(SkillError) as info:
        await client.request("GET", "https://api.example.com/")
    assert info.value.code is SkillErrorCode.UPSTREAM_UNAVAILABLE and info.value.retryable


def test_redaction_patterns() -> None:
    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJlLXZhbHVl"
    text = f"Authorization: Bearer abc123def456ghi and token {jwt_like} key AKIAABCDEFGHIJKLMNOP"
    out = redact_text(text)
    assert "abc123def456ghi" not in out and jwt_like not in out and "AKIA" not in out
    assert contains_secret(text) and not contains_secret(out)
    assert redact_text("https://bob:hunter2@host/x") == f"https://{REDACTED}@host/x"


def test_key_based_redaction_is_recursive() -> None:
    data = {
        "client_secret": "x",
        "nested": [{"password": "p", "amount": 5}],
        "Authorization": "Bearer y",
    }
    assert redact(data) == {
        "client_secret": REDACTED,
        "nested": [{"password": REDACTED, "amount": 5}],
        "Authorization": REDACTED,
    }
