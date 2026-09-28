import {
  INTL_LOCALE_BY_ROUTE_LOCALE,
  type RouteLocale
} from "@/generated/locales";

export type IntlLocale =
  (typeof INTL_LOCALE_BY_ROUTE_LOCALE)[RouteLocale];

export function resolveIntlLocale(routeLocale: RouteLocale): IntlLocale {
  return INTL_LOCALE_BY_ROUTE_LOCALE[routeLocale];
}
