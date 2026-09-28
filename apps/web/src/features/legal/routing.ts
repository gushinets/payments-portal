import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createCanonicalOnlyMetadata } from "@/i18n/metadata";

import { legalDocuments, legalRouteLocale, type LegalSlug } from "./legal";

export async function requireCanonicalLegalRoute(): Promise<void> {
  if ((await getCurrentRouteLocale()) !== legalRouteLocale) {
    notFound();
  }
}

export function createLegalMetadata(slug: LegalSlug): Metadata {
  const document = legalDocuments[slug];
  return createCanonicalOnlyMetadata(document.href, document.label);
}
