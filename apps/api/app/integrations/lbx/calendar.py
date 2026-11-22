"""Lossless LBX calendar normalization. Naive timestamps never acquire a zone."""

from datetime import UTC, date, datetime, time

from app.domains.billing.paid_cycles import CalendarEvidence, CalendarPrecision
from app.domains.catalog.commercial_offer import CommercialPeriod

from app.integrations.lbx.financial import EMPTY_CALENDAR


_MIDNIGHT_DATE_PROFILES = frozenset({("month", 1, "instance_start"), ("day", 1, "first_instance_start")})


def normalize_access_end(value: str | None) -> datetime | None:
    """Only an explicit zoned instant establishes a finite access boundary."""
    if value in EMPTY_CALENDAR or len(value) == 10:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None


def instance_start_calendar_date(value: date | datetime, period: CommercialPeriod) -> date | None:
    """Interpret a start only in a date-cycle profile observed on LBX.

    Callers establish date-only cycle bounds. A naive midnight is a calendar
    representation, never proof of a timezone or an exact access deadline.
    """
    if (period.unit, period.length, period.anchor) not in _MIDNIGHT_DATE_PROFILES:
        return None
    if isinstance(value, datetime):
        if value.utcoffset() is not None or value.time() != time.min:
            return None
        return value.date()
    return value


def normalize_calendar(calendar: dict[str, str | None], period: CommercialPeriod) -> CalendarEvidence | None:
    start = calendar.get("last_tariffication_period_start")
    end = calendar.get("last_tariffication_period_end")
    anchor = calendar.get(
        "subscription_start_date" if period.anchor == "first_instance_start" else "subscription_instance_start_date"
    )
    if period.anchor == "calendar_month":
        anchor = calendar.get("subscription_start_date")
        # Calendar-month periods are anchored to the calendar, not activation time.
        if anchor not in EMPTY_CALENDAR:
            try:
                if len(anchor) == 10:
                    anchor = date.fromisoformat(anchor).replace(day=1).isoformat()
                else:
                    parsed = datetime.fromisoformat(anchor)
                    if parsed.utcoffset() is not None:
                        anchor = parsed.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            except ValueError:
                return None
    if start in EMPTY_CALENDAR or end in EMPTY_CALENDAR:
        return None
    try:
        if len(start) == 10 and len(end) == 10 and anchor not in EMPTY_CALENDAR:
            parsed_anchor = date.fromisoformat(anchor) if len(anchor) == 10 else datetime.fromisoformat(anchor)
            calendar_anchor = instance_start_calendar_date(parsed_anchor, period)
            if calendar_anchor is not None:
                # Epoch is missing evidence, including equivalent midnight spellings.
                if calendar_anchor == date(1970, 1, 1):
                    return None
                anchor = calendar_anchor.isoformat()
        values = [start, end] + ([anchor] if anchor not in EMPTY_CALENDAR else [])
        if all(len(value) == 10 for value in values):
            for value in values:
                date.fromisoformat(value)
            precision = CalendarPrecision.DATE
        elif all(len(value) > 10 and datetime.fromisoformat(value).utcoffset() is not None for value in values):
            precision = CalendarPrecision.TIMESTAMP
        else:
            precision = CalendarPrecision.UNRESOLVED
    except ValueError:
        return None
    return CalendarEvidence(
        precision=precision, start=start, end=end, anchor=anchor if anchor not in EMPTY_CALENDAR else None
    )
