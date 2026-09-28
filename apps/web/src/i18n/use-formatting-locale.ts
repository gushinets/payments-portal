"use client";

import { useLocale } from "next-intl";

import { isRouteLocale } from "@/generated/locales";

import { resolveIntlLocale, type IntlLocale } from "./formatting-locale";

export function useIntlLocale(): IntlLocale {
  const routeLocale = useLocale();

  if (!isRouteLocale(routeLocale)) {
    throw new Error(`Unsupported next-intl route locale: ${routeLocale}`);
  }

  return resolveIntlLocale(routeLocale);
}
