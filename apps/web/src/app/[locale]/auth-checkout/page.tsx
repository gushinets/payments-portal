import type { Metadata } from "next";

import { CheckoutClient } from "@/features/checkout";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(
    await getCurrentRouteLocale(),
    "/auth-checkout"
  );
}

export default function AuthCheckoutPage() {
  return <CheckoutClient />;
}
