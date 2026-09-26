import type { Metadata } from "next";

import {
  LANGUAGE_TAG_BY_ROUTE_LOCALE,
  SUPPORTED_ROUTE_LOCALES,
  type RouteLocale
} from "@/generated/locales";

const DEFAULT_TITLE = "AnytoolAI - RU";
const DEFAULT_DESCRIPTION =
  "RU-версия платформы цифровых сервисов AnytoolAI.";

function loadMetadataBase(): URL {
  const configuredBaseUrl = process.env.APP_PUBLIC_BASE_URL;

  if (!configuredBaseUrl) {
    throw new Error("APP_PUBLIC_BASE_URL is required for web metadata");
  }

  const metadataBase = new URL(configuredBaseUrl);

  if (
    !["http:", "https:"].includes(metadataBase.protocol) ||
    metadataBase.username ||
    metadataBase.password ||
    metadataBase.pathname !== "/" ||
    metadataBase.search ||
    metadataBase.hash
  ) {
    throw new Error("APP_PUBLIC_BASE_URL must be an HTTP(S) origin");
  }

  return metadataBase;
}

export const APP_METADATA_BASE = loadMetadataBase();

function localizedPath(routeLocale: RouteLocale, pathname: string): string {
  const suffix = pathname === "/" ? "" : pathname;
  return `/${routeLocale}${suffix}`;
}

export function createLocalizedMetadata(
  routeLocale: RouteLocale,
  pathname: string
): Metadata {
  const canonicalPath = localizedPath(routeLocale, pathname);
  const languages = Object.fromEntries(
    SUPPORTED_ROUTE_LOCALES.map((alternateLocale) => [
      LANGUAGE_TAG_BY_ROUTE_LOCALE[alternateLocale],
      new URL(
        localizedPath(alternateLocale, pathname),
        APP_METADATA_BASE
      ).href
    ])
  );

  return {
    metadataBase: APP_METADATA_BASE,
    title: DEFAULT_TITLE,
    description: DEFAULT_DESCRIPTION,
    alternates: {
      canonical: new URL(canonicalPath, APP_METADATA_BASE).href,
      languages
    }
  };
}

export function createCanonicalOnlyMetadata(
  canonicalPath: string,
  title: string
): Metadata {
  return {
    metadataBase: APP_METADATA_BASE,
    title,
    alternates: {
      canonical: new URL(canonicalPath, APP_METADATA_BASE).href
    }
  };
}
