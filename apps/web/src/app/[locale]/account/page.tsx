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

export default async function AccountPage() {
  const [messages, locale] = await Promise.all([
    getMessages(),
    getCurrentRouteLocale()
  ]);

  return (
    <NextIntlClientProvider
      messages={{
        Account: messages.Account,
        EmailVerification: messages.EmailVerification
      }}
    >
      <AccountClient languageTag={LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]} />
    </NextIntlClientProvider>
  );
}
