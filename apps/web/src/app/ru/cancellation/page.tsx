import { getLegalDocument, LegalPageView } from "@/features/legal";

export default async function CancellationPage() {
  return <LegalPageView page={await getLegalDocument("cancellation")} />;
}
