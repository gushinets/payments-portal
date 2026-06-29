import { LegalPageView } from "@/components/LegalPageView";
import { legalPages } from "@/lib/legal";

export default function CancellationPage() {
  return <LegalPageView page={legalPages.cancellation} />;
}
