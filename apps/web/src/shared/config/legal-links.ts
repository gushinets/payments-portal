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

// Exact grammatical anchors in the generated RU acceptance statements.
// Keep these fragments coupled to generated/registration-acceptance.ts; the
// AuthForm characterization test fails if a generated statement drops one.
export const REGISTRATION_ACCEPTANCE_SOURCE_LINKS = {
  personal: [
    {
      text: "Согласием на обработку персональных данных",
      href: CANONICAL_LEGAL_PATH_BY_SLUG["consent-personal-data"]
    },
    {
      text: "Политикой в отношении обработки персональных данных",
      href: CANONICAL_LEGAL_PATH_BY_SLUG.privacy
    }
  ],
  offer: [
    {
      text: "Публичной оферты",
      href: CANONICAL_LEGAL_PATH_BY_SLUG.offer
    }
  ]
} as const;
