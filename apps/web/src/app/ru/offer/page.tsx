import { LegalPageView } from "@/components/LegalPageView";
import { getLegalDocument } from "@/lib/legal";

export default async function OfferPage() {
  return <LegalPageView page={await getLegalDocument("offer")} />;
}
