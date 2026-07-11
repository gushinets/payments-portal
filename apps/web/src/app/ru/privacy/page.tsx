import { getLegalDocument, LegalPageView } from "@/features/legal";

export default async function PrivacyPage() {
  return <LegalPageView page={await getLegalDocument("privacy")} />;
}
