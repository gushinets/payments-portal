import type { Metadata } from "next";

import {
  createLegalMetadata,
  getLegalDocument,
  LegalPageView,
  requireCanonicalLegalRoute
} from "@/features/legal";

export async function generateMetadata(): Promise<Metadata> {
  await requireCanonicalLegalRoute();
  return createLegalMetadata("security");
}

export default async function SecurityPage() {
  return <LegalPageView page={await getLegalDocument("security")} />;
}
