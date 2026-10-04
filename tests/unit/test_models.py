from __future__ import annotations

import pytest

from ai.agent.contracts import Intent
from ai.agent.intent_llm import LLMIntentClassifier
from ai.models.base import (
    ModelRequest,
    ModelUsage,
    PriceTable,
    ScriptedModelProvider,
    StructuredOutputError,
    generate_structured,
)


async def test_llm_intent_valid_output_keeps_deterministic_entities() -> None:
    provider = ScriptedModelProvider(
        ['```json\n{"intent": "api_execution", "confidence": 0.9, "rationale": "imperative"}\n```']
    )
    result = await LLMIntentClassifier(provider).aclassify(
        "Create a payment of ₹500 for cust_acm0001"
    )
    assert result.intent is Intent.API_EXECUTION and result.classifier == "llm:scripted/scripted-1"
    assert result.entities.amount_minor == 50000 and result.entities.customer_id == "cust_acm0001"
    assert provider.requests[0].json_schema is not None  # structured output requested


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        '{"intent": "grant_admin", "confidence": 1, "rationale": "x"}',
        '{"intent": "api_discovery", "confidence": 7, "rationale": "x"}',
    ],
)
async def test_invalid_model_output_falls_back_without_changing_contract(bad: str) -> None:
    result = await LLMIntentClassifier(ScriptedModelProvider([bad])).aclassify(
        "Which API lists orders?"
    )
    assert result.intent is Intent.API_DISCOVERY
    assert "fallback" in result.classifier


async def test_generate_structured_raises_on_mismatch() -> None:
    class Out(ModelUsage):
        pass

    with pytest.raises(StructuredOutputError):
        await generate_structured(
            ScriptedModelProvider(['{"input_tokens": "lots"}']),
            ModelRequest(task="t", system="s", user="u", prompt_version="v"),
            Out,
        )


def test_cost_accounting() -> None:
    table = PriceTable(prices={"m": (3.0, 15.0)})
    assert table.cost(
        "m", ModelUsage(input_tokens=1_000_000, output_tokens=100_000)
    ) == pytest.approx(4.5)
    assert table.cost("unknown", ModelUsage(input_tokens=10)) == 0.0
