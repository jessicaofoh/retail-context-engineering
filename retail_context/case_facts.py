"""Case-facts extraction into a persistent block at the top of context.

Extraction is LLM-driven: one Claude call against the full transcript that returns
strict JSON for the 12 required fields. This is commonly called a *scratchpad* — same
concept, different word: a dense structured block that survives compression and is
placed at the top boundary of context so the model can recover transactional facts
without scanning thousands of tokens of narrative.

Missing-field behavior raises `CaseFactExtractionError` listing the gaps — silent
null-fill is forbidden.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from retail_context.client import complete_with_system, get_model
from retail_context.transcript import Transcript

REQUIRED_FIELDS: tuple[str, ...] = (
    "customer_id",
    "refund_order_id",
    "refund_amount_usd",
    "refund_status",
    "subscription_id",
    "subscription_plan",
    "subscription_cancel_reason",
    "subscription_status",
    "active_payment_method_last4",
    "new_payment_method_last4",
    "payment_update_failure_code",
    "payment_update_status",
)


@dataclass
class CaseFacts:
    customer_id: str
    refund_order_id: str
    refund_amount_usd: float
    refund_status: str
    subscription_id: str
    subscription_plan: str
    subscription_cancel_reason: str
    subscription_status: str
    active_payment_method_last4: str
    new_payment_method_last4: str
    payment_update_failure_code: str
    payment_update_status: str

    def to_markdown(self) -> str:
        """Render the block with a level-1 header and the fixed key order."""
        lines = [
            "# Case Facts",
            "",
            f"**Customer** — customer_id: {self.customer_id}",
            "",
            "**Refund (resolved)** — "
            f"refund_order_id: {self.refund_order_id}; "
            f"refund_amount_usd: {self.refund_amount_usd}; "
            f"refund_status: {self.refund_status}",
            "",
            "**Subscription (resolved)** — "
            f"subscription_id: {self.subscription_id}; "
            f"subscription_plan: {self.subscription_plan}; "
            f"subscription_cancel_reason: {self.subscription_cancel_reason}; "
            f"subscription_status: {self.subscription_status}",
            "",
            "**Payment update (active)** — "
            f"active_payment_method_last4: {self.active_payment_method_last4}; "
            f"new_payment_method_last4: {self.new_payment_method_last4}; "
            f"payment_update_failure_code: {self.payment_update_failure_code}; "
            f"payment_update_status: {self.payment_update_status}",
        ]
        return "\n".join(lines)


class CaseFactExtractionError(ValueError):
    def __init__(self, missing: list[str], raw: dict[str, Any]):
        super().__init__(f"case-facts extraction missing required fields: {missing}")
        self.missing = missing
        self.raw = raw


_SYSTEM_PROMPT = (
    "You extract structured case facts from a retail customer-support transcript.\n"
    "Return EXACTLY one JSON object with these 12 keys and nothing else:\n"
    "customer_id, refund_order_id, refund_amount_usd, refund_status, "
    "subscription_id, subscription_plan, subscription_cancel_reason, "
    "subscription_status, active_payment_method_last4, new_payment_method_last4, "
    "payment_update_failure_code, payment_update_status.\n"
    "Types: refund_amount_usd is a JSON number (no currency symbol). "
    "active_payment_method_last4 and new_payment_method_last4 are strings of "
    "exactly four digits, zero-padded, taken verbatim from the transcript. "
    "All IDs and status tokens are strings preserved byte-exact as they appear "
    "in the transcript (keep snake_case status tokens like in_progress verbatim; "
    "do not translate them into natural language).\n"
    "If a value is genuinely absent from the transcript, use null. DO NOT "
    "invent, infer, or approximate a value that is not present.\n"
    "Output requirements: JSON only. No prose, no markdown, no code fences, "
    "no comments, no trailing text."
)


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.rstrip().endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


def extract(
    transcript: Transcript,
    *,
    model: str | None = None,
    log_path: Path | None = None,
) -> CaseFacts:
    user = f"Transcript:\n\n{transcript.full_text}"
    text, input_tokens, output_tokens = complete_with_system(
        _SYSTEM_PROMPT, user, model=model, max_tokens=2048
    )
    raw = _parse_json(text)

    if log_path is not None:
        log_path.write_text(
            json.dumps(
                {
                    "model": model or get_model(),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "parsed": raw,
                },
                indent=2,
            )
        )

    missing = [
        f for f in REQUIRED_FIELDS
        if f not in raw or raw[f] is None or raw[f] == ""
    ]
    if missing:
        raise CaseFactExtractionError(missing=missing, raw=raw)

    return CaseFacts(
        customer_id=str(raw["customer_id"]),
        refund_order_id=str(raw["refund_order_id"]),
        refund_amount_usd=float(raw["refund_amount_usd"]),
        refund_status=str(raw["refund_status"]),
        subscription_id=str(raw["subscription_id"]),
        subscription_plan=str(raw["subscription_plan"]),
        subscription_cancel_reason=str(raw["subscription_cancel_reason"]),
        subscription_status=str(raw["subscription_status"]),
        active_payment_method_last4=str(raw["active_payment_method_last4"]),
        new_payment_method_last4=str(raw["new_payment_method_last4"]),
        payment_update_failure_code=str(raw["payment_update_failure_code"]),
        payment_update_status=str(raw["payment_update_status"]),
    )


def to_dict(facts: CaseFacts) -> dict[str, Any]:
    return asdict(facts)
