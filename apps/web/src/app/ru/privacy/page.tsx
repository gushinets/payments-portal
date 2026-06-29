import { LegalPageView } from "@/components/LegalPageView";
import { legalPages } from "@/lib/legal";

export default function PrivacyPage() {
  return <LegalPageView page={legalPages.privacy} />;
}
