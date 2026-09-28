"use client";

import { Languages } from "lucide-react";
import { useSearchParams } from "next/navigation";

import {
  DISPLAY_NAME_BY_ROUTE_LOCALE,
  LANGUAGE_TAG_BY_ROUTE_LOCALE,
  SUPPORTED_ROUTE_LOCALES,
  type RouteLocale
} from "@/generated/locales";
import { Link, usePathname } from "@/i18n/navigation";
import {
  CANONICAL_LEGAL_LOCALE_PREFIX,
  CANONICAL_LEGAL_PATHS
} from "@/shared/config/legal-links";

const localeSwitchingBlockedPathnames = new Set([
  "/reset-password",
  ...CANONICAL_LEGAL_PATHS.map((pathname) =>
    pathname.slice(CANONICAL_LEGAL_LOCALE_PREFIX.length)
  )
]);

export function isLocaleSwitchingBlockedPathname(pathname: string): boolean {
  return localeSwitchingBlockedPathnames.has(pathname);
}

export function LocaleSwitcher({ locale }: { locale: RouteLocale }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  if (isLocaleSwitchingBlockedPathname(pathname)) {
    return null;
  }

  const query = searchParams.toString();
  const destination = query ? `${pathname}?${query}` : pathname;

  return (
    <details className="locale-switcher">
      <summary
        className="locale-switcher-summary"
        aria-label={`Выбор языка. Текущий язык: ${DISPLAY_NAME_BY_ROUTE_LOCALE[locale]}`}
      >
        <Languages size={15} aria-hidden="true" />
        <span>{DISPLAY_NAME_BY_ROUTE_LOCALE[locale]}</span>
      </summary>
      <nav className="locale-switcher-menu" aria-label="Выбор языка">
        {SUPPORTED_ROUTE_LOCALES.map((routeLocale) => (
          <Link
            className="locale-switcher-link"
            href={destination}
            hrefLang={LANGUAGE_TAG_BY_ROUTE_LOCALE[routeLocale]}
            locale={routeLocale}
            aria-current={routeLocale === locale ? "page" : undefined}
            key={routeLocale}
          >
            <span lang={LANGUAGE_TAG_BY_ROUTE_LOCALE[routeLocale]}>
              {DISPLAY_NAME_BY_ROUTE_LOCALE[routeLocale]}
            </span>
          </Link>
        ))}
      </nav>
    </details>
  );
}
