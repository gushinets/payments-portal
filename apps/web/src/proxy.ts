import { match } from "@formatjs/intl-localematcher";
import Negotiator from "negotiator";
import { type NextRequest, NextResponse } from "next/server";

import {
  DEFAULT_ROUTE_LOCALE,
  LANGUAGE_TAG_BY_ROUTE_LOCALE,
  SUPPORTED_ROUTE_LOCALES,
  type RouteLocale
} from "@/generated/locales";

const supportedLanguageTags = SUPPORTED_ROUTE_LOCALES.map(
  (routeLocale) => LANGUAGE_TAG_BY_ROUTE_LOCALE[routeLocale]
);
const defaultLanguageTag =
  LANGUAGE_TAG_BY_ROUTE_LOCALE[DEFAULT_ROUTE_LOCALE];
const routeLocaleByLanguageTag: ReadonlyMap<string, RouteLocale> = new Map(
  SUPPORTED_ROUTE_LOCALES.map(
    (routeLocale) =>
      [LANGUAGE_TAG_BY_ROUTE_LOCALE[routeLocale], routeLocale] as const
  )
);

function usableLanguageTags(languages: string[]): string[] {
  return languages.flatMap((language) => {
    if (language === "*") {
      return [];
    }

    try {
      return Intl.getCanonicalLocales(language);
    } catch {
      return [];
    }
  });
}

export function proxy(request: NextRequest): NextResponse {
  if (request.nextUrl.pathname !== "/") {
    return NextResponse.next();
  }

  const requestedLanguages = usableLanguageTags(
    new Negotiator({
      headers: {
        "accept-language": request.headers.get("accept-language") ?? undefined
      }
    }).languages()
  );
  const matchedLanguageTag =
    requestedLanguages.length > 0
      ? match(
          requestedLanguages,
          supportedLanguageTags,
          defaultLanguageTag,
          { algorithm: "best fit" }
        )
      : defaultLanguageTag;
  const routeLocale =
    routeLocaleByLanguageTag.get(matchedLanguageTag) ?? DEFAULT_ROUTE_LOCALE;

  return NextResponse.redirect(new URL(`/${routeLocale}`, request.url));
}

export const config = {
  matcher: ["/"]
};
