from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowChoice:
    code: str
    label: str


# GeoFlow Process Stage is one exact six-step lifecycle.
STAGE_CHOICES = (
    WorkflowChoice("preparation", "준비"),
    WorkflowChoice("contract", "계약"),
    WorkflowChoice("kickoff", "착수"),
    WorkflowChoice("execution", "수행"),
    WorkflowChoice("closeout", "준공"),
    WorkflowChoice("complete", "완료"),
)

# Event categories reuse Process Stage labels where possible, but settlement is
# deliberately an event-only category: finance can occur in parallel and never
# advances the technical Process Stage.
EVENT_CATEGORY_CHOICES = STAGE_CHOICES + (
    WorkflowChoice("settlement", "정산"),
)

EVENT_TYPE_CHOICES = (
    WorkflowChoice("estimate", "견적"),
    WorkflowChoice("bid", "입찰"),
    WorkflowChoice("award", "낙찰"),
    WorkflowChoice("contract_signed", "체결"),
    WorkflowChoice("contract_change", "변경"),
    WorkflowChoice("contract_cancel", "취소"),
    WorkflowChoice("kickoff_submitted", "착수계"),
    WorkflowChoice("kickoff_meeting", "착수회의"),
    WorkflowChoice("kickoff_approved", "착수승인"),
    WorkflowChoice("progress_report", "업무보고"),
    WorkflowChoice("suspend", "중지"),
    WorkflowChoice("resume", "재개"),
    WorkflowChoice("closeout_submitted", "준공계"),
    WorkflowChoice("closeout_inspection", "준공검사"),
    WorkflowChoice("closeout_approved", "준공승인"),
    WorkflowChoice("advance_payment", "선급금"),
    WorkflowChoice("progress_payment", "기성금"),
    WorkflowChoice("final_payment", "준공금"),
)

STATUS_CHOICES = (
    WorkflowChoice("draft", "작성중"),
    WorkflowChoice("open", "진행중"),
    WorkflowChoice("done", "완료"),
    WorkflowChoice("void", "취소"),
)

DEFAULT_HIGHLIGHT_DAYS = 7

LEGACY_STAGE_ALIASES = {
    "pre_contract": "preparation",
    "project": "execution",
    "inspection": "execution",
    "blilling": "billing",
}

# Retired system stage rows stay readable as history but are not Process Stage.
DEPRECATED_STAGE_CODES = frozenset({
    "pre_contract",
    "inspection",
    "billing",
    "blilling",
    "project",
})

# This is the event category used by the selector. For the six lifecycle groups
# it matches Process Stage; settlement is intentionally event-only.
EVENT_DEFAULT_STAGE = {
    "estimate": "preparation",
    "bid": "preparation",
    "award": "preparation",
    "contract_signed": "contract",
    "contract_change": "contract",
    "contract_cancel": "contract",
    "kickoff_submitted": "kickoff",
    "kickoff_meeting": "kickoff",
    "kickoff_approved": "kickoff",
    "progress_report": "execution",
    "suspend": "execution",
    "resume": "execution",
    "closeout_submitted": "closeout",
    "closeout_inspection": "closeout",
    "closeout_approved": "closeout",
    "advance_payment": "settlement",
    "progress_payment": "settlement",
    "final_payment": "settlement",
}

LEGACY_EVENT_DEFAULT_STAGE = {
    "contract_doc": "contract",
    "period_extension": "contract",
    "kickoff": "kickoff",
    "kickoff_doc": "kickoff",
    "inspection_request": "inspection",
    "inspection": "inspection",
    "correction_request": "inspection",
    "reinspection": "inspection",
    "completion_doc": "closeout",
    "delivery": "closeout",
    "closeout_complete": "closeout",
    # Old finance vocabulary remains readable. advance_payment is now canonical.
    "progress_invoice": "billing",
    "invoice": "billing",
    "tax_invoice": "billing",
    "payment": "billing",
    "etc": "execution",
}

EVENT_TRANSITION_TARGETS = {
    "contract_signed": "contract",
    "kickoff_submitted": "kickoff",
    "kickoff_approved": "execution",
    "closeout_submitted": "closeout",
    "closeout_approved": "complete",
}

LEGACY_EVENT_TRANSITION_TARGETS = {
    "contract_doc": "contract",
    "kickoff_doc": "kickoff",
    "kickoff": "execution",
    "completion_doc": "closeout",
    "closeout_complete": "complete",
}

CONTRACT_LIFECYCLE_STAGE_PHASES = {
    "preparation": "preparation",
    "contract": "contract",
    "kickoff": "kickoff",
    "execution": "execution",
    "closeout": "closeout",
    "complete": "complete",
}

CONTRACT_COMPLETION_EVENT_TYPE = "closeout_approved"
LEGACY_CONTRACT_COMPLETION_EVENT_TYPE = "closeout_complete"
EVENT_TYPE_WRITE_ALIASES = {
    LEGACY_CONTRACT_COMPLETION_EVENT_TYPE: CONTRACT_COMPLETION_EVENT_TYPE,
}

DEPRECATED_EVENT_TYPE_CODES = frozenset(LEGACY_EVENT_DEFAULT_STAGE)
REQUIRED_EVENT_STAGE_CODES = tuple(choice.code for choice in STAGE_CHOICES)


def normalize_stage(value: object) -> str:
    text = str(value or "").strip()
    return LEGACY_STAGE_ALIASES.get(text, text)


def normalize_event_type_for_write(value: object) -> str:
    code = str(value or "").strip()
    return EVENT_TYPE_WRITE_ALIASES.get(code, code)


def default_stage_for_event(event_type: object) -> str | None:
    code = str(event_type or "").strip()
    return EVENT_DEFAULT_STAGE.get(code) or LEGACY_EVENT_DEFAULT_STAGE.get(code)


def transition_stage_for_event(event_type: object) -> str | None:
    code = str(event_type or "").strip()
    return EVENT_TRANSITION_TARGETS.get(code) or LEGACY_EVENT_TRANSITION_TARGETS.get(code)


def is_canonical_event_type(event_type: object) -> bool:
    return str(event_type or "").strip() in EVENT_DEFAULT_STAGE


def choice_pairs(choices) -> tuple[tuple[str, str], ...]:
    return tuple((choice.code, choice.label) for choice in choices)
