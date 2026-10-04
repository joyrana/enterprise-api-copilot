"""Intent classification.

``RuleBasedIntentClassifier`` is deterministic and is the default (principle 4). An
LLM classifier can be layered on top through ``ai.models`` (see ``LLMIntentClassifier``);
on invalid model output it falls back to the rules and records that it did, so a fallback
never changes the output contract.

Entity extraction is always deterministic: identifiers, amounts, status codes and tokens
are parsed with patterns, never inferred by a model.
"""

from __future__ import annotations

import re
from typing import Protocol

from ai.agent.contracts import Entities, Intent, IntentResult

_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_PAYMENT = re.compile(r"\bpay_[A-Za-z0-9]{8,}\b")
_CUSTOMER = re.compile(r"\bcust_[a-z0-9]{6,}\b")
_ORDER = re.compile(r"\bord_[A-Za-z0-9]{3,}\b")
_STATUS = re.compile(r"\b(4\d\d|5\d\d)\b")
_AMOUNT = re.compile(
    r"(?:(?P<sym>₹|rs\.?|inr|\$|usd|€|eur)\s*(?P<a>\d[\d,]*(?:\.\d{1,2})?))|(?:(?P<b>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<sym2>rupees|inr|usd|dollars|eur|euros))",
    re.IGNORECASE,
)
_CURRENCY = {
    "₹": "INR",
    "rs": "INR",
    "rs.": "INR",
    "inr": "INR",
    "rupees": "INR",
    "$": "USD",
    "usd": "USD",
    "dollars": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euros": "EUR",
}
_LANGS = {
    "python": "python",
    "java": "java",
    "javascript": "javascript",
    "js": "javascript",
    "node": "javascript",
    "curl": "curl",
}

_HARMFUL = re.compile(
    r"\b(steal|exfiltrat\w*|bypass (the )?(approval|auth\w*|policy)|disable (the )?(approval|audit|logging)|"
    r"other tenants?'?s? (data|payments|customers)|all tenants|drop table|sql injection|ddos|brute.?force|"
    r"(card|credit card) numbers? (of|for) (all|every))\b",
    re.IGNORECASE,
)
_OFF_TOPIC = re.compile(
    r"\b(weather|recipe|joke|poem|movie|football|cricket score|horoscope|stock tips?|write (me )?a song)\b",
    re.IGNORECASE,
)
_DISCOVERY = re.compile(
    r"\b(which|what|find|search|discover|is there|are there|list (all |the )?(available )?(apis?|endpoints?|operations?))\b.{0,40}\b(apis?|endpoints?|operations?)\b"
    r"|\bendpoints? (for|to)\b|\bapis? (for|to)\b",
    re.IGNORECASE | re.DOTALL,
)
_EXPLAIN = re.compile(
    r"\b(explain|describe|how does|how do i (call|use|authenticate)|what (scopes?|parameters?|fields?|headers?)|"
    r"schema (of|for)|request body (of|for)|what does .{1,40} (require|need|return))\b",
    re.IGNORECASE,
)
_CODE = re.compile(
    r"\b(curl|snippet|code (sample|example)|sample code|sdk example|in (python|java|javascript|node|go))\b",
    re.IGNORECASE,
)
_TROUBLE = re.compile(
    r"\b(error|errors|failing|fails|failed|troubleshoot\w*|not working|unauthori[sz]ed|forbidden|denied|rejected|"
    r"rate.?limit(ed)?|too many requests|conflict|why (am i|is|does|do))\b",
    re.IGNORECASE,
)
_TOKEN_WORDS = re.compile(
    r"\b(decode|inspect|check|analy[sz]e)\b.{0,30}\b(jwt|token)\b", re.IGNORECASE
)
_EXEC = re.compile(
    r"^\s*(please\s+)?(create|make|charge|refund|cancel|void|list|get|fetch|retrieve|show( me)?|look up|track|place)\b",
    re.IGNORECASE,
)
_EXEC_OBJECTS = re.compile(r"\b(payments?|refunds?|customers?|orders?|shipments?)\b", re.IGNORECASE)
_STATUS_WORDS = ("authorized", "captured", "refunded", "cancelled")


def extract_entities(query: str) -> Entities:
    ent = Entities()
    if m := _JWT.search(query):
        ent.jwt = m.group(0)
    if m := _PAYMENT.search(query):
        ent.payment_id = m.group(0)
    if m := _CUSTOMER.search(query):
        ent.customer_id = m.group(0)
    if m := _ORDER.search(query):
        ent.order_id = m.group(0)
    scrubbed = _JWT.sub(" ", query)
    amount_match = _AMOUNT.search(scrubbed)
    # Amounts are removed before looking for status codes so "₹500" is not read as HTTP 500.
    ent.status_codes = sorted({int(code) for code in _STATUS.findall(_AMOUNT.sub(" ", scrubbed))})
    if m := amount_match:
        raw = (m.group("a") or m.group("b") or "0").replace(",", "")
        symbol = (m.group("sym") or m.group("sym2") or "").lower()
        ent.currency = _CURRENCY.get(symbol)
        ent.amount_minor = round(float(raw) * 100)
    lowered = query.lower()
    for word, env in (
        ("production", "production"),
        ("prod ", "production"),
        ("staging", "staging"),
        ("sandbox", "sandbox"),
    ):
        if word in lowered + " ":
            ent.environment = env
            break
    ent.languages = sorted(
        {lang for word, lang in _LANGS.items() if re.search(rf"\b{re.escape(word)}\b", lowered)}
    )
    ent.status_filter = next((w for w in _STATUS_WORDS if w in lowered), None)
    if "duplicate" in lowered:
        ent.refund_reason = "duplicate"
    elif "fraud" in lowered:
        ent.refund_reason = "fraudulent"
    elif "refund" in lowered:
        ent.refund_reason = "requested_by_customer"
    return ent


def operation_query(query: str) -> str:
    """The request with argument values (ids, amounts, tokens) removed.

    Used for operation search: identifiers describe *which resource*, not *which
    operation*, and their character n-grams bias lexical-hash similarity.
    """
    for pattern in (_JWT, _PAYMENT, _CUSTOMER, _ORDER, _AMOUNT):
        query = pattern.sub(" ", query)
    return " ".join(query.split())


class IntentClassifier(Protocol):
    name: str

    def classify(self, query: str) -> IntentResult: ...


class RuleBasedIntentClassifier:
    name = "rules-v1"

    def classify(self, query: str) -> IntentResult:
        ent = extract_entities(query)
        text = query.strip()

        def result(intent: Intent, confidence: float, why: str) -> IntentResult:
            return IntentResult(
                intent=intent,
                confidence=confidence,
                entities=ent,
                rationale=why,
                classifier=self.name,
            )

        if len(text) < 3 or (len(re.findall(r"\w+", text)) < 2 and not ent.jwt):
            return result(Intent.CLARIFICATION_NEEDED, 0.6, "request too short to act on")
        if _HARMFUL.search(text):
            return result(
                Intent.UNSUPPORTED, 0.95, "request asks for a prohibited or harmful action"
            )
        if _OFF_TOPIC.search(text) and not _EXEC_OBJECTS.search(text):
            return result(Intent.UNSUPPORTED, 0.9, "request is unrelated to APIs")
        if ent.jwt and (_TOKEN_WORDS.search(text) or not _TROUBLE.search(text)):
            return result(Intent.TOKEN_INSPECTION, 0.95, "message contains a JWT to inspect")
        if ent.status_codes or _TROUBLE.search(text):
            return result(Intent.TROUBLESHOOTING, 0.85, "mentions an error status or failure")
        if _CODE.search(text):
            return result(Intent.CODE_GENERATION, 0.85, "asks for code or a cURL example")
        if _EXPLAIN.search(text):
            return result(Intent.API_EXPLANATION, 0.8, "asks how an operation works")
        if _DISCOVERY.search(text):
            return result(Intent.API_DISCOVERY, 0.8, "asks which API/endpoint to use")
        if _EXEC.search(text) and _EXEC_OBJECTS.search(text):
            return result(
                Intent.API_EXECUTION, 0.8, "imperative request on a payments/orders resource"
            )
        if _EXEC_OBJECTS.search(text) and len(re.findall(r"\w+", text)) <= 2:
            return result(Intent.CLARIFICATION_NEEDED, 0.6, "names a resource but no action")
        return result(Intent.DOCS_QUESTION, 0.6, "general question answered from documentation")
