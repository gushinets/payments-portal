"""Generated from config/locales.json. Do not edit."""

from typing import Final, Literal, TypeGuard

RouteLocale = Literal['en', 'fr', 'it', 'de', 'es', 'ru', 'pt']

SUPPORTED_ROUTE_LOCALES: Final[tuple[RouteLocale, ...]] = (
    'en',
    'fr',
    'it',
    'de',
    'es',
    'ru',
    'pt',
)
DEFAULT_ROUTE_LOCALE: Final[RouteLocale] = 'ru'

_ROUTE_LOCALE_SET: Final[frozenset[str]] = frozenset(
    SUPPORTED_ROUTE_LOCALES
)


def is_route_locale(value: object) -> TypeGuard[RouteLocale]:
    return isinstance(value, str) and value in _ROUTE_LOCALE_SET


LANGUAGE_TAG_BY_ROUTE_LOCALE: Final[dict[RouteLocale, str]] = {
    'en': 'en',
    'fr': 'fr',
    'it': 'it',
    'de': 'de',
    'es': 'es',
    'ru': 'ru',
    'pt': 'pt-BR',
}


INTL_LOCALE_BY_ROUTE_LOCALE: Final[dict[RouteLocale, str]] = {
    'en': 'en',
    'fr': 'fr',
    'it': 'it',
    'de': 'de',
    'es': 'es',
    'ru': 'ru',
    'pt': 'pt-BR',
}


DISPLAY_NAME_BY_ROUTE_LOCALE: Final[dict[RouteLocale, str]] = {
    'en': 'English',
    'fr': 'Français',
    'it': 'Italiano',
    'de': 'Deutsch',
    'es': 'Español',
    'ru': 'Русский',
    'pt': 'Português',
}
