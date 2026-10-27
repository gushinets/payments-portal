import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { AccountClient } from "@/features/account";
import { LANGUAGE_TAG_BY_ROUTE_LOCALE } from "@/generated/locales";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/account");
}

export default async function AccountPage({ searchParams }: { searchParams: Promise<{ purchase?: string | string[] }> }) {
  const [messages, locale, query] = await Promise.all([
    getMessages(),
    getCurrentRouteLocale(),
    searchParams
  ]);

  return (
    <NextIntlClientProvider
      messages={{
        Auth: messages.Auth,
        Account: messages.Account,
        Billing: messages.Billing,
        Purchase: messages.Purchase,
        EmailVerification: messages.EmailVerification
      }}
    >
      <AccountClient languageTag={LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]} initialPurchaseId={typeof query.purchase === "string" ? query.purchase : undefined} />
    </NextIntlClientProvider>
  );
}
