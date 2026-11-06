"""Calendar cycle meaning, frozen-anchor arithmetic and no-backfill classification."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domains.catalog.commercial_offer import CommercialPeriod


class CalendarPrecision(StrEnum):
    DATE = "date"
    TIMESTAMP = "timestamp"
    UNRESOLVED = "unresolved"


class CalendarEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["source-calendar:v1"] = "source-calendar:v1"
    precision: CalendarPrecision
    start: str
    end: str
    anchor: str | None


class CycleKind(StrEnum):
    FIRST = "first"
    SAME = "same"
    LATER = "later"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class CycleDecision:
    kind: CycleKind
    key: str | None = None
    evidence: CalendarEvidence | None = None


def _value(value: str, precision: str) -> date | datetime:
    if precision == "date" and len(value) == 10:
        return date.fromisoformat(value)
    if precision == "timestamp":
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is not None:
            return parsed
    raise ValueError("unresolved calendar precision")


def _shift(anchor: date | datetime, count: int, unit: str) -> date | datetime:
    if unit in {"day", "week"}:
        return anchor + timedelta(days=count * (7 if unit == "week" else 1))
    months = count * (12 if unit == "year" else 1)
    target = anchor.year * 12 + anchor.month - 1 + months
    year, month = divmod(target, 12)
    month += 1
    return anchor.replace(year=year, month=month, day=min(anchor.day, monthrange(year, month)[1]))


def _index(anchor: date | datetime, start: date | datetime, period: CommercialPeriod) -> int | None:
    if period.unit in {"day", "week"}:
        days = (start - anchor).days
        count, remainder = divmod(days, period.length * (7 if period.unit == "week" else 1))
    else:
        months = (start.year - anchor.year) * 12 + start.month - anchor.month
        count, remainder = divmod(months, period.length * (12 if period.unit == "year" else 1))
    if remainder or count < 0 or _shift(anchor, count * period.length, period.unit) != start:
        return None
    return count


def classify_cycle(
    current: CalendarEvidence | None,
    period: CommercialPeriod,
    *,
    first: CalendarEvidence | None = None,
    latest: CalendarEvidence | None = None,
) -> CycleDecision:
    ambiguous = CycleDecision(CycleKind.AMBIGUOUS)
    if (
        current is None
        or current.anchor is None
        or period.length <= 0
        or period.unit not in {"day", "week", "month", "year"}
    ):
        return ambiguous
    if (first is None) != (latest is None):
        return ambiguous
    try:
        start, end, anchor = (
            _value(value, current.precision) for value in (current.start, current.end, current.anchor)
        )
        if first is not None:
            if first.precision != current.precision or first.anchor is None:
                return ambiguous
            frozen_anchor = _value(first.anchor, first.precision)
            if anchor != frozen_anchor:
                return ambiguous
            anchor = frozen_anchor
        if isinstance(anchor, datetime):
            # Retain source spelling in evidence, but do calendar arithmetic in
            # the frozen anchor's explicit offset. Equivalent ISO encodings do
            # not manufacture a new cycle or rewrite the issued tuple.
            start, end = start.astimezone(anchor.tzinfo), end.astimezone(anchor.tzinfo)
        if period.anchor == "calendar_month":
            if period.unit not in {"month", "year"} or anchor.day != 1 or (period.unit == "year" and anchor.month != 1):
                return ambiguous
        elif period.anchor not in {"instance_start", "first_instance_start"}:
            return ambiguous
        index = _index(anchor, start, period)
        following = _shift(anchor, (index + 1) * period.length, period.unit) if index is not None else None
        expected_end = following - timedelta(days=1) if current.precision == "date" and following else following
        if index is None or end != expected_end or (start > end if current.precision == "date" else start >= end):
            return ambiguous
        key = f"{current.precision}:{start.isoformat()}:{end.isoformat()}"
        if first is None:
            return CycleDecision(CycleKind.FIRST, key, current)
        previous = _value(latest.start, latest.precision)
        previous_end = _value(latest.end, latest.precision)
        if start == previous and end == previous_end:
            return CycleDecision(CycleKind.SAME, key, current)
        if start <= previous or (start <= previous_end if current.precision == "date" else start < previous_end):
            return ambiguous
        return CycleDecision(CycleKind.LATER, key, current)
    except (ValueError, TypeError, OverflowError):
        return ambiguous
