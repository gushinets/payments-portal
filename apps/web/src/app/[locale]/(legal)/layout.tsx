import { requireCanonicalLegalRoute } from "@/features/legal";

export default async function LegalLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  await requireCanonicalLegalRoute();

  return children;
}
