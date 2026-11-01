"""Build the agent's model provider from configuration.

``ollama`` (default for processes started from the environment) talks to a local Ollama
server; ``anthropic`` uses the Messages API; ``none`` runs the deterministic stack only
(tests, CI and air-gapped installs).
"""

from __future__ import annotations

import os

from ai.models.base import ModelProvider

PROVIDERS = ("ollama", "anthropic", "none")


def build_provider(
    provider: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    timeout_s: float = 120.0,
) -> ModelProvider | None:
    if provider == "none":
        return None
    if provider == "ollama":
        from ai.models.ollama import DEFAULT_BASE_URL, DEFAULT_MODEL, OllamaProvider

        return OllamaProvider(
            model=model or DEFAULT_MODEL,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout_s=timeout_s,
        )
    if provider == "anthropic":
        from ai.models.anthropic import DEFAULT_MODEL as CLAUDE_DEFAULT
        from ai.models.anthropic import AnthropicProvider

        return AnthropicProvider(
            os.environ.get("ANTHROPIC_API_KEY", ""),
            model=model or CLAUDE_DEFAULT,
            base_url=base_url or "https://api.anthropic.com",
            timeout_s=timeout_s,
        )
    raise ValueError(f"unknown LLM provider '{provider}' (expected one of {', '.join(PROVIDERS)})")
