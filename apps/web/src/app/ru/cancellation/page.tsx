import { LegalPageView } from "@/components/LegalPageView";
import { getLegalDocument } from "@/lib/legal";

export default async function CancellationPage() {
  return <LegalPageView page={await getLegalDocument("cancellation")} />;
}
