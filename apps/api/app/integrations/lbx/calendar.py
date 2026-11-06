"""Lossless LBX calendar normalization. Naive timestamps never acquire a zone."""

from datetime import UTC, date, datetime

from app.domains.billing.paid_cycles import CalendarEvidence

from app.integrations.lbx.financial import EMPTY_CALENDAR


def normalize_access_end(value: str | None) -> datetime | None:
    """Only an explicit zoned instant establishes a finite access boundary."""
    if value in EMPTY_CALENDAR or len(value) == 10:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None


def normalize_calendar(calendar: dict[str, str | None], anchor_kind: str) -> CalendarEvidence | None:
    start = calendar.get("last_tariffication_period_start")
    end = calendar.get("last_tariffication_period_end")
    anchor = calendar.get(
        "subscription_start_date" if anchor_kind == "first_instance_start" else "subscription_instance_start_date"
    )
    if anchor_kind == "calendar_month":
        anchor = calendar.get("subscription_start_date")
        # Calendar-month periods are anchored to the calendar, not activation time.
        if anchor and len(anchor) == 10:
            try:
                anchor = date.fromisoformat(anchor).replace(day=1).isoformat()
            except ValueError:
                return None
    if start in EMPTY_CALENDAR or end in EMPTY_CALENDAR:
        return None
    values = [start, end] + ([anchor] if anchor not in EMPTY_CALENDAR else [])
    try:
        if all(len(value) == 10 for value in values):
            for value in values:
                date.fromisoformat(value)
            precision = "date"
        elif all(len(value) > 10 and datetime.fromisoformat(value).utcoffset() is not None for value in values):
            precision = "timestamp"
        else:
            precision = "unresolved"
    except ValueError:
        return None
    return CalendarEvidence(
        precision=precision, start=start, end=end, anchor=anchor if anchor not in EMPTY_CALENDAR else None
    )
