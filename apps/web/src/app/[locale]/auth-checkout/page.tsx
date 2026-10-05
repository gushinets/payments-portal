import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { CheckoutClient } from "@/features/checkout";
import { LANGUAGE_TAG_BY_ROUTE_LOCALE } from "@/generated/locales";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(
    await getCurrentRouteLocale(),
    "/auth-checkout"
  );
}

export default async function AuthCheckoutPage() {
  const [messages, locale] = await Promise.all([
    getMessages(),
    getCurrentRouteLocale()
  ]);

  return (
    <NextIntlClientProvider
      messages={{
        Auth: messages.Auth,
        Checkout: messages.Checkout,
        EmailVerification: messages.EmailVerification
      }}
    >
      <CheckoutClient languageTag={LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]} />
    </NextIntlClientProvider>
  );
}
