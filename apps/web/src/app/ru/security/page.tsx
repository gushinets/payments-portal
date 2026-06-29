import { LegalPageView } from "@/components/LegalPageView";
import { legalPages } from "@/lib/legal";

export default function SecurityPage() {
  return <LegalPageView page={legalPages.security} />;
}
