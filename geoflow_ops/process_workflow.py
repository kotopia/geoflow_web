from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowChoice:
    code: str
    label: str


# GeoFlow process lifecycle. Billing/settlement is intentionally not a process
# stage because financial events may happen in parallel with, or long after,
# technical completion.
STAGE_CHOICES = (
    WorkflowChoice("preparation", "준비"),
    WorkflowChoice("contract", "계약"),
    WorkflowChoice("kickoff", "착수"),
    WorkflowChoice("execution", "수행"),
    WorkflowChoice("closeout", "준공"),
    WorkflowChoice("complete", "완료"),
)

# Canonical event vocabulary for the first process-stage rollout. Work-scope and
# finance event vocabularies are deliberately left out of this boundary.
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
    WorkflowChoice("suspend", "용역중지"),
    WorkflowChoice("resume", "용역재개"),
    WorkflowChoice("closeout_submitted", "준공계"),
    WorkflowChoice("closeout_inspection", "준공검사"),
    WorkflowChoice("closeout_approved", "준공승인"),
)

# Internal event record state is retained only for history integrity (open/void,
# draft compatibility, etc.). Process Stage never reads these values directly.
STATUS_CHOICES = (
    WorkflowChoice("draft", "작성중"),
    WorkflowChoice("open", "진행중"),
    WorkflowChoice("done", "완료"),
    WorkflowChoice("void", "취소"),
)

# Only reviewed historical tokens are normalized. Unknown/custom values remain
# untouched so tenant history is never silently reinterpreted.
LEGACY_STAGE_ALIASES = {
    "pre_contract": "preparation",
    "project": "execution",
    "inspection": "execution",
    "blilling": "billing",
}

# Event category stage. This is where the event belongs in the event selector;
# it is NOT necessarily the stage reached after the event occurs.
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
}

# Historical codes remain readable/editable for production history but are not
# part of the canonical dropdown. Their old category is retained for validation.
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
    "advance_payment": "billing",
    "progress_invoice": "billing",
    "invoice": "billing",
    "tax_invoice": "billing",
    "payment": "billing",
    "etc": "execution",
}

# Only these events advance the Process Stage. Ordinary events such as 변경,
# 업무보고, 용역중지/재개 and 준공검사 never advance the lifecycle by themselves.
EVENT_TRANSITION_TARGETS = {
    "contract_signed": "contract",
    "kickoff_submitted": "kickoff",
    "kickoff_approved": "execution",
    "closeout_submitted": "closeout",
    "closeout_approved": "complete",
}

# Reviewed historical transition equivalents preserve existing production state.
LEGACY_EVENT_TRANSITION_TARGETS = {
    "contract_doc": "contract",
    "kickoff_doc": "kickoff",
    "kickoff": "execution",
    "completion_doc": "closeout",
    "closeout_complete": "complete",
}

# Exact lifecycle mapping used by the workflow summary service.
CONTRACT_LIFECYCLE_STAGE_PHASES = {
    "preparation": "preparation",
    "contract": "contract",
    "kickoff": "kickoff",
    "execution": "execution",
    "closeout": "closeout",
    "complete": "complete",
}

# Final completion is a reviewed human event under the 준공 category. The legacy
# closeout_complete event remains recognized for already-migrated history and old
# clients, but new writes are normalized to closeout_approved.
CONTRACT_COMPLETION_EVENT_TYPE = "closeout_approved"
LEGACY_CONTRACT_COMPLETION_EVENT_TYPE = "closeout_complete"
EVENT_TYPE_WRITE_ALIASES = {
    LEGACY_CONTRACT_COMPLETION_EVENT_TYPE: CONTRACT_COMPLETION_EVENT_TYPE,
}

# Known legacy system event types are hidden from the new-event dropdown while
# remaining valid historical values. Custom tenant-defined types are unaffected.
DEPRECATED_EVENT_TYPE_CODES = frozenset(LEGACY_EVENT_DEFAULT_STAGE)

# Core event stages are system-required. Tenant settings may contain extra stages,
# but these six process stages must always remain available and immutable.
REQUIRED_EVENT_STAGE_CODES = tuple(choice.code for choice in STAGE_CHOICES)


def normalize_stage(value: object) -> str:
    """Normalize only reviewed legacy aliases and preserve all other values."""

    text = str(value or "").strip()
    return LEGACY_STAGE_ALIASES.get(text, text)


def normalize_event_type_for_write(value: object) -> str:
    """Normalize reviewed legacy client writes without rewriting stored history."""

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
