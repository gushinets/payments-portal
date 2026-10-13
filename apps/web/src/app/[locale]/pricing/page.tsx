import type { Metadata } from "next";

import { PricingOverview } from "@/features/pricing";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/pricing");
}

export default function PricingPage() {
  return <PricingOverview />;
}
