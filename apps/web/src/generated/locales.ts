// Generated from config/locales.json. Do not edit.

export const SUPPORTED_ROUTE_LOCALES = [
  "en",
  "fr",
  "it",
  "de",
  "es",
  "ru",
  "pt",
] as const;

export type RouteLocale = (typeof SUPPORTED_ROUTE_LOCALES)[number];

export const DEFAULT_ROUTE_LOCALE: RouteLocale = "ru";

const ROUTE_LOCALE_SET: ReadonlySet<string> = new Set(
  SUPPORTED_ROUTE_LOCALES,
);

export function isRouteLocale(value: unknown): value is RouteLocale {
  return typeof value === "string" && ROUTE_LOCALE_SET.has(value);
}

export const LANGUAGE_TAG_BY_ROUTE_LOCALE = {
  "en": "en",
  "fr": "fr",
  "it": "it",
  "de": "de",
  "es": "es",
  "ru": "ru",
  "pt": "pt-BR",
} as const satisfies Record<RouteLocale, string>;

export const INTL_LOCALE_BY_ROUTE_LOCALE = {
  "en": "en",
  "fr": "fr",
  "it": "it",
  "de": "de",
  "es": "es",
  "ru": "ru",
  "pt": "pt-BR",
} as const satisfies Record<RouteLocale, string>;

export const DISPLAY_NAME_BY_ROUTE_LOCALE = {
  "en": "English",
  "fr": "Français",
  "it": "Italiano",
  "de": "Deutsch",
  "es": "Español",
  "ru": "Русский",
  "pt": "Português",
} as const satisfies Record<RouteLocale, string>;
