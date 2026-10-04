from __future__ import annotations

import json

import httpx
import pytest

from ai.models.anthropic import API_VERSION, AnthropicProvider
from ai.models.base import ModelRequest, PriceTable, ScriptedModelProvider
from evals.judge import calibrate, cohens_kappa, load_items


def test_kappa() -> None:
    assert cohens_kappa([0, 1, 2, 2], [0, 1, 2, 2]) == 1.0
    assert cohens_kappa([0, 0, 1, 1], [1, 1, 0, 0]) == -1.0
    assert cohens_kappa([], []) is None


async def test_calibration_agreement_consistency_and_parse_failures() -> None:
    items = load_items()
    assert len(items) == 16 and all(i.human_score is not None for i in items)
    perfect = [json.dumps({"score": i.human_score, "reason": "r"}) for i in items]
    result = await calibrate(ScriptedModelProvider(perfect * 2), items, repeats=2)
    assert (
        result["human_agreement"]["exact"] == 1.0
        and result["human_agreement"]["cohens_kappa"] == 1.0
    )
    assert result["consistency"]["stable_fraction"] == 1.0 and result["parse_failures"] == 0

    # Second run flips one item and emits one unparseable verdict.
    noisy = perfect[:]
    noisy[0] = json.dumps({"score": 0, "reason": "flip"})
    noisy[1] = "not json"
    result = await calibrate(ScriptedModelProvider(perfect + noisy), items, repeats=2)
    assert result["parse_failures"] == 1
    assert result["consistency"]["stable_fraction"] == pytest.approx(14 / 16)
    assert "not ground truth" in result["note"]


async def test_anthropic_provider_request_shape_and_usage() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": '{"score": 2, "reason": "ok"}'}],
                "usage": {"input_tokens": 1000, "output_tokens": 20},
            },
        )

    provider = AnthropicProvider(
        "test-key-not-real",
        transport=httpx.MockTransport(handler),
        prices=PriceTable(prices={"claude-sonnet-5-5": (3.0, 15.0)}),
    )
    response = await provider.generate(
        ModelRequest(
            task="judge",
            system="SYS",
            untrusted_context="DOC",
            user="Q",
            prompt_version="v",
            max_output_tokens=50,
        )
    )
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    headers = seen["headers"]
    assert (
        headers["x-api-key"] == "test-key-not-real" and headers["anthropic-version"] == API_VERSION
    )  # type: ignore[index]
    body = seen["body"]
    assert body["system"] == "SYS" and body["max_tokens"] == 50  # type: ignore[index]
    assert body["messages"][0]["content"].startswith("<untrusted_context>\nDOC")  # type: ignore[index]
    assert "DOC" not in body["system"]  # type: ignore[index]
    assert (
        response.usage.input_tokens == 1000
        and response.usage.estimated_cost_usd == pytest.approx(0.0033)
    )


def test_provider_requires_key() -> None:
    with pytest.raises(ValueError):
        AnthropicProvider("")
