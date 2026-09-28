import type { Metadata } from "next";

import {
  createLegalMetadata,
  getLegalDocument,
  LegalPageView,
  requireCanonicalLegalRoute
} from "@/features/legal";

export async function generateMetadata(): Promise<Metadata> {
  await requireCanonicalLegalRoute();
  return createLegalMetadata("cancellation");
}

export default async function CancellationPage() {
  return <LegalPageView page={await getLegalDocument("cancellation")} />;
}
