import { getLegalDocument, LegalPageView } from "@/features/legal";

export default async function ConsentPersonalDataPage() {
  return <LegalPageView page={await getLegalDocument("consent-personal-data")} />;
}
