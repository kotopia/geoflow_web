from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowChoice:
    code: str
    label: str


# System semantics only; tenant-facing labels come from field_ref=event.stage.
STAGE_CHOICES = (
    WorkflowChoice("preparation", "준비"),
    WorkflowChoice("contract", "계약"),
    WorkflowChoice("kickoff", "착수"),
    WorkflowChoice("execution", "수행"),
    WorkflowChoice("closeout", "준공"),
    WorkflowChoice("complete", "완료"),
    WorkflowChoice("settlement", "정산"),
)

EVENT_TYPE_CHOICES = (
    WorkflowChoice("estimate", "견적"), WorkflowChoice("bid", "입찰"),
    WorkflowChoice("award", "낙찰"), WorkflowChoice("contract_sign", "체결"),
    WorkflowChoice("contract_change", "변경"), WorkflowChoice("contract_cancel", "취소"),
    WorkflowChoice("kickoff_doc", "착수계"), WorkflowChoice("kickoff_meeting", "착수회의"),
    WorkflowChoice("kickoff_approval", "착수승인"), WorkflowChoice("work_report", "업무보고"),
    WorkflowChoice("suspend", "중지"), WorkflowChoice("resume", "재개"),
    WorkflowChoice("completion_doc", "준공계"), WorkflowChoice("completion_inspection", "준공검사"),
    WorkflowChoice("completion_approval", "준공승인"), WorkflowChoice("advance_payment", "선급금"),
    WorkflowChoice("progress_payment", "기성금"), WorkflowChoice("final_payment", "준공금"),
)

# Internal state machine, intentionally not a tenant-editable setting.
STATUS_CHOICES = (
    WorkflowChoice("draft", "작성중"), WorkflowChoice("open", "진행중"),
    WorkflowChoice("done", "완료"), WorkflowChoice("void", "취소"),
)

LEGACY_STAGE_ALIASES = {
    "pre_contract": "preparation", "project": "execution",
    "inspection": "closeout", "billing": "settlement", "blilling": "settlement",
}

EVENT_DEFAULT_STAGE = {
    "estimate": "preparation", "bid": "preparation", "award": "preparation",
    "contract_sign": "contract", "contract_change": "contract", "contract_cancel": "contract",
    "kickoff_doc": "kickoff", "kickoff_meeting": "kickoff", "kickoff_approval": "kickoff",
    "work_report": "execution", "suspend": "execution", "resume": "execution",
    "completion_doc": "closeout", "completion_inspection": "closeout",
    "completion_approval": "closeout", "advance_payment": "settlement",
    "progress_payment": "settlement", "final_payment": "settlement",
}

CONTRACT_LIFECYCLE_STAGE_PHASES = {
    "preparation": "contract", "contract": "contract", "kickoff": "execution",
    "execution": "execution", "closeout": "closeout", "complete": "complete",
}

# 준공승인은 완료 Stage로 전환한다. 완료 Stage에는 자식 업무유형이 없다.
CONTRACT_COMPLETION_EVENT_TYPE = "completion_approval"
REQUIRED_EVENT_STAGE_CODES = tuple(choice.code for choice in STAGE_CHOICES)


def normalize_stage(value: object) -> str:
    text = str(value or "").strip()
    return LEGACY_STAGE_ALIASES.get(text, text)


def default_stage_for_event(event_type: object) -> str | None:
    return EVENT_DEFAULT_STAGE.get(str(event_type or "").strip())


def choice_pairs(choices) -> tuple[tuple[str, str], ...]:
    return tuple((choice.code, choice.label) for choice in choices)
