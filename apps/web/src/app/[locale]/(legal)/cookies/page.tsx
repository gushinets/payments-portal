import type { Metadata } from "next";

import {
  createLegalMetadata,
  getLegalDocument,
  LegalPageView,
  requireCanonicalLegalRoute
} from "@/features/legal";

export async function generateMetadata(): Promise<Metadata> {
  await requireCanonicalLegalRoute();
  return createLegalMetadata("cookies");
}

export default async function CookiesPage() {
  return <LegalPageView page={await getLegalDocument("cookies")} />;
}
