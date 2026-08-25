from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowChoice:
    code: str
    label: str


STAGE_CHOICES = (
    WorkflowChoice("pre_contract", "계약 준비"),
    WorkflowChoice("contract", "계약"),
    WorkflowChoice("kickoff", "착수"),
    WorkflowChoice("execution", "수행"),
    WorkflowChoice("inspection", "검사"),
    WorkflowChoice("closeout", "준공"),
    WorkflowChoice("billing", "청구/정산"),
)

EVENT_TYPE_CHOICES = (
    WorkflowChoice("estimate", "견적제출"),
    WorkflowChoice("contract_doc", "계약체결"),
    WorkflowChoice("contract_change", "계약변경"),
    WorkflowChoice("period_extension", "기간연장"),
    WorkflowChoice("suspend", "중지"),
    WorkflowChoice("resume", "재개"),
    WorkflowChoice("contract_cancel", "계약취소"),
    WorkflowChoice("kickoff", "착수"),
    WorkflowChoice("kickoff_doc", "착수계"),
    WorkflowChoice("progress_report", "공정보고"),
    WorkflowChoice("inspection_request", "검사요청"),
    WorkflowChoice("inspection", "검사완료"),
    WorkflowChoice("correction_request", "보완요청"),
    WorkflowChoice("reinspection", "재검사"),
    WorkflowChoice("completion_doc", "준공계 제출"),
    WorkflowChoice("delivery", "납품완료"),
    WorkflowChoice("closeout_complete", "완료"),
    WorkflowChoice("advance_payment", "선금"),
    WorkflowChoice("progress_invoice", "기성청구"),
    WorkflowChoice("invoice", "청구"),
    WorkflowChoice("tax_invoice", "세금계산서"),
    WorkflowChoice("payment", "입금/지급완료"),
    WorkflowChoice("etc", "기타"),
)

# Internal event record state is retained only for history integrity (open/void,
# draft compatibility, etc.). Contract business phase never reads these values.
STATUS_CHOICES = (
    WorkflowChoice("draft", "작성중"),
    WorkflowChoice("open", "진행중"),
    WorkflowChoice("done", "완료"),
    WorkflowChoice("void", "취소"),
)

# Only known historical tokens are normalized. Unknown/custom values are preserved
# so existing tenant history is never silently reinterpreted.
LEGACY_STAGE_ALIASES = {
    "project": "execution",
    "blilling": "billing",
}

EVENT_DEFAULT_STAGE = {
    "estimate": "pre_contract",
    "contract_doc": "contract",
    "contract_change": "contract",
    "period_extension": "contract",
    "suspend": "contract",
    "resume": "contract",
    "contract_cancel": "contract",
    "kickoff": "kickoff",
    "kickoff_doc": "kickoff",
    "progress_report": "execution",
    "inspection_request": "inspection",
    "inspection": "inspection",
    "correction_request": "inspection",
    "reinspection": "inspection",
    "completion_doc": "closeout",
    "delivery": "closeout",
    "closeout_complete": "closeout",
    "advance_payment": "billing",
    "progress_invoice": "billing",
    "invoice": "billing",
    "tax_invoice": "billing",
    "payment": "billing",
}

# Coarse Contract lifecycle is derived from the selected event stage, not the
# event type. This means, for example, stage=kickoff + type=etc still moves the
# contract to 진행, and any non-void stage=closeout event moves it to 준공.
CONTRACT_LIFECYCLE_STAGE_PHASES = {
    "pre_contract": "contract",
    "contract": "contract",
    "kickoff": "execution",
    "execution": "execution",
    "inspection": "execution",
    "closeout": "closeout",
}

# Final 완료 is intentionally different: it requires an explicit human action
# that records this dedicated event type under the 준공 stage.
CONTRACT_COMPLETION_EVENT_TYPE = "closeout_complete"

# Core event stages are system-required. Tenant settings may contain extra stages,
# but these core stages must always remain available and immutable.
REQUIRED_EVENT_STAGE_CODES = tuple(choice.code for choice in STAGE_CHOICES)


def normalize_stage(value: object) -> str:
    """Normalize only reviewed legacy aliases and preserve all other values."""

    text = str(value or "").strip()
    return LEGACY_STAGE_ALIASES.get(text, text)


def default_stage_for_event(event_type: object) -> str | None:
    return EVENT_DEFAULT_STAGE.get(str(event_type or "").strip())


def choice_pairs(choices) -> tuple[tuple[str, str], ...]:
    return tuple((choice.code, choice.label) for choice in choices)
