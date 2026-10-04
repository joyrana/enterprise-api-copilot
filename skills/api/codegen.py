"""Equivalent request snippets (cURL, Python, JavaScript, Java) for an API call.

Rules:
* Credentials are **never** embedded. Snippets read the token from ``$COPILOT_TOKEN``.
* Only ``Content-Type``, ``Accept``, ``Idempotency-Key`` and ``X-Correlation-Id`` headers
  are emitted; other header values are dropped.
* Strings are escaped per language (``shlex.quote`` for shell, JSON escaping elsewhere).
  Snippets are returned as text and never executed (threat model T9/T11).
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlencode

Language = Literal["curl", "python", "javascript", "java"]
ALL_LANGUAGES: tuple[Language, ...] = ("curl", "python", "javascript", "java")
_ALLOWED_HEADERS = ("Idempotency-Key", "X-Correlation-Id")


def _url(base_url: str, path: str, query: Mapping[str, Any]) -> str:
    qs = urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in query.items()})
    return f"{base_url}{path}" + (f"?{qs}" if qs else "")


def _headers(body: Any, extra: Mapping[str, str]) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for name in _ALLOWED_HEADERS:
        for key, value in extra.items():
            if key.lower() == name.lower():
                headers[name] = value
    return headers


def curl(method: str, url: str, headers: Mapping[str, str], body: Any) -> str:
    parts = [
        f"curl -sS -X {method.upper()} {shlex.quote(url)}",
        '-H "Authorization: Bearer $COPILOT_TOKEN"',
    ]
    parts += [f"-H {shlex.quote(f'{k}: {v}')}" for k, v in headers.items()]
    if body is not None:
        parts.append(f"--data {shlex.quote(json.dumps(body, separators=(',', ':')))}")
    return " \\\n  ".join(parts)


def python(method: str, url: str, headers: Mapping[str, str], body: Any) -> str:
    lines = [
        "import os",
        "",
        "import httpx",
        "",
        "headers = {"
        + '"Authorization": f"Bearer {os.environ[\'COPILOT_TOKEN\']}", '
        + f"**{json.dumps(dict(headers))}}}",
        "response = httpx.request(",
        f"    {json.dumps(method.upper())},",
        f"    {json.dumps(url)},",
        "    headers=headers,",
    ]
    if body is not None:
        lines.append(f"    json=json.loads({json.dumps(json.dumps(body))}),")
        lines.insert(0, "import json")
    lines += ["    timeout=30,", ")", "print(response.status_code, response.text)"]
    return "\n".join(lines) + "\n"


def javascript(method: str, url: str, headers: Mapping[str, str], body: Any) -> str:
    header_obj = {"Authorization": "__TOKEN__", **headers}
    rendered = json.dumps(header_obj, indent=2).replace(
        '"__TOKEN__"', "`Bearer ${process.env.COPILOT_TOKEN}`"
    )
    body_line = f"\n  body: JSON.stringify({json.dumps(body)})," if body is not None else ""
    return (
        f"const response = await fetch({json.dumps(url)}, {{\n"
        f"  method: {json.dumps(method.upper())},\n"
        f"  headers: {rendered.replace(chr(10), chr(10) + '  ')},{body_line}\n"
        "});\n"
        "console.log(response.status, await response.text());\n"
    )


def java(method: str, url: str, headers: Mapping[str, str], body: Any) -> str:
    publisher = (
        f"HttpRequest.BodyPublishers.ofString({json.dumps(json.dumps(body))})"
        if body is not None
        else "HttpRequest.BodyPublishers.noBody()"
    )
    header_lines = "".join(
        f"\n    .header({json.dumps(k)}, {json.dumps(v)})" for k, v in headers.items()
    )
    return (
        "import java.net.URI;\n"
        "import java.net.http.HttpClient;\n"
        "import java.net.http.HttpRequest;\n"
        "import java.net.http.HttpResponse;\n\n"
        "HttpClient client = HttpClient.newHttpClient();\n"
        "HttpRequest request = HttpRequest.newBuilder()\n"
        f"    .uri(URI.create({json.dumps(url)}))\n"
        '    .header("Authorization", "Bearer " + System.getenv("COPILOT_TOKEN"))'
        f"{header_lines}\n"
        f"    .method({json.dumps(method.upper())}, {publisher})\n"
        "    .build();\n"
        "HttpResponse<String> response = client.send(request, "
        "HttpResponse.BodyHandlers.ofString());\n"
        'System.out.println(response.statusCode() + " " + response.body());\n'
    )


_RENDERERS = {"curl": curl, "python": python, "javascript": javascript, "java": java}


def render(
    *,
    method: str,
    base_url: str,
    path: str,
    query: Mapping[str, Any] | None = None,
    body: Any = None,
    headers: Mapping[str, str] | None = None,
    languages: tuple[Language, ...] = ALL_LANGUAGES,
) -> dict[str, str]:
    url = _url(base_url, path, query or {})
    hdrs = _headers(body, headers or {})
    return {lang: _RENDERERS[lang](method, url, hdrs, body) for lang in languages}
