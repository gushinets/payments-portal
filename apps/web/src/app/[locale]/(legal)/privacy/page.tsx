import type { Metadata } from "next";

import {
  createLegalMetadata,
  getLegalDocument,
  LegalPageView,
  requireCanonicalLegalRoute
} from "@/features/legal";

export async function generateMetadata(): Promise<Metadata> {
  await requireCanonicalLegalRoute();
  return createLegalMetadata("privacy");
}

export default async function PrivacyPage() {
  return <LegalPageView page={await getLegalDocument("privacy")} />;
}
