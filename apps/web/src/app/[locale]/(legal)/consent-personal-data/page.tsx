import type { Metadata } from "next";

import {
  createLegalMetadata,
  getLegalDocument,
  LegalPageView,
  requireCanonicalLegalRoute
} from "@/features/legal";

export async function generateMetadata(): Promise<Metadata> {
  await requireCanonicalLegalRoute();
  return createLegalMetadata("consent-personal-data");
}

export default async function ConsentPersonalDataPage() {
  return <LegalPageView page={await getLegalDocument("consent-personal-data")} />;
}
