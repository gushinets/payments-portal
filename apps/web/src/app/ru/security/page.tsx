import { LegalPageView } from "@/components/LegalPageView";
import { getLegalDocument } from "@/lib/legal";

export default async function SecurityPage() {
  return <LegalPageView page={await getLegalDocument("security")} />;
}
