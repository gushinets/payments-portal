import { LegalPageView } from "@/components/LegalPageView";
import { getLegalDocument } from "@/lib/legal";

export default async function PrivacyPage() {
  return <LegalPageView page={await getLegalDocument("privacy")} />;
}
