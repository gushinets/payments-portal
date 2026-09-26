import type { Metadata } from "next";

import { PaymentResultClient } from "@/features/payment-result";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(
    await getCurrentRouteLocale(),
    "/payment-result"
  );
}

export default function PaymentResultPage() {
  return <PaymentResultClient />;
}
