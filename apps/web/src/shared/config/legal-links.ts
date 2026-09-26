import legalManifest from "@/generated/legal-manifest.json";

function generatedLegalPath(slug: string): string {
  const document = legalManifest.documents.find((item) => item.slug === slug);

  if (!document) {
    throw new Error(`Generated legal document is missing: ${slug}`);
  }

  return document.urlPath;
}

export const CANONICAL_LEGAL_PATH_BY_SLUG = {
  privacy: generatedLegalPath("privacy"),
  "consent-personal-data": generatedLegalPath("consent-personal-data"),
  offer: generatedLegalPath("offer"),
  cancellation: generatedLegalPath("cancellation"),
  cookies: generatedLegalPath("cookies"),
  security: generatedLegalPath("security")
} as const;

export const CANONICAL_LEGAL_PATHS = Object.values(
  CANONICAL_LEGAL_PATH_BY_SLUG
);

export const CANONICAL_LEGAL_LOCALE_PREFIX = `/${legalManifest.region}`;
