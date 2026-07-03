import { LegalPageView } from "@/components/LegalPageView";
import { getLegalDocument } from "@/lib/legal";

export default async function CookiesPage() {
  return <LegalPageView page={await getLegalDocument("cookies")} />;
}
