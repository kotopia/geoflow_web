from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


SPACE = re.compile(r"\s+")


def normalized(value: object) -> str:
    return SPACE.sub("", str(value or "")).casefold()


def terms(row: dict[str, Any]) -> list[str]:
    values = [row.get("code"), row.get("name"), *(row.get("aliases") or [])]
    return [normalized(value) for value in values if normalized(value)]


def any_term(haystack: str, rows: Iterable[dict[str, Any]]) -> list[str]:
    matches = []
    for row in rows:
        if any(term in haystack for term in terms(row)):
            matches.append(str(row.get("name") or row.get("code") or ""))
    return matches


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    needs_review: bool
    reasons: list[dict[str, Any]]


def evaluate_notice(notice: dict[str, Any], filters: dict[str, list[dict[str, Any]]]) -> MatchResult:
    title = normalized(notice.get("title"))
    raw_text = normalized(notice.get("search_text"))
    region_text = normalized(notice.get("region_text"))
    industry_text = normalized(notice.get("industry_text"))
    agency_text = normalized(" ".join(filter(None, [notice.get("notice_agency_name"), notice.get("demand_agency_name")])))
    reasons: list[dict[str, Any]] = []
    needs_review = False

    if not any(filters.get(kind) for kind in ("region", "industry", "agency", "include")):
        return MatchResult(False, False, [{"kind": "configuration", "values": []}])

    excludes = [row for row in filters.get("exclude", []) if normalized(row.get("keyword"))]
    excluded = [row["keyword"] for row in excludes if normalized(row["keyword"]) in raw_text]
    if excluded:
        return MatchResult(False, False, [{"kind": "exclude", "values": excluded}])

    checks = (
        ("region", region_text, filters.get("region", [])),
        ("industry", industry_text, filters.get("industry", [])),
        ("agency", agency_text, filters.get("agency", [])),
    )
    for kind, haystack, rows in checks:
        if not rows:
            continue
        if not haystack:
            needs_review = True
            reasons.append({"kind": kind, "values": [], "uncertain": True})
            continue
        if kind == "region" and any(value in haystack for value in ("전국", "지역제한없음", "제한없음")):
            reasons.append({"kind": kind, "values": ["전국"]})
            continue
        if kind == "industry" and any(
            value in haystack for value in ("업종제한없음", "면허제한없음", "제한없음")
        ):
            reasons.append({"kind": kind, "values": ["업종제한 없음"]})
            continue
        matched_values = any_term(haystack, rows)
        if not matched_values:
            return MatchResult(False, False, reasons + [{"kind": kind, "values": []}])
        reasons.append({"kind": kind, "values": matched_values})

    includes = [row for row in filters.get("include", []) if normalized(row.get("keyword"))]
    if includes:
        matched_keywords = [row["keyword"] for row in includes if normalized(row["keyword"]) in title]
        if not matched_keywords:
            return MatchResult(False, False, reasons + [{"kind": "include", "values": []}])
        reasons.append({"kind": "include", "values": matched_keywords})

    return MatchResult(True, needs_review, reasons)
