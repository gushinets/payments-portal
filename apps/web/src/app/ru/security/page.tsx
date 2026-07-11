import { getLegalDocument, LegalPageView } from "@/features/legal";

export default async function SecurityPage() {
  return <LegalPageView page={await getLegalDocument("security")} />;
}
