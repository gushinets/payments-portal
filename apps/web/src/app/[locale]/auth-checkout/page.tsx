import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { CheckoutClient } from "@/features/checkout";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(
    await getCurrentRouteLocale(),
    "/auth-checkout"
  );
}

export default async function AuthCheckoutPage() {
  const messages = await getMessages();

  return (
    <NextIntlClientProvider
      messages={{ Auth: messages.Auth, Checkout: messages.Checkout }}
    >
      <CheckoutClient />
    </NextIntlClientProvider>
  );
}
