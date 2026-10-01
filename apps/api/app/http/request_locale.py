from __future__ import annotations

import re

from app.generated.locales import (
    DEFAULT_ROUTE_LOCALE,
    LANGUAGE_TAG_BY_ROUTE_LOCALE,
    RouteLocale,
)


_ROUTE_LOCALE_BY_LANGUAGE_TAG: dict[str, RouteLocale] = {
    language_tag.casefold(): route_locale for route_locale, language_tag in LANGUAGE_TAG_BY_ROUTE_LOCALE.items()
}
if len(_ROUTE_LOCALE_BY_LANGUAGE_TAG) != len(LANGUAGE_TAG_BY_ROUTE_LOCALE):
    raise RuntimeError("Generated locale language tags must be unique after case-folding")
_ACCEPT_LANGUAGE_QVALUE = re.compile(r"(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)\Z")


def normalize_request_language(value: str | None) -> RouteLocale:
    if not value:
        return DEFAULT_ROUTE_LOCALE

    best_route_locale: RouteLocale | None = None
    best_quality = 0
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue

        segments = [segment.strip() for segment in item.split(";")]
        if len(segments) not in (1, 2):
            continue

        route_locale = _ROUTE_LOCALE_BY_LANGUAGE_TAG.get(segments[0].casefold())
        if route_locale is None:
            continue

        quality = 1000
        if len(segments) == 2:
            parameter_name, separator, qvalue = segments[1].partition("=")
            if (
                separator != "="
                or parameter_name.casefold() != "q"
                or _ACCEPT_LANGUAGE_QVALUE.fullmatch(qvalue) is None
            ):
                continue
            if qvalue.startswith("1"):
                quality = 1000
            else:
                _, _, fraction = qvalue.partition(".")
                quality = int(fraction.ljust(3, "0")) if fraction else 0

        if quality > best_quality:
            best_route_locale = route_locale
            best_quality = quality

    return best_route_locale or DEFAULT_ROUTE_LOCALE
