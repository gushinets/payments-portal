import type { Metadata } from "next";

import {
  createLegalMetadata,
  getLegalDocument,
  LegalPageView,
  requireCanonicalLegalRoute
} from "@/features/legal";

export async function generateMetadata(): Promise<Metadata> {
  await requireCanonicalLegalRoute();
  return createLegalMetadata("offer");
}

export default async function OfferPage() {
  return <LegalPageView page={await getLegalDocument("offer")} />;
}
