import { LegalPageView } from "@/components/LegalPageView";
import { legalPages } from "@/lib/legal";

export default function CookiesPage() {
  return <LegalPageView page={legalPages.cookies} />;
}
