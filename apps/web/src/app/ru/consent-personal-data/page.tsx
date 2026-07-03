import { LegalPageView } from "@/components/LegalPageView";
import { getLegalDocument } from "@/lib/legal";

export default async function ConsentPersonalDataPage() {
  return <LegalPageView page={await getLegalDocument("consent-personal-data")} />;
}
