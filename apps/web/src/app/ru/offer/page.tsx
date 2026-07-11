import { getLegalDocument, LegalPageView } from "@/features/legal";

export default async function OfferPage() {
  return <LegalPageView page={await getLegalDocument("offer")} />;
}
