import { getLegalDocument, LegalPageView } from "@/features/legal";

export default async function CookiesPage() {
  return <LegalPageView page={await getLegalDocument("cookies")} />;
}
