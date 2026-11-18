"""Lossless LBX calendar normalization. Naive timestamps never acquire a zone."""

from datetime import UTC, date, datetime, time

from app.domains.billing.paid_cycles import CalendarEvidence, CalendarPrecision
from app.domains.catalog.commercial_offer import CommercialPeriod
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


def annual_calendar_date_anchor(activation: datetime, period: CommercialPeriod) -> date | None:
    """Recognize the 043 annual offer's local-midnight calendar date."""
    if (
        (period.unit, period.length, period.anchor) == ("year", 1, "calendar_month")
        and activation.utcoffset() is None
        and activation.time() == time.min
    ):
        return activation.date().replace(day=1)
    return None


def normalize_calendar(
    calendar: dict[str, str | None],
    period: CommercialPeriod,
    *,
    established_calendar: CalendarEvidence | None = None,
) -> CalendarEvidence | None:
    start = calendar.get("last_tariffication_period_start")
    end = calendar.get("last_tariffication_period_end")
    if start in EMPTY_CALENDAR or end in EMPTY_CALENDAR:
        return None
    anchor_kind = period.anchor
    anchor = calendar.get(
        "subscription_start_date" if anchor_kind == "first_instance_start" else "subscription_instance_start_date"
    )
    if anchor_kind == "calendar_month":
        anchor = calendar.get("subscription_start_date")
        # Calendar-month periods are anchored to the calendar, not activation time.
        if anchor not in EMPTY_CALENDAR:
            try:
                if len(anchor) == 10:
                    anchor = date.fromisoformat(anchor).replace(day=1).isoformat()
                else:
                    parsed = datetime.fromisoformat(anchor)
                    if parsed.utcoffset() is not None:
                        if (
                            established_calendar is not None
                            and established_calendar.precision == CalendarPrecision.TIMESTAMP
                            and established_calendar.anchor is not None
                        ):
                            established = datetime.fromisoformat(established_calendar.anchor)
                            if established.utcoffset() is not None:
                                # Derive the current month in the issued frame; a
                                # genuinely changed activation must still be detected.
                                parsed = parsed.astimezone(established.tzinfo)
                        anchor = parsed.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
                    elif len(start) == len(end) == 10 and (month := annual_calendar_date_anchor(parsed, period)):
                        anchor = month.isoformat()
            except ValueError:
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
